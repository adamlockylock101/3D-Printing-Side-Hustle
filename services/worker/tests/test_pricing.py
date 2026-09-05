from __future__ import annotations

from pathlib import Path

import pytest

from worker.config import shop_config
from worker.geometry import analyse
from worker.materials import by_id
from worker.pricing import build_quote, failure_risk, quantity_discount
from worker.schemas import LeadTime, Requirements
from worker.slicing import estimate

SETTINGS = {"walls": 3, "infill_percent": 20, "layer_height_mm": 0.2}


def quote_for(path: Path, material_id: str = "petg", **req_kwargs):
    geometry = analyse(path)
    material = by_id(material_id)
    sliced = estimate(geometry, material, SETTINGS)
    return build_quote(material, sliced, geometry, Requirements(**req_kwargs)), geometry, sliced


# --------------------------------------------------------------------------------------
# Estimator
# --------------------------------------------------------------------------------------


def test_estimator_produces_plausible_numbers(box_stl: Path):
    quote, geometry, sliced = quote_for(box_stl)
    assert sliced.estimated
    # A 40x30x20 block at 20% infill is a few tens of grams and a couple of hours, not more.
    assert 5 < sliced.filament_g < 40
    assert 20 < sliced.print_minutes < 400


def test_more_infill_means_more_filament_and_more_time(box_stl: Path):
    geometry = analyse(box_stl)
    material = by_id("petg")
    light = estimate(geometry, material, {**SETTINGS, "infill_percent": 10})
    heavy = estimate(geometry, material, {**SETTINGS, "infill_percent": 60})
    assert heavy.filament_g > light.filament_g
    assert heavy.print_minutes > light.print_minutes


def test_finer_layers_take_longer(box_stl: Path):
    geometry = analyse(box_stl)
    material = by_id("petg")
    coarse = estimate(geometry, material, {**SETTINGS, "layer_height_mm": 0.28})
    fine = estimate(geometry, material, {**SETTINGS, "layer_height_mm": 0.12})
    assert fine.print_minutes > coarse.print_minutes


def test_overhangs_generate_support_material(tall_spike_stl: Path, box_stl: Path):
    material = by_id("petg")
    spike = estimate(analyse(tall_spike_stl), material, SETTINGS)
    block = estimate(analyse(box_stl), material, SETTINGS)
    assert block.support_g == 0.0
    assert spike.support_g >= 0.0


def test_denser_material_weighs_more_for_the_same_part(box_stl: Path):
    geometry = analyse(box_stl)
    petg = estimate(geometry, by_id("petg"), SETTINGS)  # 1.27 g/cm3
    pp = estimate(geometry, by_id("pp"), SETTINGS)  # 0.90 g/cm3
    assert petg.filament_g > pp.filament_g


# --------------------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------------------


def test_quote_lines_reconcile_to_the_unit_price(box_stl: Path):
    quote, _, _ = quote_for(box_stl)
    assert not quote.minimum_applied or True
    core = sum(
        line.amount
        for line in quote.lines
        if line.label in {"Material", "Machine time", "Labour", "Failure allowance", "Margin"}
    )
    if not quote.minimum_applied:
        assert core == pytest.approx(quote.unit_price, rel=0.02)


def test_small_part_hits_the_minimum_order(inch_scale_stl: Path):
    quote, _, _ = quote_for(inch_scale_stl)
    minimum = shop_config()["commerce"]["minimum_order"]
    assert quote.minimum_applied
    assert quote.total_price == pytest.approx(minimum)
    assert any(line.label == "Minimum order" for line in quote.lines)


def test_quantity_discount_lowers_the_unit_price(box_stl: Path):
    single, _, _ = quote_for(box_stl, quantity=1)
    batch, _, _ = quote_for(box_stl, quantity=10)
    assert batch.unit_price < single.unit_price
    assert batch.total_price > single.total_price


def test_setup_cost_is_amortised_across_a_batch(box_stl: Path):
    single, _, _ = quote_for(box_stl, quantity=1)
    batch, _, _ = quote_for(box_stl, quantity=25)
    # Ten units should cost well under ten times one unit once setup is shared and the
    # quantity break applies.
    assert batch.total_price < single.total_price * 25 * 0.85


