"""Quote-time design review: orientation, load across the layers, and holes.

Not a DFM pass. FDM tolerates most geometry, and the slicer already handles support and drops
features it cannot print. This catches the few things that make a functional printed part fail
or disappoint, and ties them to the material the engine has just recommended.

It runs once the material and the requirements are known, because that is when the thresholds
(a TPU wall, a nylon hole allowance) and the load are known. The upload-time checks in
findings.py are re-run here with the material's thresholds and in the orientation that will
actually print, so the customer sees one consistent set.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient as orient_polygon
from shapely.ops import unary_union

from . import findings as checks
from .geometry import analyse_mesh, largest_build_volume, overhang_mask
from .materials import Material, design_rules, load_materials
from .orientation import (
    AXIS_NAMES,
    FACE_AXIS,
    FACE_DIRECTIONS,
    FACE_PHRASES,
    face_down_transform,
    orient_mesh,
)
from .schemas import (
    DesignFinding,
    FindingLocation,
    GeometryReport,
    OrientationCandidate,
    OrientationChoice,
    Requirements,
    Severity,
)
from .slicing import EFFECTIVE_FLOW_MM3_S, LAYER_OVERHEAD_S, extruded_volume_mm3

BAND_SEVERITY = {"adequate": Severity.INFO, "marginal": Severity.ADVISE, "weak": Severity.MUST_FIX}


@dataclass
class DesignReview:
    """What the quote needs from the review."""

    # As uploaded, with findings and the orientation decision: what the customer is shown.
    geometry: GeometryReport
    # Measured in the orientation it will print in: what slicing and pricing run on.
    print_geometry: GeometryReport
    face_down: str


# --------------------------------------------------------------------------------------
# Section properties
# --------------------------------------------------------------------------------------


def section_modulus_min(polygon: Polygon) -> float:
    """Smallest elastic section modulus of a planar section, over every bending axis.

    Second moments by Green's theorem over the boundary, holes included; the principal axes
    give the extreme values, and the weaker of the two is the one that breaks.
    """
    shape = orient_polygon(polygon, 1.0)  # exterior anticlockwise, holes clockwise
    area = sx = sy = ixx = iyy = ixy = 0.0
    for ring in (shape.exterior, *shape.interiors):
        c = np.asarray(ring.coords)
        x, y, x1, y1 = c[:-1, 0], c[:-1, 1], c[1:, 0], c[1:, 1]
        cross = x * y1 - x1 * y
        area += cross.sum() / 2
        sx += ((x + x1) * cross).sum() / 6
        sy += ((y + y1) * cross).sum() / 6
        ixx += ((y * y + y * y1 + y1 * y1) * cross).sum() / 12
        iyy += ((x * x + x * x1 + x1 * x1) * cross).sum() / 12
        ixy += ((x * y1 + 2 * x * y + 2 * x1 * y1 + x1 * y) * cross).sum() / 24
    if area <= 1e-9:
        return 0.0
    cx, cy = sx / area, sy / area
    ixx -= area * cy * cy
    iyy -= area * cx * cx
    ixy -= area * cx * cy

    tensor = np.array([[ixx, -ixy], [-ixy, iyy]])
    values, vectors = np.linalg.eigh(tensor)
    points = np.asarray(shape.exterior.coords) - (cx, cy)
    moduli = []
    for inertia, (ex, ey) in zip(values, vectors.T, strict=True):
        extreme = float(np.abs(-ey * points[:, 0] + ex * points[:, 1]).max())
        if extreme > 1e-9:
            moduli.append(float(inertia) / extreme)
    return min(moduli) if moduli else 0.0


@dataclass
class AxisStrength:
    """The weakest layer interface if the layers stack along one model axis."""

    axis: int
    safety_factor: float
    stress_mpa: float
    strength_mpa: float
    lever_mm: float
    modulus_mm3: float
    position_mm: float  # from the part's lowest point along the axis
    extent_mm: float
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]


def solid_bodies(mesh: trimesh.Trimesh) -> list[trimesh.Trimesh] | None:
    """The mesh's separate bodies, or None if any of them is open.

    CAD exports often hand over a part as several bodies that touch or overlap. Cut as one mesh,
    their coincident faces close into section loops that are not there; cut one body at a time
    each section is sound, and the pieces can be merged afterwards. An open body has no sound
    sections at all.
    """
    # repair=False: split would otherwise patch the very holes this is meant to notice.
    bodies = mesh.split(only_watertight=False, repair=False)
    if not bodies or not all(body.is_watertight for body in bodies):
        return None
    return list(bodies)


def axis_strength(
    bodies: list[trimesh.Trimesh],
    axis: int,
    material: Material,
    load_n: float,
    rules: dict[str, Any],
) -> AxisStrength | None:
    """Interlayer bending check with layers stacked along `axis`.

    We do not know which way the load pushes. The proxy assumes a sideways load at the far end
    of the part, as on a cantilever bracket, and finds the layer interface where that bends the
    bond hardest: the largest (distance to the far end) / (section modulus). A tall thin member
    standing across the layers scores badly; the same member lying in the layers does not.

    The far end is taken to be the slighter one, as a bracket's web is slighter than the base it
    is fixed by, so the weak point lands at the root rather than at the free tip. When both ends
    are alike there is no telling which is fixed, and the distance to either end is used.
    """
    load_rules = rules.get("load", {})
    lower = np.min([b.bounds[0] for b in bodies], axis=0)
    upper = np.max([b.bounds[1] for b in bodies], axis=0)
    extent = float(upper[axis] - lower[axis])
    if extent <= 0 or load_n <= 0:
        return None
    start, stop = load_rules.get("slice_span", [0.05, 0.95])
    offsets = np.linspace(start, stop, int(load_rules.get("slices", 40))) * extent
    normal = np.zeros(3)
    normal[axis] = 1.0

    # Every body is cut by the same planes from the same origin, so their sections share one
    # 2D frame and can be merged layer by layer.
    pieces: list[list] = [[] for _ in offsets]
    frames: list = [None for _ in offsets]
    for body in bodies:
        try:
            sections = body.section_multiplane(
                plane_origin=lower, plane_normal=normal, heights=offsets
            )
        except Exception:
            return None
        for i, section in enumerate(sections):
            if section is not None and section.polygons_full:
                pieces[i].extend(section.polygons_full)
                frames[i] = section.metadata.get("to_3D", np.eye(4))

    slices = []
    for offset, polygons, to_3d in zip(offsets, pieces, frames, strict=True):
        if not polygons:
            continue
        # A hundredth of a millimetre closes the hairline gaps floating point leaves between
        # bodies that only touch; it is far below anything the nozzle could print.
        merged = unary_union([p.buffer(0.01) for p in polygons]).buffer(-0.01)
        shapes = list(getattr(merged, "geoms", [merged]))
        slices.append((float(offset), shapes, to_3d))
    if not slices:
        return None

    ends = max(1, len(slices) // 10)
    low_end = sum(sum(p.area for p in shapes) for _, shapes, _ in slices[:ends])
    high_end = sum(sum(p.area for p in shapes) for _, shapes, _ in slices[-ends:])
    if high_end < low_end * 0.8:
        free_end = extent  # the high end is the slighter one, so it carries the load
    elif low_end < high_end * 0.8:
        free_end = 0.0
    else:
        free_end = None

    strength = material.tensile_mpa * material.z_strength_ratio
    worst: AxisStrength | None = None
    for offset, shapes, to_3d in slices:
        lever = max(offset, extent - offset) if free_end is None else abs(free_end - offset)
        if lever <= 0:
            continue
        for polygon in shapes:
            modulus = section_modulus_min(polygon)
            if modulus <= 0:
                continue
            stress = load_n * lever / modulus
            factor = strength / stress
            if worst is None or factor < worst.safety_factor:
                minx, miny, maxx, maxy = polygon.bounds
                corners = trimesh.transform_points(
                    np.array([[minx, miny, 0.0], [maxx, maxy, 0.0]]), to_3d
                )
                worst = AxisStrength(
                    axis=axis,
                    safety_factor=factor,
                    stress_mpa=stress,
                    strength_mpa=strength,
                    lever_mm=lever,
                    modulus_mm3=modulus,
                    position_mm=float(offset),
                    extent_mm=extent,
                    bbox_min=tuple(float(v) for v in corners.min(axis=0)),
                    bbox_max=tuple(float(v) for v in corners.max(axis=0)),
                )
    return worst


def band(safety_factor: float, rules: dict[str, Any]) -> str:
    load_rules = rules.get("load", {})
    if safety_factor >= float(load_rules.get("adequate_at_least", 2.0)):
        return "adequate"
    if safety_factor >= float(load_rules.get("marginal_at_least", 1.0)):
        return "marginal"
    return "weak"


def design_load(req: Requirements, rules: dict[str, Any]) -> tuple[float, str] | None:
    """The load the strength check uses, and how it was arrived at; None if it does not apply."""
    load_rules = rules.get("load", {})
    load_type = req.load.type
    if load_type is None or load_type.value not in load_rules.get("applies_to", []):
        return None
    if req.load.magnitude_n:
        newtons = float(req.load.magnitude_n)
        source = f"the {newtons:.0f} N you gave"
    else:
        qualitative = req.load.qualitative or "moderate"
        newtons = float(load_rules.get("assumed_load_n", {}).get(qualitative, 50.0))
        source = f"an assumed {newtons:.0f} N for a {qualitative} load"
    factor = float(load_rules.get("dynamic_factor", {}).get(load_type.value, 1.0))
    if factor != 1.0:
        source += f", times {factor:g} for {load_type.value} loading"
    return newtons * factor, source


# --------------------------------------------------------------------------------------
# Orientation
# --------------------------------------------------------------------------------------


def _cosmetic_mask(mesh: trimesh.Trimesh, face: str | None) -> np.ndarray:
    """Triangles belonging to the face the customer said must look good."""
    if face is None:
        return np.zeros(len(mesh.faces), dtype=bool)
    # Within 45 degrees of the named direction: the face itself and its gentler chamfers.
    return mesh.face_normals @ np.array(FACE_DIRECTIONS[face]) > math.cos(math.radians(45))


def _candidate(
    mesh: trimesh.Trimesh,
    face: str,
    rules: dict[str, Any],
    cosmetic: np.ndarray,
    extruded_mm3: float,
    layer_height: float,
) -> tuple[OrientationCandidate, float]:
    rotation = face_down_transform(face)[:3, :3]
    normals = mesh.face_normals @ rotation.T
    centres_z = (mesh.triangles_center @ rotation.T)[:, 2]
    heights = (mesh.vertices @ rotation.T)[:, 2]
    z_min = float(heights.min())
    areas = mesh.area_faces

    overhanging, on_bed = overhang_mask(normals, centres_z, z_min, rules)
    projected = areas * np.clip(-normals[:, 2], 0.0, None)
    density = float(rules.get("orientation", {}).get("support_density", 0.12))
    support = float((projected * (centres_z - z_min))[overhanging].sum() * density)
    # Only faces genuinely flat on the plate. A faceted cylinder's near-flat facets would
    # otherwise count as contact, when a round part really rests on a line and rolls.
    flat_down = normals[:, 2] < -0.999
    height = float(heights.max() - z_min)

    layers = max(1, math.ceil(height / layer_height))
    seconds = layers * LAYER_OVERHEAD_S + (extruded_mm3 + support) / EFFECTIVE_FLOW_MM3_S
    candidate = OrientationCandidate(
        face_down=face,
        support_mm3=round(support, 1),
        support_fraction=round(float(areas[overhanging].sum() / max(areas.sum(), 1e-9)), 4),
        bed_contact_mm2=round(float(areas[on_bed & flat_down].sum()), 1),
        height_mm=round(height, 2),
        time_index=0.0,
        cosmetic_support_mm2=round(float(areas[overhanging & cosmetic].sum()), 1),
        score=0.0,
    )
    return candidate, seconds


def _score(candidates: list[OrientationCandidate], seconds: list[float], rules: dict) -> None:
    weights = rules.get("orientation", {}).get("weights", {})
    fastest = min(seconds)
    for candidate, secs in zip(candidates, seconds, strict=True):
        candidate.time_index = round(secs / fastest, 3) if fastest > 0 else 1.0

    def spread(values: list[float], higher_is_better: bool = False) -> list[float]:
        lo, hi = min(values), max(values)
        if hi - lo < 1e-9:
            return [0.0] * len(values)
        if higher_is_better:
            return [(hi - v) / (hi - lo) for v in values]
        return [(v - lo) / (hi - lo) for v in values]

    terms = {
        "support": spread([c.support_mm3 for c in candidates]),
        "bed_contact": spread([c.bed_contact_mm2 for c in candidates], higher_is_better=True),
        "height": spread([c.height_mm for c in candidates]),
        "time": spread(seconds),
    }
    for i, candidate in enumerate(candidates):
        candidate.score = round(
            sum(float(weights.get(name, 0.0)) * values[i] for name, values in terms.items()), 4
        )


@dataclass
class _Decision:
    chosen: OrientationCandidate
    free_choice: OrientationCandidate  # what the non-strength factors alone would pick
    strength_decided: bool
    cosmetic_decided: bool
    cosmetic_conflict: bool  # the cosmetic face could not be kept clean
    overridden: bool


def _choose(
    candidates: list[OrientationCandidate],
    rules: dict[str, Any],
    cosmetic_face: str | None,
    override: str | None,
) -> _Decision:
    free_choice = min(candidates, key=lambda c: c.score)
    orientation_rules = rules.get("orientation", {})
    tolerance = float(orientation_rules.get("cosmetic_support_tolerance_mm2", 5.0))

    strong = candidates
    factors = [c.safety_factor for c in candidates if c.safety_factor is not None]
    if factors:
        margin = float(rules.get("load", {}).get("strength_margin", 1.25))
        best = max(factors)
        strong = [c for c in candidates if (c.safety_factor or 0.0) >= best / margin]

    pool = strong
    cosmetic_conflict = False
    if cosmetic_face is not None:
        clean = [c for c in strong if c.cosmetic_support_mm2 <= tolerance]
        if clean:
            pool = clean
        else:
            # Either no orientation keeps the face clean, or only weak ones do. Strength wins on
            # a load-bearing part; otherwise mark the face as little as possible.
            cosmetic_conflict = True
            if not factors:
                least = min(c.cosmetic_support_mm2 for c in candidates)
                pool = [c for c in candidates if c.cosmetic_support_mm2 <= least + tolerance]

    # A part that can stand on a flat face should not be balanced on an edge to save a few
    # layers. Strength and the cosmetic face come first; a brim covers what is left.
    min_contact = float(orientation_rules.get("min_bed_contact_mm2", 100.0))
    stable = [c for c in pool if c.bed_contact_mm2 >= min_contact]
    if stable:
        pool = stable

    chosen = min(pool, key=lambda c: c.score)
    overridden = False
    if override is not None:
        chosen = next(c for c in candidates if c.face_down == override)
        overridden = True

    return _Decision(
        chosen=chosen,
        free_choice=free_choice,
        strength_decided=bool(factors) and free_choice not in strong and chosen in strong,
        cosmetic_decided=(
            cosmetic_face is not None
            and not cosmetic_conflict
            and free_choice.cosmetic_support_mm2 > tolerance
        ),
        cosmetic_conflict=cosmetic_conflict,
        overridden=overridden,
    )


def _compare(chosen: OrientationCandidate, other: OrientationCandidate) -> str:
    """Plain-English differences between two orientations, the ones big enough to matter."""
    bits = []
    support_diff = chosen.support_mm3 - other.support_mm3
    if abs(support_diff) >= max(50.0, 0.1 * max(chosen.support_mm3, other.support_mm3)):
        bits.append(
            f"{'more' if support_diff > 0 else 'less'} support "
            f"(about {abs(support_diff) / 1000:.1f} cm3)"
        )
    time_diff = chosen.time_index / other.time_index - 1.0
    if abs(time_diff) >= 0.05:
        bits.append(f"about {abs(time_diff) * 100:.0f}% {'longer' if time_diff > 0 else 'quicker'}")
    height_diff = chosen.height_mm - other.height_mm
    if abs(height_diff) >= 5:
        bits.append(f"{abs(height_diff):.0f} mm {'taller' if height_diff > 0 else 'lower'}")
    contact_diff = chosen.bed_contact_mm2 - other.bed_contact_mm2
    if abs(contact_diff) >= max(50.0, 0.2 * max(chosen.bed_contact_mm2, other.bed_contact_mm2)):
        bits.append(f"{'more' if contact_diff > 0 else 'less'} contact with the bed")
    if not bits:
        return "little difference in support, time or height"
    return ", ".join(bits)


def _orientation_finding(
    decision: _Decision,
    candidates: list[OrientationCandidate],
    rules: dict[str, Any],
    cosmetic_face: str | None,
) -> DesignFinding:
    chosen = decision.chosen
    phrase = FACE_PHRASES[chosen.face_down]
    if decision.overridden:
        reason = "The operator chose this orientation."
    elif decision.strength_decided:
        reason = (
            "This puts the layers along the part's main load path, which matters more on a "
            "load-bearing part than support or print time."
        )
    elif decision.cosmetic_decided:
        reason = f"This keeps support off the {cosmetic_face} face you said must look good."
    else:
        reason = "This needs the least support and print time for the part's shape."

    others = sorted((c for c in candidates if c is not chosen), key=lambda c: c.score)
    runner_up = decision.free_choice if decision.free_choice is not chosen else others[0]
    trade = _compare(chosen, runner_up)
    trade_off = f"Against printing it {FACE_PHRASES[runner_up.face_down]}, this means {trade}."

    severity = Severity.INFO
    fix = "If one face must look better than the others, tell us and we will keep support off it."
    if cosmetic_face is not None:
        fix = "Nothing to change."
    if decision.cosmetic_conflict:
        severity = Severity.ADVISE
        if decision.strength_decided or any(c.safety_factor is not None for c in candidates):
            reason += (
                f" Support will touch the {cosmetic_face} face: every orientation that keeps it "
                "clean would print the part noticeably weaker, and on a load-bearing part "
                "strength comes first."
            )
        else:
            reason += f" No orientation keeps support completely off the {cosmetic_face} face."
        fix = (
            f"Expect light marks on the {cosmetic_face} face where support is removed; they can "
            "be sanded. Chamfering its overhanging edges to 45 degrees would remove the need."
        )
    min_contact = float(rules.get("orientation", {}).get("min_bed_contact_mm2", 100.0))
    if chosen.bed_contact_mm2 < min_contact:
        severity = max(severity, Severity.ADVISE, key=_severity_rank)
        fix = (
            f"Only {chosen.bed_contact_mm2:.0f} mm2 touches the bed this way, so we will add a "
            "brim. A flat face of at least 10 x 10 mm on that side would make it more reliable."
        )

    return DesignFinding(
        check="orientation",
        severity=severity,
        message=f"We will print it {phrase}. {reason}",
        measured=chosen.support_mm3,
        unit="mm3 of support",
        location=FindingLocation(
            description=f"The {chosen.face_down} face goes on the bed",
        ),
        why=(
            "Which way up a part prints decides how much support it needs, how long it takes, "
            "which faces carry support marks, and which way its layer lines run. " + trade_off
        ),
        fix=fix,
    )


def _severity_rank(severity: Severity) -> int:
    return {Severity.INFO: 0, Severity.ADVISE: 1, Severity.MUST_FIX: 2}[severity]


# --------------------------------------------------------------------------------------
# Load across the layers
# --------------------------------------------------------------------------------------


def _better_material(
    material: Material, safety_factor: float, rules: dict[str, Any], excluded: set[str]
) -> tuple[Material, str] | None:
    """A stocked FDM material whose interlayer strength would lift the part into a better band."""
    current = band(safety_factor, rules)
    own = material.tensile_mpa * material.z_strength_ratio
    best: tuple[Material, str, float] | None = None
    for other in load_materials():
        if other.id in excluded or other.id == material.id or not other.in_stock:
            continue
        if other.is_resin:
            continue
        factor = safety_factor * (other.tensile_mpa * other.z_strength_ratio) / own
        other_band = band(factor, rules)
        if _band_rank(other_band) > _band_rank(current) and (best is None or factor > best[2]):
            best = (other, other_band, factor)
    return (best[0], best[1]) if best else None


def _band_rank(name: str) -> int:
    return {"weak": 0, "marginal": 1, "adequate": 2}[name]


def _load_finding(
    material: Material,
    rules: dict[str, Any],
    req: Requirements,
    load: tuple[float, str],
    strengths: dict[int, AxisStrength],
    decision: _Decision,
    excluded: set[str],
) -> DesignFinding | None:
    chosen_face = decision.chosen.face_down
    weakest = strengths.get(FACE_AXIS[chosen_face])
    if weakest is None:
        return None
    newtons, source = load
    result = band(weakest.safety_factor, rules)
    load_type = req.load.type.value if req.load.type else "load"

    # Height of the weak section above the bed, as printed.
    downward = FACE_DIRECTIONS[chosen_face][weakest.axis]
    z = weakest.position_mm if downward < 0 else weakest.extent_mm - weakest.position_mm

    context = ""
    if decision.strength_decided:
        free = decision.free_choice.face_down
        free_strength = strengths.get(FACE_AXIS[free])
        free_band = band(free_strength.safety_factor, rules) if free_strength else "weaker"
        if free_band == result:
            context = (
                f" Strength decided the orientation: printed {FACE_PHRASES[free]}, it would "
                f"need less support or time and still be {free_band}, but with far less margin, "
                "because the layers would cross the load path."
            )
        else:
            context = (
                f" Strength decided the orientation: printed {FACE_PHRASES[free]}, it would "
                f"need less support or time, but the layers would cross the load path and it "
                f"would be {free_band}."
            )
    elif chosen_face != "bottom" and FACE_AXIS["bottom"] in strengths and not decision.overridden:
        modelled_band = band(strengths[FACE_AXIS["bottom"]].safety_factor, rules)
        if _band_rank(modelled_band) < _band_rank(result):
            context = (
                " Printed as modelled, the layers would cross the load path and it would be "
                f"{modelled_band}."
            )
    elif decision.overridden and strengths:
        best_axis = max(strengths.values(), key=lambda s: s.safety_factor)
        if _band_rank(band(best_axis.safety_factor, rules)) > _band_rank(result):
            context += (
                " The orientation was set by the operator; laying the part with its "
                f"{AXIS_NAMES[best_axis.axis]} axis upright would be stronger."
            )

    ratio_pct = round(material.z_strength_ratio * 100)
    if result == "adequate":
        message = (
            f"Strength across the layer lines is adequate for the {load_type} load, in "
            f"{material.name} printed this way.{context}"
        )
        fix = "Nothing to change."
    else:
        message = (
            f"Strength across the layer lines is {result} for the {load_type} load: printed "
            f"this way, the load bends the layer bonds near {z:.0f} mm above the bed.{context}"
        )
        fixes = [
            "thicken the section there or add a fillet or gusset where it joins the rest of "
            "the part",
            "split the part so the loaded arm can print lying flat",
        ]
        alternative = _better_material(material, weakest.safety_factor, rules, excluded)
        if alternative:
            other, other_band = alternative
            fixes.append(
                f"print it in {other.name}, which bonds between layers better and would be "
                f"{other_band}"
            )
        fix = "Either " + "; or ".join(fixes) + "."

    return DesignFinding(
        check="load_vs_layers",
        severity=BAND_SEVERITY[result],
        message=message,
        band=result,  # type: ignore[arg-type]
        location=FindingLocation(
            description=(
                f"The weakest layer interface, {z:.0f} mm above the bed as printed "
                f"({AXIS_NAMES[weakest.axis]} = {weakest.bbox_min[weakest.axis]:.0f} mm in "
                "your model)"
            ),
            z_mm=round(z, 1),
            bbox_min=weakest.bbox_min,
            bbox_max=weakest.bbox_max,
        ),
        why=(
            f"Printed parts are weakest where one layer bonds to the next: {material.name} "
            f"reaches only about {ratio_pct}% of its in-plane strength across the layers. We do "
            "not know which way your load pushes, so we assume it acts sideways at the far end "
            "of the part, as on a bracket, and check where that bends the layer bonds hardest. "
            "If your part is loaded differently, tell us and we will look again."
        ),
        fix=fix,
        operator_note=(
            f"Interlayer bending SF {weakest.safety_factor:.2f} ({result}): "
            f"{weakest.stress_mpa:.1f} MPa against {weakest.strength_mpa:.1f} MPa "
            f"(tensile {material.tensile_mpa:g} x z ratio {material.z_strength_ratio:g}). "
            f"Load {newtons:.0f} N from {source}; lever {weakest.lever_mm:.0f} mm; section "
            f"modulus {weakest.modulus_mm3:.0f} mm3. By build axis: "
            + ", ".join(
                f"{AXIS_NAMES[a]} {s.safety_factor:.2f}" for a, s in sorted(strengths.items())
            )
            + ". z_strength_ratio is provisional."
        ),
    )


def _unverifiable_load_finding(req: Requirements) -> DesignFinding:
    load_type = req.load.type.value if req.load.type else "load"
    return DesignFinding(
        check="load_vs_layers",
        severity=Severity.ADVISE,
        message=(
            f"We could not check strength across the layer lines for the {load_type} load, "
            "because the mesh has open surfaces. We will check it by hand."
        ),
        why=(
            "Printed parts are weakest where one layer bonds to the next, so which way up a "
            "loaded part prints matters. Measuring that needs the part's true cross-sections, "
            "and a mesh with holes in its surface does not have any."
        ),
        fix="Re-export the model from CAD as closed solid bodies and quote it again.",
        operator_note="Strength check skipped: a body in the mesh is open. Check by eye.",
    )


# --------------------------------------------------------------------------------------
# Holes
# --------------------------------------------------------------------------------------


@dataclass
class Hole:
    axis: int  # in the print frame: 2 is vertical
    diameter_mm: float
    centre: np.ndarray  # print frame
    # Extent along the hole's own axis, over the sections it was seen in.
    span: tuple[float, float] = (0.0, 0.0)

    def middle(self) -> np.ndarray:
        centre = self.centre.copy()
        centre[self.axis] = sum(self.span) / 2
        return centre


def find_holes(mesh: trimesh.Trimesh, rules: dict[str, Any]) -> list[Hole]:
    """Round holes, found as near-circular inner rings in cross-sections along each axis."""
    hole_rules = rules.get("holes", {})
    min_circ = float(hole_rules.get("min_circularity", 0.95))
    d_min = float(hole_rules.get("min_diameter_mm", 1.0))
    d_max = float(hole_rules.get("max_diameter_mm", 30.0))
    count = int(hole_rules.get("sections_per_axis", 9))

    holes: list[Hole] = []
    for axis in range(3):
        extent = float(mesh.extents[axis])
        if extent <= 0:
            continue
        normal = np.zeros(3)
        normal[axis] = 1.0
        offsets = np.linspace(0.1, 0.9, count) * extent
        try:
            sections = mesh.section_multiplane(
                plane_origin=np.array(mesh.bounds[0], dtype=float),
                plane_normal=normal,
                heights=offsets,
            )
        except Exception:
            continue
        for section in sections:
            if section is None:
                continue
            to_3d = section.metadata.get("to_3D", np.eye(4))
            for polygon in section.polygons_full:
                for ring in polygon.interiors:
                    inner = Polygon(ring)
                    if inner.length <= 0:
                        continue
                    circularity = 4 * math.pi * inner.area / inner.length**2
                    diameter = 2 * math.sqrt(inner.area / math.pi)
                    if circularity < min_circ or not d_min <= diameter <= d_max:
                        continue
                    c = inner.centroid
                    centre = trimesh.transform_points(np.array([[c.x, c.y, 0.0]]), to_3d)[0]
                    _merge_hole(
                        holes,
                        Hole(
                            axis=axis,
                            diameter_mm=diameter,
                            centre=centre,
                            span=(float(centre[axis]), float(centre[axis])),
                        ),
                    )
    return holes


def _merge_hole(holes: list[Hole], new: Hole) -> None:
    """The same hole turns up in several parallel sections; count it once."""
    for hole in holes:
        if hole.axis != new.axis or abs(hole.diameter_mm - new.diameter_mm) > 0.3:
            continue
        offset = hole.centre - new.centre
        offset[new.axis] = 0.0
        if np.linalg.norm(offset) < 1.0:
            along = float(new.centre[new.axis])
            hole.span = (min(hole.span[0], along), max(hole.span[1], along))
            return
    holes.append(new)


def _hole_findings(
    holes: list[Hole],
    rotation: np.ndarray,
    material: Material,
    rules: dict[str, Any],
    req: Requirements,
) -> list[DesignFinding]:
    hole_rules = rules.get("holes", {})
    small = float(hole_rules.get("vertical_undersize_below_mm", 5.0))
    allowance = float(hole_rules.get("oversize_allowance_mm", 0.2))
    bridge = float(hole_rules.get("horizontal_bridge_mm", 8.0))
    fit_matters = bool(req.precision.fit_critical) or req.precision.tolerance_class in (
        "tight",
        "press_fit",
    )

    # Group by kind and size, so a plate of twenty M3 holes is one finding, not twenty.
    groups: dict[tuple[str, float], list[Hole]] = {}
    for hole in holes:
        vertical = hole.axis == 2
        if vertical and hole.diameter_mm >= small:
            continue
        key = ("vertical" if vertical else "horizontal", round(hole.diameter_mm * 5) / 5)
        groups.setdefault(key, []).append(hole)

    found = []
    for (kind, diameter), members in sorted(groups.items()):
        # Back into the coordinates the customer modelled in (the rotation is pure).
        centres = np.array([rotation.T @ h.middle() for h in members])
        model_axis = int(np.argmax(np.abs(rotation.T @ np.eye(3)[members[0].axis])))
        radius = diameter / 2
        count = len(members)
        noun = f"{count} hole{'s' if count > 1 else ''}"
        verb = "print" if count > 1 else "prints"
        they = "their" if count > 1 else "its"
        where = FindingLocation(
            description=(
                f"{noun} of {diameter:.1f} mm, running along your model's "
                f"{AXIS_NAMES[model_axis]} axis, centred at "
                + "; ".join("(" + ", ".join(f"{v:.0f}" for v in c) + ")" for c in centres[:4])
                + (" and others" if count > 4 else "")
            ),
            bbox_min=tuple(float(v) for v in centres.min(axis=0) - radius),
            bbox_max=tuple(float(v) for v in centres.max(axis=0) + radius),
        )
        ream = " Since you said it has to fit, we would ream it." if fit_matters else ""
        if kind == "vertical":
            found.append(
                DesignFinding(
                    check="holes",
                    severity=Severity.ADVISE,
                    message=(
                        f"{noun.capitalize()} of {diameter:.1f} mm {verb} upright and will come "
                        "out undersize."
                    ),
                    measured=round(diameter, 2),
                    threshold=small,
                    unit="mm diameter",
                    location=where,
                    why=(
                        "A printed hole is a polygon of plastic lines laid inside the circle, "
                        "and the plastic squashes inward, so small upright holes print tight - "
                        "typically 0.1-0.3 mm undersize. A pin or bolt that should slide in "
                        f"won't.{ream}"
                    ),
                    fix=(
                        f"Model it at {diameter + allowance:.2f} mm (+{allowance:g} mm for "
                        f"{material.name}), or leave it and drill or ream to {diameter:.1f} mm "
                        "after printing."
                    ),
                )
            )
        else:
            droop = (
                " At this size the top also has to bridge, so it needs support inside the hole "
                "or a teardrop shape."
                if diameter > bridge
                else ""
            )
            found.append(
                DesignFinding(
                    check="holes",
                    severity=Severity.ADVISE,
                    message=(
                        f"{noun.capitalize()} of {diameter:.1f} mm {verb} on {they} side and will "
                        "come out slightly oval."
                    ),
                    measured=round(diameter, 2),
                    threshold=bridge,
                    unit="mm diameter",
                    location=where,
                    why=(
                        "A hole printed on its side is built up in layers, so its curve is "
                        "stepped and its top sags slightly as each layer spans the gap. It "
                        f"ends up a little oval and short at the top.{droop}{ream}"
                    ),
                    fix=(
                        "Give the hole a teardrop top (a 45 degree point) so it prints "
                        f"without sagging, or model it about {allowance:g} mm oversize and "
                        f"ream to {diameter:.1f} mm after printing."
                    ),
                )
            )
    return found


# --------------------------------------------------------------------------------------
# The review
# --------------------------------------------------------------------------------------


def review(
    mesh: trimesh.Trimesh,
    report: GeometryReport,
    material: Material,
    req: Requirements,
    settings: dict[str, Any],
    *,
    excluded_materials: set[str] | None = None,
    orientation_override: str | None = None,
) -> DesignReview:
    """Choose the orientation and produce the full set of findings for this material and load."""
    rules = design_rules(material)
    cosmetic_face = req.aesthetics.cosmetic_face
    layer_height = float(settings.get("layer_height_mm", 0.2))
    extruded = extruded_volume_mm3(report, settings)

    load = design_load(req, rules)
    strengths: dict[int, AxisStrength] = {}
    bodies = solid_bodies(mesh) if load is not None else None
    unverifiable = load is not None and bodies is None
    if load is not None and bodies is not None and not material.is_resin:
        for axis in range(3):
            result = axis_strength(bodies, axis, material, load[0], rules)
            if result is not None:
                strengths[axis] = result

    cosmetic = _cosmetic_mask(mesh, cosmetic_face)
    candidates: list[OrientationCandidate] = []
    seconds: list[float] = []
    for face in FACE_DIRECTIONS:
        candidate, secs = _candidate(mesh, face, rules, cosmetic, extruded, layer_height)
        axis = strengths.get(FACE_AXIS[face])
        candidate.safety_factor = round(float(axis.safety_factor), 3) if axis else None
        candidates.append(candidate)
        seconds.append(secs)
    _score(candidates, seconds, rules)

    decision = _choose(candidates, rules, cosmetic_face, orientation_override)
    face = decision.chosen.face_down
    oriented = orient_mesh(mesh, face)
    print_geometry = analyse_mesh(oriented, rules)

    found: list[DesignFinding] = [f for f in report.findings if f.check == "mesh_integrity"]
    found += checks.base_findings(
        bbox=report.bbox_mm,
        build=largest_build_volume(),
        fits=report.fits_build_volume,
        min_wall_mm=report.min_wall_mm,
        overhang_fraction=print_geometry.overhang_fraction,
        aspect=print_geometry.height_to_footprint_ratio,
        height=print_geometry.bbox_mm[2],
        triangles=report.triangle_count,
        rules=rules,
        oriented=True,
    )
    found.append(_orientation_finding(decision, candidates, rules, cosmetic_face))
    if unverifiable:
        found.append(_unverifiable_load_finding(req))
    elif load is not None:
        finding = _load_finding(
            material, rules, req, load, strengths, decision, excluded_materials or set()
        )
        if finding is not None:
            found.append(finding)
    rotation = face_down_transform(face)[:3, :3]
    found += _hole_findings(find_holes(oriented, rules), rotation, material, rules, req)

    customer = report.model_copy(deep=True)
    customer.set_findings(found)
    customer.orientation = OrientationChoice(
        face_down=face,
        reason=_orientation_reason(found),
        overridden_by_operator=decision.overridden,
        candidates=candidates,
    )
    print_geometry.set_findings(found)
    return DesignReview(geometry=customer, print_geometry=print_geometry, face_down=face)


def _orientation_reason(found: list[DesignFinding]) -> str:
    return next(f.message for f in found if f.check == "orientation")
