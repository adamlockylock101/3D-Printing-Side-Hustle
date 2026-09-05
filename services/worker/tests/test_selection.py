"""Tests for the material selection engine.

These assert on the *reasoning*, not on a hard-coded winner where several materials could
legitimately win — a scoring tweak should not turn the suite red unless it changed a decision
that actually matters.
"""

from __future__ import annotations

import pytest

from worker.materials import by_id, load_materials
from worker.schemas import (
    Aesthetics,
    BrittlenessTolerance,
    Chemical,
    CostSensitivity,
    Environment,
    GeometryReport,
    Lifecycle,
    Load,
    LoadDuration,
    LoadType,
    Moisture,
    Precision,
    Requirements,
    Thermal,
)
from worker.selection import (
    SCORING_DIMENSIONS,
    PrinterCapabilities,
    derive_weights,
    select_material,
)

FULL_SHOP = PrinterCapabilities(
    any_enclosed=True,
    any_hardened_nozzle=True,
    has_resin=False,
    max_build_volume_mm=(256, 256, 256),
)
OPEN_FRAME_SHOP = PrinterCapabilities(
    any_enclosed=False,
    any_hardened_nozzle=False,
    has_resin=False,
    max_build_volume_mm=(256, 256, 256),
)


def rejected_ids(rec) -> set[str]:
    return {r.material_id for r in rec.rejected}


# --------------------------------------------------------------------------------------
# Weights
# --------------------------------------------------------------------------------------


def test_weights_normalise_to_one():
    weights = derive_weights(Requirements())
    assert set(weights) == set(SCORING_DIMENSIONS)
    assert pytest.approx(sum(weights.values()), abs=1e-9) == 1.0
    assert all(v >= 0 for v in weights.values())


def test_cost_dominates_for_a_cheap_prototype():
    req = Requirements(lifecycle=Lifecycle.PROTOTYPE, cost_sensitivity=CostSensitivity.HIGH)
    weights = derive_weights(req)
    assert max(weights, key=weights.get) == "cost"


def test_toughness_dominates_for_impact_loading():
    req = Requirements(
        load=Load(type=LoadType.IMPACT),
        brittleness_tolerance=BrittlenessTolerance.MUST_NOT_SHATTER,
    )
    weights = derive_weights(req)
    assert max(weights, key=weights.get) == "toughness"


def test_sustained_load_raises_the_creep_weight():
    baseline = derive_weights(Requirements(load=Load(type=LoadType.TENSION)))
    sustained = derive_weights(
        Requirements(load=Load(type=LoadType.TENSION, duration=LoadDuration.SUSTAINED))
    )
    assert sustained["creep"] > baseline["creep"]


# --------------------------------------------------------------------------------------
# Hard filters
# --------------------------------------------------------------------------------------


def test_prototype_gets_a_cheap_easy_material():
    req = Requirements(
        lifecycle=Lifecycle.PROTOTYPE,
        cost_sensitivity=CostSensitivity.HIGH,
        aesthetics=Aesthetics(visible=False),
    )
    rec = select_material(req, caps=FULL_SHOP)
    assert not rec.declined
    assert rec.primary.material_id in {"pla", "pla_tough", "petg"}
    assert rec.primary.in_stock


def test_outdoor_service_rejects_uv_sensitive_materials():
    req = Requirements(
        lifecycle=Lifecycle.END_USE,
        environment=Environment(outdoor_uv=True),
        load=Load(type=LoadType.BENDING, duration=LoadDuration.SUSTAINED),
    )
    rec = select_material(req, caps=FULL_SHOP)
    assert not rec.declined
    # PLA, PETG (fair), ABS, PP and both resins are not UV-stable enough for outdoor end-use.
    for material_id in ("pla", "pla_tough", "petg", "abs", "pp", "resin_standard"):
        assert material_id in rejected_ids(rec), f"{material_id} should be UV-rejected"
    assert by_id(rec.primary.material_id).uv_rank >= 2


def test_hot_car_temperature_is_inferred_without_a_number():
    req = Requirements(
        lifecycle=Lifecycle.END_USE,
        thermal=Thermal(sunlight_hot_car=True),
    )
    assert req.effective_max_temp_c() == 70.0
    rec = select_material(req, caps=FULL_SHOP)
    assert "pla" in rejected_ids(rec)
    assert "petg" in rejected_ids(rec)
    winner = by_id(rec.primary.material_id)
    assert winner.hdt_045_c * 0.85 >= 70.0


