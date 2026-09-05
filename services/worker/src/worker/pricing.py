"""Quote calculation.

    price = material + machine + labour + risk buffer, then margin, then quantity and rush
            adjustments, then the minimum order floor.

Every term ends up in `Quote.lines` so the operator screen and the customer see the same
breakdown. A quote nobody can explain is a quote that gets argued about.
"""

from __future__ import annotations

from .config import shop_config
from .materials import Material
from .schemas import CostLine, GeometryReport, LeadTime, Quote, Requirements, SliceResult


def _round_money(value: float) -> float:
    return round(value + 1e-9, 2)


def failure_risk(material: Material, geometry: GeometryReport) -> float:
    """Probability-of-failure proxy used to size the risk buffer.

    Starts from the material's printability and rises with geometry risk. Replace the constants
    with measured per-material failure rates once enough jobs have been logged — see
    docs/material-selection.md section 6.
    """
    base = {5: 0.02, 4: 0.04, 3: 0.07, 2: 0.12, 1: 0.20}.get(material.printability, 0.08)
    if material.warp_rank == 2:
        base += 0.03
    return min(base + geometry.risk_score() * 0.25, 0.5)


def quantity_discount(quantity: int) -> float:
    breaks = shop_config()["pricing"].get("quantity_breaks", [])
    applicable = [b["discount"] for b in breaks if quantity >= b["min_qty"]]
    return max(applicable) if applicable else 0.0


def build_quote(
    material: Material,
    slice_result: SliceResult,
    geometry: GeometryReport,
    req: Requirements,
) -> Quote:
    cfg = shop_config()
    pricing = cfg["pricing"]
    commerce = cfg["commerce"]
    quantity = max(1, req.quantity)

    # --- per-unit cost build-up -------------------------------------------------------
    total_grams = slice_result.filament_g + slice_result.support_g
    material_cost = total_grams * (1 + pricing["waste_factor"]) * material.cost_per_gram()

    print_hours = slice_result.print_minutes / 60.0
    machine_cost = print_hours * pricing["machine_rate_per_hour"]

    # Setup is per batch, not per part: it is the single biggest reason a batch of ten is not
    # ten times the price of one.
    setup_hours = pricing["setup_minutes"] / 60.0 / quantity
    packing_hours = pricing["packing_minutes"] / 60.0
    post_hours = 0.05 + geometry.overhang_fraction * 0.25  # support removal scales with overhang
    labour_cost = (setup_hours + packing_hours + post_hours) * pricing["labour_rate_per_hour"]

    subtotal = material_cost + machine_cost + labour_cost

    risk = failure_risk(material, geometry)
    risk_amount = min(subtotal * risk, subtotal * pricing["risk_buffer_cap"])

    cost_with_risk = subtotal + risk_amount
    margin_amount = cost_with_risk * pricing["margin"]
    unit_price = cost_with_risk + margin_amount

    # --- adjustments ------------------------------------------------------------------
    discount = quantity_discount(quantity)
    unit_price *= 1 - discount

    rush_multiplier = pricing["rush_multipliers"].get(req.lead_time.value, 1.0)
    unit_price *= rush_multiplier

    total_price = unit_price * quantity

    minimum = commerce["minimum_order"]
    minimum_applied = total_price < minimum
    if minimum_applied:
        total_price = float(minimum)
        unit_price = total_price / quantity

    # --- manual review gates ----------------------------------------------------------
    requires_manual = False
    manual_reason: str | None = None
    total_hours = print_hours * quantity
    if total_hours > commerce["auto_decline_over_hours"]:
        requires_manual = True
        manual_reason = (
            f"{total_hours:.0f} hours of print time exceeds the "
            f"{commerce['auto_decline_over_hours']} hour ceiling for an automatic quote."
        )
    elif total_hours > commerce["max_auto_quote_hours"]:
        requires_manual = True
        manual_reason = (
            f"{total_hours:.0f} hours of print time is past the "
            f"{commerce['max_auto_quote_hours']} hour automatic-quote limit, so this one is "
            "priced by hand."
        )
    elif not geometry.fits_build_volume:
        requires_manual = True
        manual_reason = "The part does not fit the build volume and needs splitting first."
    elif geometry.units_suspect:
        requires_manual = True
        manual_reason = "The model's scale looks wrong, so the quote needs confirming by hand."

    lines = [
        CostLine(
            label="Material",
            amount=_round_money(material_cost),
            detail=(
                f"{total_grams:.0f} g of {material.name} at "
                f"${material.cost_per_kg:.0f}/kg, plus {pricing['waste_factor'] * 100:.0f}% waste"
            ),
        ),
        CostLine(
            label="Machine time",
            amount=_round_money(machine_cost),
            detail=(
                f"{print_hours:.1f} h at ${pricing['machine_rate_per_hour']:.2f}/h "
                "(depreciation, power, maintenance)"
            ),
        ),
        CostLine(
            label="Labour",
            amount=_round_money(labour_cost),
            detail=(
                f"setup, support removal and packing at ${pricing['labour_rate_per_hour']:.0f}/h"
            ),
        ),
        CostLine(
            label="Failure allowance",
            amount=_round_money(risk_amount),
            detail=f"{risk * 100:.0f}% estimated failure risk for this geometry and material",
        ),
        CostLine(
            label="Margin",
            amount=_round_money(margin_amount),
            detail=f"{pricing['margin'] * 100:.0f}%",
        ),
    ]
    if discount:
        lines.append(
            CostLine(
                label="Quantity discount",
                amount=_round_money(-unit_price * discount / max(1 - discount, 1e-6)),
                detail=f"{discount * 100:.0f}% off for {quantity} units",
            )
        )
    if rush_multiplier != 1.0:
        lines.append(
            CostLine(
                label="Rush" if rush_multiplier > 1 else "Relaxed lead time",
                amount=_round_money(unit_price * (1 - 1 / rush_multiplier)),
                detail=f"{req.lead_time.value} turnaround",
            )
        )
    if minimum_applied:
        lines.append(
            CostLine(
                label="Minimum order",
                amount=_round_money(minimum),
                detail=(
                    f"Below our ${minimum:.0f} minimum, which covers handling regardless of "
                    "print time"
                ),
            )
        )

    return Quote(
        material_id=material.id,
        material_name=material.name,
        quantity=quantity,
        unit_price=_round_money(unit_price),
        total_price=_round_money(total_price),
        currency=cfg["currency"],
        lines=lines,
        print_minutes_each=slice_result.print_minutes,
        filament_g_each=round(total_grams, 1),
        lead_time=req.lead_time or LeadTime.STANDARD,
        estimated=slice_result.estimated,
        requires_manual_review=requires_manual,
        manual_review_reason=manual_reason,
        minimum_applied=minimum_applied,
        expires_hours=commerce["quote_valid_hours"],
    )
