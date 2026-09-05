"""The material selection engine.

Deterministic and auditable by design: hard filters knock out anything that fails a stated
requirement (recording why), then survivors are scored on weights derived from the
requirements, then adjusted for what can actually be printed here and what is in stock.

The LLM never reaches this module. It only produces the Requirements object that goes in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import shop_config
from .materials import (
    Material,
    load_materials,
    process_capability_mm,
    process_min_feature_mm,
    process_tolerance_floor_mm,
    table_version,
)
from .schemas import (
    BrittlenessTolerance,
    GeometryReport,
    Lifecycle,
    LoadDuration,
    LoadType,
    MaterialScore,
    Moisture,
    Recommendation,
    RejectedMaterial,
    Requirements,
)

# Heat deflection is measured under a defined load in a lab. Real parts see a worse combination
# of sustained stress, thickness and time, so hold service temperature below a fraction of HDT.
HDT_SAFETY_FACTOR = 0.85

# Elongation at break below this is "will shatter rather than bend" territory.
DUCTILE_ELONGATION_MIN = 10.0

# Water absorption above this makes a material unsuitable for continuous immersion.
IMMERSION_ABSORPTION_MAX = 1.0

# Minimum UV rank for outdoor service; matches materials.UV_RANK["good"].
UV_GOOD = 2

SCORING_DIMENSIONS = (
    "strength",
    "toughness",
    "heat",
    "creep",
    "uv",
    "moisture",
    "precision",
    "cost",
    "printability",
)


@dataclass
class PrinterCapabilities:
    """What the shop can physically do, derived from config/shop.yaml."""

    any_enclosed: bool
    any_hardened_nozzle: bool
    has_resin: bool
    max_build_volume_mm: tuple[float, float, float]

    @classmethod
    def from_config(cls) -> PrinterCapabilities:
        printers = shop_config().get("printers", [])
        fdm = [p for p in printers if p.get("kind") != "resin"]
        resin = [p for p in printers if p.get("kind") == "resin"]
        volumes = [tuple(p.get("build_volume_mm", [0, 0, 0])) for p in fdm] or [(0.0, 0.0, 0.0)]
        largest = max(volumes, key=lambda v: v[0] * v[1] * v[2])
        return cls(
            any_enclosed=any(p.get("enclosed") for p in fdm),
            any_hardened_nozzle=any(p.get("hardened_nozzle") for p in fdm),
            has_resin=bool(resin),
            max_build_volume_mm=(float(largest[0]), float(largest[1]), float(largest[2])),
        )


# --------------------------------------------------------------------------------------
# Step 1 — hard filters
# --------------------------------------------------------------------------------------


def _hard_filter(
    material: Material, req: Requirements, caps: PrinterCapabilities
) -> str | None:
    """Return a rejection reason, or None if the material survives."""

    # Process availability first: rejecting on capability is clearer than on properties.
    if material.is_resin and not caps.has_resin:
        return "No resin printer in the shop"
    if material.requires_enclosure and not caps.any_enclosed:
        return "Needs an enclosed printer; none available"
    if material.requires_hardened_nozzle and not caps.any_hardened_nozzle:
        return "Needs a hardened nozzle; none fitted"

    max_temp = req.effective_max_temp_c()
    if max_temp is not None:
        usable = material.hdt_045_c * HDT_SAFETY_FACTOR
        if max_temp > usable:
            return (
                f"Softens too near the service temperature "
                f"(HDT {material.hdt_045_c:.0f} C, usable to ~{usable:.0f} C, needs {max_temp:.0f} C)"
            )

    env = req.environment
    if env.outdoor_uv and material.uv_rank < UV_GOOD:
        return f"UV resistance is {material.uv_resistance}; degrades outdoors"

    if env.moisture == Moisture.IMMERSED and material.water_absorption_pct > IMMERSION_ABSORPTION_MAX:
        return (
            f"Absorbs {material.water_absorption_pct:.1f}% water; swells and weakens when immersed"
        )

    attacked = set(material.attacked_by) & {c.value for c in env.chemicals}
    if attacked:
        return f"Attacked by {', '.join(sorted(attacked))}"

    if env.food_contact and not material.food_safe_capable:
        return "Not available in a food-contact-capable grade"

    if (
        req.brittleness_tolerance == BrittlenessTolerance.MUST_NOT_SHATTER
        and material.elongation_pct < DUCTILE_ELONGATION_MIN
    ):
        return (
            f"Too brittle for a must-not-shatter part "
            f"(elongation {material.elongation_pct:.0f}%, want >={DUCTILE_ELONGATION_MIN:.0f}%)"
        )

    # Reject on the floor, not the nominal capability: a tuned machine can be pushed past its
    # everyday tolerance, and declining every job a shade tighter than nominal loses good work.
    tolerance = req.effective_tolerance_mm()
    if tolerance is not None:
        floor = process_tolerance_floor_mm(material.process)
        if tolerance < floor:
            return (
                f"{material.process.upper()} cannot hold tighter than about +/-{floor:.2f} mm; "
                f"the part needs +/-{tolerance:.2f} mm"
            )

    min_feature = req.precision.min_feature_mm
    if min_feature is not None and min_feature < process_min_feature_mm(material.process):
        return (
            f"Smallest reliable feature on {material.process.upper()} is about "
            f"{process_min_feature_mm(material.process):.1f} mm"
        )

    # Sustained load is what quietly kills PLA in service: it holds fine for a week and sags
    # over a month. Creep resistance of 1 means "do not load this for long".
    if (
        req.load.duration == LoadDuration.SUSTAINED
        and req.load.type not in (None, LoadType.NONE)
        and material.creep_resistance <= 1
    ):
        return "Creeps under sustained load; the part would deform over time"

    return None


# --------------------------------------------------------------------------------------
# Step 2 — weights derived from the requirements
# --------------------------------------------------------------------------------------


def derive_weights(req: Requirements) -> dict[str, float]:
    """Turn requirements into scoring weights. Normalised to sum to 1."""

    w = dict.fromkeys(SCORING_DIMENSIONS, 0.0)

    # Baseline: everyone cares a little about all of it.
    w.update(
        strength=0.10,
        toughness=0.10,
        heat=0.08,
        creep=0.05,
        uv=0.03,
        moisture=0.03,
        precision=0.10,
        cost=0.15,
        printability=0.12,
    )

    lifecycle = req.lifecycle
    if lifecycle in (Lifecycle.PROTOTYPE, Lifecycle.FIT_CHECK):
        w["cost"] += 0.25
        w["printability"] += 0.15
        w["precision"] += 0.05
        w["strength"] -= 0.05
        w["creep"] -= 0.03
    elif lifecycle == Lifecycle.COSMETIC:
        w["cost"] += 0.10
        w["printability"] += 0.15
        w["precision"] += 0.10
        w["strength"] -= 0.05
    elif lifecycle == Lifecycle.END_USE:
        w["strength"] += 0.10
        w["toughness"] += 0.10
        w["creep"] += 0.08
        w["cost"] -= 0.05
    elif lifecycle == Lifecycle.FUNCTIONAL_PROTOTYPE:
        w["strength"] += 0.06
        w["toughness"] += 0.06

    load = req.load
    if load.type in (LoadType.IMPACT, LoadType.CYCLIC):
        w["toughness"] += 0.25
        w["strength"] += 0.05
    elif load.type in (LoadType.TENSION, LoadType.BENDING, LoadType.SHEAR):
        w["strength"] += 0.15
        w["toughness"] += 0.08
    elif load.type == LoadType.CLAMPING:
        w["creep"] += 0.15
        w["strength"] += 0.08

    if load.qualitative == "heavy" or (load.magnitude_n or 0) > 200:
        w["strength"] += 0.10
        w["toughness"] += 0.05
    if load.duration == LoadDuration.SUSTAINED:
        w["creep"] += 0.15

    brittleness = req.brittleness_tolerance
    if brittleness == BrittlenessTolerance.MUST_NOT_SHATTER:
        w["toughness"] += 0.20
    elif brittleness == BrittlenessTolerance.PREFER_DUCTILE:
        w["toughness"] += 0.10
    elif brittleness == BrittlenessTolerance.STIFFNESS_PREFERRED:
        w["strength"] += 0.12
        w["toughness"] -= 0.05

    if req.effective_max_temp_c() is not None:
        w["heat"] += 0.15
    if req.environment.outdoor_uv:
        w["uv"] += 0.15
        w["heat"] += 0.05
    if req.environment.moisture in (Moisture.SPLASH, Moisture.IMMERSED, Moisture.HUMID):
        w["moisture"] += 0.12

    if req.precision.fit_critical:
        w["precision"] += 0.18
    if req.effective_tolerance_mm() is not None and req.effective_tolerance_mm() <= 0.15:
        w["precision"] += 0.10

    cost_sensitivity = req.cost_sensitivity
    if cost_sensitivity and cost_sensitivity.value == "high":
        w["cost"] += 0.20
    elif cost_sensitivity and cost_sensitivity.value == "low":
        w["cost"] -= 0.10

    # Large batches amplify both material cost and the cost of an unreliable print.
    if req.quantity >= 10:
        w["cost"] += 0.08
        w["printability"] += 0.08

    for key in w:
        w[key] = max(w[key], 0.0)
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


# --------------------------------------------------------------------------------------
# Step 3 — scoring
# --------------------------------------------------------------------------------------


def _raw_dimensions(material: Material, req: Requirements) -> dict[str, float]:
    """Per-material raw values, all oriented so that higher is better."""

    max_temp = req.effective_max_temp_c()
    heat_headroom = material.hdt_045_c * HDT_SAFETY_FACTOR - (max_temp or 0.0)

    # Impact is the better toughness proxy where it exists; elongation carries the rest.
    # TPU has no notched impact value because it does not break, so treat it as the maximum.
    impact = material.impact_notched if material.impact_notched is not None else 30.0
    toughness = impact * 0.6 + min(material.elongation_pct, 100.0) * 0.4

    return {
        "strength": material.tensile_mpa,
        "toughness": toughness,
        "heat": heat_headroom,
        "creep": float(material.creep_resistance),
        "uv": float(material.uv_rank),
        "moisture": -material.water_absorption_pct,
        "precision": -float(material.warp_rank) - process_capability_mm(material.process) * 4,
        "cost": -material.cost_per_kg,
        "printability": float(material.printability),
    }


def _normalise(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _stock_and_practicality_factor(material: Material) -> float:
    """Step 3 of the documented algorithm: an ideal material you cannot print is not the answer."""
    factor = 1.0
    if not material.in_stock:
        factor *= 0.75  # orderable, but adds lead time and a minimum spool purchase
    if material.printability <= 2:
        factor *= 0.92
    if material.requires_drying:
        factor *= 0.97
    return factor


# --------------------------------------------------------------------------------------
# Step 4 — narrative output
# --------------------------------------------------------------------------------------

DIMENSION_PHRASES = {
    "strength": "tensile strength",
    "toughness": "toughness and impact resistance",
    "heat": "heat resistance",
    "creep": "resistance to creep under sustained load",
    "uv": "UV stability",
    "moisture": "moisture resistance",
    "precision": "dimensional stability",
    "cost": "material cost",
    "printability": "print reliability",
}


def _orientation_advice(material: Material, req: Requirements) -> str | None:
    """The highest-value thing a materials engineer can tell an FDM customer."""
    if material.is_resin:
        return None
    load_type = req.load.type
    if load_type in (None, LoadType.NONE):
        return None

    ratio_pct = round(material.z_strength_ratio * 100)
    weak = f"{material.name} reaches only about {ratio_pct}% of its in-plane strength across layers"

    if load_type in (LoadType.TENSION, LoadType.BENDING, LoadType.SHEAR):
        return (
            f"{weak}, so the part will be oriented with the layer lines running across your "
            f"{load_type.value} load rather than along it. If the part has an obvious long axis "
            "that carries the load, tell us which way it points."
        )
    if load_type == LoadType.IMPACT:
        return (
            f"{weak}. Impact loads find layer lines first, so we will orient to keep the "
            "expected impact direction out of the weak axis and increase perimeters."
        )
    if load_type == LoadType.CYCLIC:
        return (
            f"{weak}, and cyclic loading fails at layer boundaries long before the bulk material "
            "gives up. Expect a conservative orientation and extra perimeters."
        )
    if load_type == LoadType.CLAMPING:
        return (
            f"{weak}. Bolted or clamped joints crush the layer stack, so we will orient the "
            "clamping force in-plane and recommend a washer or heat-set insert."
        )
    return weak


def _print_settings(material: Material, req: Requirements, geometry: GeometryReport | None) -> dict[str, Any]:
    """Perimeters carry bending load, not infill. Most customers assume the opposite."""
    load = req.load
    heavy = load.qualitative == "heavy" or (load.magnitude_n or 0) > 200
    structural = load.type not in (None, LoadType.NONE)

    walls = 2
    infill = 15
    pattern = "grid"

    if structural:
        walls = 4
        infill = 25
        pattern = "gyroid"
    if heavy or load.type in (LoadType.IMPACT, LoadType.CYCLIC):
        walls = 5
        infill = 40
        pattern = "gyroid"
    if req.lifecycle in (Lifecycle.PROTOTYPE, Lifecycle.FIT_CHECK):
        walls, infill, pattern = 2, 10, "grid"

    layer_height = 0.2
    tolerance = req.effective_tolerance_mm()
    if tolerance is not None and tolerance <= 0.15:
        layer_height = 0.12
    if req.aesthetics.visible and req.aesthetics.finish == "smooth":
        layer_height = min(layer_height, 0.12)
    if geometry is not None and geometry.min_wall_mm is not None and geometry.min_wall_mm < 1.0:
        walls = min(walls, 2)

    return {
        "walls": walls,
        "infill_percent": infill,
        "infill_pattern": pattern,
        "layer_height_mm": layer_height,
        "note": (
            "Perimeters carry bending and tensile load far more effectively than infill, so the "
            "wall count is raised before the infill density."
        ),
    }


def _trade_off(alternate: Material, primary: Material) -> str:
    bits: list[str] = []
    cost_delta = (alternate.cost_per_kg - primary.cost_per_kg) / max(primary.cost_per_kg, 1)
    if cost_delta <= -0.15:
        bits.append(f"about {abs(cost_delta) * 100:.0f}% cheaper")
    elif cost_delta >= 0.15:
        bits.append(f"about {cost_delta * 100:.0f}% dearer")

    heat_delta = alternate.hdt_045_c - primary.hdt_045_c
    if heat_delta >= 15:
        bits.append(f"handles {heat_delta:.0f} C more heat")
    elif heat_delta <= -15:
        bits.append(f"softens {abs(heat_delta):.0f} C sooner")

    if alternate.elongation_pct >= primary.elongation_pct * 1.5:
        bits.append("noticeably tougher")
    elif alternate.elongation_pct <= primary.elongation_pct * 0.6:
        bits.append("more brittle")

    if alternate.printability < primary.printability:
        bits.append("fussier to print")
    if alternate.uv_rank > primary.uv_rank:
        bits.append("better outdoors")

    return "; ".join(bits) if bits else "broadly comparable"


def _build_rationale(
    primary: MaterialScore,
    material: Material,
    req: Requirements,
    weights: dict[str, float],
    rejected: list[RejectedMaterial],
) -> str:
    top = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)[:3]
    priorities = ", ".join(DIMENSION_PHRASES[k] for k, _ in top)

    lines = [
        f"**{material.name}** is recommended. Based on what you told us, the properties that "
        f"mattered most here were {priorities}."
    ]
    if material.notes:
        lines += ["", material.notes]

    facts = []
    max_temp = req.effective_max_temp_c()
    if max_temp is not None:
        facts.append(
            f"Heat deflection {material.hdt_045_c:.0f} C, comfortably above your "
            f"{max_temp:.0f} C service temperature with margin."
        )
    if req.brittleness_tolerance in (
        BrittlenessTolerance.MUST_NOT_SHATTER,
        BrittlenessTolerance.PREFER_DUCTILE,
    ):
        facts.append(
            f"Elongation at break {material.elongation_pct:.0f}%, so it bends and deforms "
            "rather than shattering."
        )
    if req.environment.outdoor_uv:
        facts.append(f"UV resistance rated {material.uv_resistance} for outdoor service.")
    if req.load.duration == LoadDuration.SUSTAINED:
        facts.append(f"Creep resistance {material.creep_resistance}/5 under sustained load.")
    if req.environment.chemicals:
        facts.append(
            "Chemically compatible with "
            f"{', '.join(sorted(c.value for c in req.environment.chemicals))}."
        )
    if facts:
        lines.append("")
        lines.extend(f"- {f}" for f in facts)

    if rejected:
        lines.append("")
        notable = rejected[:3]
        lines.append(
            "Ruled out: "
            + "; ".join(f"{r.name} ({r.reason[0].lower() + r.reason[1:]})" for r in notable)
            + "."
        )

    lines.append("")
    lines.append(
        "_Printed parts are anisotropic and typically reach 40-80% of the datasheet figure "
        "across layer lines. This is engineering guidance for the use you described, not a "
        "certification._"
    )
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def select_material(
    req: Requirements,
    geometry: GeometryReport | None = None,
    caps: PrinterCapabilities | None = None,
) -> Recommendation:
    caps = caps or PrinterCapabilities.from_config()
    materials = load_materials()

    survivors: list[Material] = []
    rejected: list[RejectedMaterial] = []
    for material in materials:
        reason = _hard_filter(material, req, caps)
        if reason:
            rejected.append(
                RejectedMaterial(material_id=material.id, name=material.name, reason=reason)
            )
        else:
            survivors.append(material)

    warnings: list[str] = []
    if geometry is not None:
        warnings.extend(geometry.warnings)

    if not survivors:
        return _declined(req, rejected, warnings, caps)

    weights = derive_weights(req)
    raw = {m.id: _raw_dimensions(m, req) for m in survivors}
    normalised = {
        dim: dict(zip([m.id for m in survivors], _normalise([raw[m.id][dim] for m in survivors])))
        for dim in SCORING_DIMENSIONS
    }

    scored: list[tuple[Material, float, list[str]]] = []
    for material in survivors:
        contributions = {
            dim: weights[dim] * normalised[dim][material.id] for dim in SCORING_DIMENSIONS
        }
        score = sum(contributions.values()) * _stock_and_practicality_factor(material)
        drivers = [
            DIMENSION_PHRASES[dim]
            for dim, _ in sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)[:3]
        ]
        scored.append((material, score, drivers))

    scored.sort(key=lambda item: item[1], reverse=True)
    best_material, best_score, best_drivers = scored[0]

    primary = MaterialScore(
        material_id=best_material.id,
        name=best_material.name,
        score=round(best_score, 4),
        drivers=best_drivers,
        cost_per_kg=best_material.cost_per_kg,
        in_stock=best_material.in_stock,
    )
    alternates = [
        MaterialScore(
            material_id=m.id,
            name=m.name,
            score=round(s, 4),
            drivers=d,
            trade_off=_trade_off(m, best_material),
            cost_per_kg=m.cost_per_kg,
            in_stock=m.in_stock,
        )
        for m, s, d in scored[1:3]
    ]

    if not best_material.in_stock:
        warnings.append(
            f"{best_material.name} is not currently stocked; expect additional lead time while "
            "a spool is ordered."
        )
    if best_material.requires_drying:
        warnings.append(f"{best_material.name} is hygroscopic and will be dried before printing.")
    if req.environment.food_contact:
        warnings.append(
            "Layer lines on any printed part trap residue regardless of the polymer. A "
            "food-safe coating or a food-safe printed-mould-then-cast approach is safer than "
            "direct food contact."
        )
    if geometry is not None and not geometry.fits_build_volume:
        warnings.append(
            "The part exceeds the build volume and will need splitting into sections, or scaling."
        )

    return Recommendation(
        primary=primary,
        alternates=alternates,
        rejected=rejected,
        rationale=_build_rationale(primary, best_material, req, weights, rejected),
        orientation_advice=_orientation_advice(best_material, req),
        print_settings=_print_settings(best_material, req, geometry),
        warnings=warnings,
        table_version=table_version(),
        escalate_to_resin=best_material.is_resin,
    )


def _declined(
    req: Requirements,
    rejected: list[RejectedMaterial],
    warnings: list[str],
    caps: PrinterCapabilities,
) -> Recommendation:
    """No material survives. Say why, specifically, rather than returning an empty list."""
    tolerance = req.effective_tolerance_mm()
    fdm_floor = process_tolerance_floor_mm("fdm")

    if tolerance is not None and tolerance < fdm_floor and not caps.has_resin:
        reason = (
            f"A tolerance of +/-{tolerance:.2f} mm is below what FDM can hold "
            f"(about +/-{fdm_floor:.2f} mm at best), and there is no resin printer in the shop. "
            "This part needs SLA/MSLA or machining."
        )
    else:
        binding = "; ".join(sorted({r.reason for r in rejected}))[:400]
        reason = (
            "No available material satisfies every stated requirement at once. The binding "
            f"constraints were: {binding}."
        )

    placeholder = MaterialScore(
        material_id="none", name="No suitable material", score=0.0, cost_per_kg=0.0, in_stock=False
    )
    return Recommendation(
        primary=placeholder,
        alternates=[],
        rejected=rejected,
        rationale=reason,
        warnings=warnings,
        table_version=table_version(),
        declined=True,
        declined_reason=reason,
    )