def test_must_not_shatter_rejects_brittle_materials():
    req = Requirements(
        brittleness_tolerance=BrittlenessTolerance.MUST_NOT_SHATTER,
        load=Load(type=LoadType.IMPACT),
    )
    rec = select_material(req, caps=FULL_SHOP)
    for material_id in ("pla", "pa6_cf", "resin_standard"):
        assert material_id in rejected_ids(rec)
    assert by_id(rec.primary.material_id).elongation_pct >= 10


def test_immersion_rejects_hygroscopic_materials():
    req = Requirements(environment=Environment(moisture=Moisture.IMMERSED))
    rec = select_material(req, caps=FULL_SHOP)
    assert "pa6_cf" in rejected_ids(rec)
    assert by_id(rec.primary.material_id).water_absorption_pct <= 1.0


def test_fuel_and_solvent_exposure_rejects_the_susceptible_materials():
    req = Requirements(
        lifecycle=Lifecycle.END_USE,
        environment=Environment(chemicals=[Chemical.FUELS, Chemical.SOLVENTS]),
    )
    rec = select_material(req, caps=FULL_SHOP)
    for material_id in ("pla", "pla_tough", "petg", "asa", "abs", "tpu_95a"):
        assert material_id in rejected_ids(rec)
    # PP and the nylons resist fuels and solvents, so they are the legitimate survivors.
    assert "pp" not in rejected_ids(rec)
    assert not set(by_id(rec.primary.material_id).attacked_by) & {"fuels", "solvents"}


def test_acid_exposure_leaves_polypropylene():
    req = Requirements(
        lifecycle=Lifecycle.END_USE,
        environment=Environment(chemicals=[Chemical.ACIDS, Chemical.SOLVENTS, Chemical.BASES]),
    )
    rec = select_material(req, caps=FULL_SHOP)
    assert rec.primary.material_id == "pp"


def test_sustained_load_rejects_materials_that_creep():
    req = Requirements(
        load=Load(type=LoadType.TENSION, duration=LoadDuration.SUSTAINED),
    )
    rec = select_material(req, caps=FULL_SHOP)
    assert "pla" in rejected_ids(rec)
    reason = next(r.reason for r in rec.rejected if r.material_id == "pla")
    assert "creep" in reason.lower()


def test_food_contact_leaves_only_food_safe_capable_grades():
    req = Requirements(environment=Environment(food_contact=True))
    rec = select_material(req, caps=FULL_SHOP)
    assert not rec.declined
    assert by_id(rec.primary.material_id).food_safe_capable
    assert any("food" in w.lower() for w in rec.warnings)


def test_open_frame_shop_cannot_offer_enclosure_materials():
    req = Requirements(lifecycle=Lifecycle.END_USE)
    rec = select_material(req, caps=OPEN_FRAME_SHOP)
    for material_id in ("asa", "abs", "pc", "pa6_cf", "pa12", "pp"):
        assert material_id in rejected_ids(rec)
    assert rec.primary.material_id in {"pla", "pla_tough", "petg", "tpu_95a"}


def test_carbon_fibre_needs_a_hardened_nozzle():
    caps = PrinterCapabilities(
        any_enclosed=True,
        any_hardened_nozzle=False,
        has_resin=False,
        max_build_volume_mm=(256, 256, 256),
    )
    rec = select_material(Requirements(), caps=caps)
    reason = next(r.reason for r in rec.rejected if r.material_id == "pa6_cf")
    assert "hardened nozzle" in reason.lower()


# --------------------------------------------------------------------------------------
# Declining
# --------------------------------------------------------------------------------------


def test_tolerance_beyond_fdm_declines_when_there_is_no_resin_printer():
    req = Requirements(precision=Precision(tolerance_mm=0.04, fit_critical=True))
    rec = select_material(req, caps=FULL_SHOP)
    assert rec.declined
    assert "resin" in (rec.declined_reason or "").lower()
    assert rec.primary.material_id == "none"


def test_impossible_combination_declines_with_the_binding_constraints():
    req = Requirements(
        thermal=Thermal(max_service_c=300),
        environment=Environment(outdoor_uv=True, moisture=Moisture.IMMERSED),
    )
    rec = select_material(req, caps=FULL_SHOP)
    assert rec.declined
    assert rec.rejected
    assert rec.declined_reason


# --------------------------------------------------------------------------------------
# Output quality
# --------------------------------------------------------------------------------------


def test_every_rejection_carries_a_readable_reason():
    req = Requirements(
        lifecycle=Lifecycle.END_USE,
        environment=Environment(outdoor_uv=True),
        thermal=Thermal(max_service_c=80),
    )
    rec = select_material(req, caps=FULL_SHOP)
    for rejection in rec.rejected:
        assert rejection.reason.strip()
        assert rejection.name


