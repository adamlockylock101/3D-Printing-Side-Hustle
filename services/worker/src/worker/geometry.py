"""Mesh analysis.

Everything here runs before a quote exists, so it has to be fast and it has to fail softly:
a mesh we cannot fully analyse still gets a quote, with findings attached. The checks that turn
these measurements into findings live in findings.py; the quote-time design review, which knows
the material and the load, lives in design.py.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
import trimesh

from . import findings as checks
from .config import shop_config
from .materials import design_rules
from .schemas import DesignFinding, FindingLocation, GeometryReport, Severity

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".stl", ".3mf", ".obj", ".ply", ".off"}

# Cap the ray sampling so a two-million-triangle mesh does not stall the quote.
MAX_THICKNESS_SAMPLES = 250


class UnsupportedMesh(ValueError):
    pass


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedMesh(
            f"{path.suffix} is not a supported mesh format. "
            f"Send one of: {', '.join(sorted(SUPPORTED_SUFFIXES))}."
        )
    loaded = trimesh.load(path, force="mesh")
    if isinstance(loaded, trimesh.Scene):
        loaded = trimesh.util.concatenate(tuple(loaded.geometry.values()))
    if not isinstance(loaded, trimesh.Trimesh) or loaded.faces.shape[0] == 0:
        raise UnsupportedMesh("The file contains no printable geometry.")
    return loaded


def _hull_area_2d(points: np.ndarray) -> float:
    """Area of the convex hull of an XY point cloud (monotone chain, no scipy dependency)."""
    pts = np.unique(np.round(points, 4), axis=0)
    if len(pts) < 3:
        return 0.0
    order = np.lexsort((pts[:, 1], pts[:, 0]))
    pts = pts[order]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[np.ndarray] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[np.ndarray] = []
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    hull = np.array(lower[:-1] + upper[:-1])
    if len(hull) < 3:
        return 0.0
    x, y = hull[:, 0], hull[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def overhang_mask(
    normals: np.ndarray, centres_z: np.ndarray, z_min: float, rules: dict
) -> tuple[np.ndarray, np.ndarray]:
    """Faces that need support, and faces sitting on the plate, for a mesh as it will print.

    A face needs support when its angle from vertical exceeds the overhang angle. The bottom
    face sits on the plate rather than in mid-air, so it is excluded.
    """
    limit = -math.sin(math.radians(float(rules.get("overhang_angle_deg", 45))))
    on_bed = (centres_z - z_min) < float(rules.get("bed_tolerance_mm", 0.6))
    return (normals[:, 2] < limit) & ~on_bed, on_bed


def _overhang_fraction(mesh: trimesh.Trimesh, rules: dict) -> float:
    """Area-weighted fraction of the surface that needs support."""
    areas = mesh.area_faces
    total = float(areas.sum())
    if total <= 0:
        return 0.0
    overhanging, _ = overhang_mask(
        mesh.face_normals, mesh.triangles_center[:, 2], float(mesh.bounds[0][2]), rules
    )
    return float(areas[overhanging].sum() / total)


def _min_wall_mm(mesh: trimesh.Trimesh) -> float | None:
    """Estimate the thinnest wall by casting rays inward from sampled surface points.

    Approximate by construction — it samples rather than solving for the true minimum — so it
    drives a warning, never a rejection. See docs/PLAN.md section 12.
    """
    try:
        n_samples = min(MAX_THICKNESS_SAMPLES, max(60, mesh.faces.shape[0] // 20))
        points, face_ids = trimesh.sample.sample_surface(mesh, n_samples)
        normals = mesh.face_normals[face_ids]
        # Start just inside the surface so the ray does not immediately re-hit its own face.
        origins = points - normals * 1e-3
        hits, ray_ids, _ = mesh.ray.intersects_location(
            ray_origins=origins, ray_directions=-normals, multiple_hits=False
        )
        if len(hits) == 0:
            return None
        distances = np.linalg.norm(hits - origins[ray_ids], axis=1)
        distances = distances[distances > 1e-3]
        if distances.size == 0:
            return None
        # The 2nd percentile rather than the raw minimum: a single degenerate triangle should
        # not condemn an otherwise healthy part.
        return float(np.percentile(distances, 2))
    except Exception:
        return None


def largest_build_volume() -> tuple[float, float, float]:
    printers = [p for p in shop_config().get("printers", []) if p.get("kind") != "resin"]
    volumes = [tuple(p.get("build_volume_mm", [0, 0, 0])) for p in printers] or [(0.0, 0.0, 0.0)]
    largest = max(volumes, key=lambda v: v[0] * v[1] * v[2])
    return (float(largest[0]), float(largest[1]), float(largest[2]))


def _integrity(message: str, why: str, fix: str, severity: Severity) -> DesignFinding:
    return DesignFinding(
        check="mesh_integrity",
        severity=severity,
        message=message,
        location=FindingLocation(description="The mesh as a whole"),
        why=why,
        fix=fix,
    )


_REPAIR_FIX = (
    "Re-export from CAD as a single solid body, or run it through your slicer's repair "
    "function first."
)


def _fallback_volume(
    mesh: trimesh.Trimesh, raw_volume: float, found: list[DesignFinding]
) -> float:
    """Best available volume for a mesh that is not watertight.

    The signed volume trimesh computes is usually still correct for the common breakages —
    overlapping solids, duplicate faces, a few flipped normals — so prefer it whenever it is
    physically possible, meaning positive and no larger than the convex hull. Only fall back to
    the hull when the raw figure is impossible, because the hull can over-state a concave part
    several times over: an L-bracket's hull is more than three times the bracket.
    """
    hull: float | None = None
    try:
        hull = float(abs(mesh.convex_hull.volume)) or None
    except Exception:
        log.warning("Convex hull failed; relying on the raw mesh volume", exc_info=True)

    if raw_volume > 0 and (hull is None or raw_volume <= hull * 1.01):
        found.append(
            _integrity(
                "We could not fully verify this mesh, so the material estimate is approximate. "
                "We confirm it against a real slice before printing.",
                "The material in the quote comes from the mesh's volume.",
                _REPAIR_FIX,
                Severity.INFO,
            )
        )
        return raw_volume

    if hull is not None:
        found.append(
            _integrity(
                "This mesh is broken enough that we cannot measure its enclosed volume, so we "
                "have used an upper bound. The quoted material is likely to be more than the "
                "part needs, and we will correct it by hand before charging you.",
                "The material in the quote comes from the mesh's volume.",
                _REPAIR_FIX,
                Severity.ADVISE,
            )
        )
        return hull

    found.append(
        _integrity(
            "We could not measure this part's volume at all. The mesh is likely badly broken, "
            "so we will price it by hand rather than guess.",
            "Without a volume there is nothing to price the material from.",
            _REPAIR_FIX,
            Severity.MUST_FIX,
        )
    )
    return 0.0


def analyse(path: str | Path) -> GeometryReport:
    return analyse_mesh(load_mesh(path))


def analyse_mesh(mesh: trimesh.Trimesh, rules: dict | None = None) -> GeometryReport:
    """Measure the mesh as it sits, and run the light checks with `rules` (default: FDM)."""
    rules = rules if rules is not None else design_rules()
    extents = mesh.extents
    bbox = (float(extents[0]), float(extents[1]), float(extents[2]))
    found: list[DesignFinding] = []

    volume = float(abs(mesh.volume))
    area = float(mesh.area)
    watertight = bool(mesh.is_watertight)
    if not watertight:
        found.append(
            _integrity(
                "The mesh is not watertight (it has holes or flipped faces). We will attempt an "
                "automatic repair, but the printed result may differ from your model.",
                "The slicer has to guess what is inside and outside where the surface is open.",
                _REPAIR_FIX,
                Severity.ADVISE,
            )
        )
        # An open mesh has no reliable enclosed volume. Prefer the convex hull, which is an
        # upper bound and so errs towards over-quoting rather than under-quoting. Fall back to
        # the raw signed volume if the hull cannot be computed, and only report zero when
        # nothing worked — a zero here must never reach a price, so pricing treats it as a
        # manual-review trigger rather than a cheap part.
        volume = _fallback_volume(mesh, volume, found)

    footprint = _hull_area_2d(mesh.vertices[:, :2])
    height = bbox[2]
    ratio = height / math.sqrt(footprint) if footprint > 1 else 0.0

    build = largest_build_volume()
    sorted_part = sorted(bbox, reverse=True)
    sorted_build = sorted(build, reverse=True)
    fits = all(p <= b for p, b in zip(sorted_part, sorted_build, strict=True))

    min_wall = _min_wall_mm(mesh)
    overhang = _overhang_fraction(mesh, rules)

    found.extend(
        checks.base_findings(
            bbox=bbox,
            build=build,
            fits=fits,
            min_wall_mm=min_wall,
            overhang_fraction=overhang,
            aspect=ratio,
            height=height,
            triangles=int(mesh.faces.shape[0]),
            rules=rules,
        )
    )

    report = GeometryReport(
        bbox_mm=bbox,
        volume_mm3=volume,
        surface_area_mm2=area,
        triangle_count=int(mesh.faces.shape[0]),
        is_watertight=watertight,
        min_wall_mm=min_wall,
        overhang_fraction=overhang,
        footprint_mm2=footprint,
        height_to_footprint_ratio=ratio,
        fits_build_volume=fits,
        # STL carries no units, so a model authored in inches arrives 25.4x too small. This is
        # the single most common upload error, and it is cheap to catch.
        units_suspect=any(f.check == "units" for f in found),
    )
    report.set_findings(found)
    return report