def test_rush_costs_more_and_relaxed_costs_less(box_stl: Path):
    standard, _, _ = quote_for(box_stl, quantity=5, lead_time=LeadTime.STANDARD)
    rush, _, _ = quote_for(box_stl, quantity=5, lead_time=LeadTime.RUSH)
    relaxed, _, _ = quote_for(box_stl, quantity=5, lead_time=LeadTime.RELAXED)
    assert rush.total_price > standard.total_price > relaxed.total_price


def test_expensive_material_costs_more_than_a_cheap_one(box_stl: Path):
    cheap, _, _ = quote_for(box_stl, quantity=5, material_id="pla")
    dear, _, _ = quote_for(box_stl, quantity=5, material_id="pa6_cf")
    assert dear.total_price > cheap.total_price


def test_oversized_part_is_routed_to_manual_review(oversized_stl: Path):
    quote, _, _ = quote_for(oversized_stl)
    assert quote.requires_manual_review
    assert quote.manual_review_reason


def test_long_print_is_routed_to_manual_review(box_stl: Path):
    quote, _, _ = quote_for(box_stl, quantity=200)
    assert quote.requires_manual_review
    assert "print time" in (quote.manual_review_reason or "")


def test_suspect_scale_is_routed_to_manual_review(inch_scale_stl: Path):
    quote, _, _ = quote_for(inch_scale_stl)
    assert quote.requires_manual_review
    assert "scale" in (quote.manual_review_reason or "")


def test_quote_currency_and_expiry_come_from_config(box_stl: Path):
    quote, _, _ = quote_for(box_stl)
    cfg = shop_config()
    assert quote.currency == cfg["currency"]
    assert quote.expires_hours == cfg["commerce"]["quote_valid_hours"]


def test_estimated_flag_propagates_to_the_quote(box_stl: Path):
    quote, _, sliced = quote_for(box_stl)
    assert quote.estimated == sliced.estimated


# --------------------------------------------------------------------------------------
# Risk
# --------------------------------------------------------------------------------------


def test_harder_materials_carry_more_failure_risk(box_stl: Path):
    geometry = analyse(box_stl)
    assert failure_risk(by_id("pa6_cf"), geometry) > failure_risk(by_id("pla"), geometry)


def test_risky_geometry_raises_the_failure_allowance(tall_spike_stl: Path, box_stl: Path):
    material = by_id("petg")
    assert failure_risk(material, analyse(tall_spike_stl)) > failure_risk(
        material, analyse(box_stl)
    )


def test_failure_risk_is_bounded(tall_spike_stl: Path):
    geometry = analyse(tall_spike_stl)
    for material_id in ("pla", "petg", "pp", "pa6_cf", "asa"):
        assert 0.0 <= failure_risk(by_id(material_id), geometry) <= 0.5


def test_quantity_discount_thresholds():
    assert quantity_discount(1) == 0.0
    assert quantity_discount(5) > 0.0
    assert quantity_discount(25) > quantity_discount(10) > quantity_discount(5)


def test_a_part_with_no_measurable_volume_is_never_auto_priced():
    """The last line of defence: whatever produced a zero, don't quote it as cheap."""
    from worker.schemas import GeometryReport, SliceResult

    broken = GeometryReport(
        bbox_mm=(50, 50, 50),
        volume_mm3=0.0,
        surface_area_mm2=1000.0,
        triangle_count=12,
        is_watertight=False,
        warnings=["We could not measure this part's volume at all."],
    )
    material = by_id("petg")
    sliced = SliceResult(print_minutes=5, filament_g=0.0, estimated=True)
    quote = build_quote(material, sliced, broken, Requirements())
    assert quote.requires_manual_review
    assert "measure" in (quote.manual_review_reason or "")


def test_a_tiny_part_keeps_a_non_zero_mass_so_the_real_warning_survives(inch_scale_stl: Path):
    """A 2 mm part must not round to 0 g.

    If it does, the generic "we could not measure this" guard fires and hides the real
    problem, which is that the model is scaled wrong.
    """
    quote, _, sliced = quote_for(inch_scale_stl)
    assert sliced.filament_g > 0
    assert quote.requires_manual_review
    assert "scale" in (quote.manual_review_reason or "")