def test_bending_load_produces_orientation_advice():
    req = Requirements(load=Load(type=LoadType.BENDING, qualitative="heavy"))
    rec = select_material(req, caps=FULL_SHOP)
    assert rec.orientation_advice
    assert "layer" in rec.orientation_advice.lower()


def test_no_load_produces_no_orientation_advice():
    rec = select_material(Requirements(lifecycle=Lifecycle.COSMETIC), caps=FULL_SHOP)
    assert rec.orientation_advice is None


def test_structural_parts_get_more_perimeters_than_prototypes():
    structural = select_material(
        Requirements(load=Load(type=LoadType.BENDING, qualitative="heavy")), caps=FULL_SHOP
    )
    prototype = select_material(Requirements(lifecycle=Lifecycle.PROTOTYPE), caps=FULL_SHOP)
    assert structural.print_settings["walls"] > prototype.print_settings["walls"]


def test_tight_tolerance_reduces_layer_height():
    rec = select_material(
        Requirements(precision=Precision(tolerance_mm=0.15, fit_critical=True)), caps=FULL_SHOP
    )
    assert not rec.declined
    assert rec.print_settings["layer_height_mm"] <= 0.12


def test_tolerance_at_the_floor_is_accepted_but_below_it_is_not():
    at_floor = select_material(Requirements(precision=Precision(tolerance_mm=0.15)), caps=FULL_SHOP)
    below_floor = select_material(
        Requirements(precision=Precision(tolerance_mm=0.10)), caps=FULL_SHOP
    )
    assert not at_floor.declined
    assert below_floor.declined


def test_alternates_are_distinct_and_carry_trade_offs():
    req = Requirements(lifecycle=Lifecycle.END_USE, load=Load(type=LoadType.BENDING))
    rec = select_material(req, caps=FULL_SHOP)
    ids = [a.material_id for a in rec.alternates]
    assert rec.primary.material_id not in ids
    assert len(ids) == len(set(ids))
    assert all(a.trade_off for a in rec.alternates)


def test_rationale_always_carries_the_anisotropy_disclaimer():
    rec = select_material(Requirements(lifecycle=Lifecycle.END_USE), caps=FULL_SHOP)
    assert "anisotropic" in rec.rationale.lower()
    assert rec.table_version


def test_selection_is_deterministic():
    req = Requirements(
        lifecycle=Lifecycle.END_USE,
        load=Load(type=LoadType.IMPACT, qualitative="moderate"),
        environment=Environment(outdoor_uv=True),
        thermal=Thermal(max_service_c=55),
    )
    first = select_material(req, caps=FULL_SHOP)
    second = select_material(req, caps=FULL_SHOP)
    assert first.model_dump() == second.model_dump()


def test_geometry_warnings_are_carried_into_the_recommendation():
    geometry = GeometryReport(
        bbox_mm=(400, 100, 100),
        volume_mm3=100_000,
        surface_area_mm2=50_000,
        triangle_count=1000,
        is_watertight=False,
        fits_build_volume=False,
        warnings=["Mesh is not watertight"],
    )
    rec = select_material(Requirements(), geometry=geometry, caps=FULL_SHOP)
    assert "Mesh is not watertight" in rec.warnings
    assert any("build volume" in w for w in rec.warnings)


def test_unstocked_winner_is_flagged():
    # PC is in the property table but not in config/shop.yaml stocked_materials.
    assert by_id("pc") is not None and not by_id("pc").in_stock
    req = Requirements(thermal=Thermal(max_service_c=105), lifecycle=Lifecycle.END_USE)
    rec = select_material(req, caps=FULL_SHOP)
    if not rec.primary.in_stock:
        assert any("not currently stocked" in w for w in rec.warnings)


def test_material_table_is_internally_consistent():
    for material in load_materials():
        assert 0 < material.z_strength_ratio <= 1
        assert 1 <= material.creep_resistance <= 5
        assert 1 <= material.printability <= 5
        assert material.uv_resistance in {"poor", "fair", "good", "excellent"}
        assert material.warp in {"low", "medium", "high"}
        assert material.cost_per_kg > 0
        assert material.notes, f"{material.id} has no operator-facing note"


def test_single_survivor_explains_why_there_are_no_alternates():
    # Outdoor plus a hot-car service temperature leaves only ASA in the current catalogue.
    req = Requirements(
        lifecycle=Lifecycle.END_USE,
        environment=Environment(outdoor_uv=True),
        thermal=Thermal(sunlight_hot_car=True),
    )
    rec = select_material(req, caps=FULL_SHOP)
    assert not rec.declined
    assert rec.alternates == []
    assert any("only material" in w for w in rec.warnings)
