"""Shared data shapes.

The requirements vector is the contract between the LLM intake step and the deterministic
selection engine. The LLM only ever fills this in; it never chooses a material.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------------------
# Requirements
# --------------------------------------------------------------------------------------


class Lifecycle(StrEnum):
    PROTOTYPE = "prototype"
    FIT_CHECK = "fit_check"
    FUNCTIONAL_PROTOTYPE = "functional_prototype"
    END_USE = "end_use"
    COSMETIC = "cosmetic"


class LoadType(StrEnum):
    NONE = "none"
    TENSION = "tension"
    COMPRESSION = "compression"
    BENDING = "bending"
    SHEAR = "shear"
    IMPACT = "impact"
    CYCLIC = "cyclic"
    CLAMPING = "clamping"


class LoadDuration(StrEnum):
    MOMENTARY = "momentary"
    INTERMITTENT = "intermittent"
    SUSTAINED = "sustained"


class BrittlenessTolerance(StrEnum):
    MUST_NOT_SHATTER = "must_not_shatter"
    PREFER_DUCTILE = "prefer_ductile"
    INDIFFERENT = "indifferent"
    STIFFNESS_PREFERRED = "stiffness_preferred"


class Moisture(StrEnum):
    DRY = "dry"
    HUMID = "humid"
    SPLASH = "splash"
    IMMERSED = "immersed"


class Chemical(StrEnum):
    FUELS = "fuels"
    OILS = "oils"
    SOLVENTS = "solvents"
    ACIDS = "acids"
    BASES = "bases"
    ALCOHOLS = "alcohols"


class CostSensitivity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LeadTime(StrEnum):
    RELAXED = "relaxed"
    STANDARD = "standard"
    RUSH = "rush"


class Load(BaseModel):
    type: LoadType | None = None
    magnitude_n: float | None = Field(
        default=None, description="Peak load in newtons, if the customer gave a number"
    )
    qualitative: Literal["light", "moderate", "heavy"] | None = None
    duration: LoadDuration | None = None


class Thermal(BaseModel):
    max_service_c: float | None = None
    min_service_c: float | None = None
    sunlight_hot_car: bool | None = Field(
        default=None,
        description="Left in sun or in a parked car. Implies ~70-80 C even in mild climates.",
    )


class Environment(BaseModel):
    outdoor_uv: bool | None = None
    moisture: Moisture | None = None
    chemicals: list[Chemical] = Field(default_factory=list)
    food_contact: bool | None = None
    skin_contact: bool | None = None


class Precision(BaseModel):
    tolerance_mm: float | None = None
    tolerance_class: Literal["cosmetic", "standard", "tight", "press_fit"] | None = None
    fit_critical: bool | None = None
    min_feature_mm: float | None = None


class Aesthetics(BaseModel):
    visible: bool | None = None
    colour: str | None = None
    finish: Literal["as_printed", "smooth", "paintable"] | None = None


class Requirements(BaseModel):
    """The parsed intake. Every field is optional; unknowns drive the follow-up questions."""

    lifecycle: Lifecycle | None = None
    load: Load = Field(default_factory=Load)
    brittleness_tolerance: BrittlenessTolerance | None = None
    thermal: Thermal = Field(default_factory=Thermal)
    environment: Environment = Field(default_factory=Environment)
    precision: Precision = Field(default_factory=Precision)
    aesthetics: Aesthetics = Field(default_factory=Aesthetics)
    cost_sensitivity: CostSensitivity | None = None
    lead_time: LeadTime = LeadTime.STANDARD
    quantity: int = 1
    notes_freeform: str | None = None

    # Populated by the intake step, not the customer.
    field_confidence: dict[str, float] = Field(default_factory=dict)
    raw_text: str | None = None

    def effective_max_temp_c(self) -> float | None:
        """Service temperature including the hot-car inference.

        Customers routinely say "it goes in my car" without connecting that to temperature.
        A parked car interior reaches 70-80 C in summer sun, which is above PLA's HDT and is
        the single most common cause of a part failing in the field.
        """
        stated = self.thermal.max_service_c
        implied = 70.0 if self.thermal.sunlight_hot_car else None
        candidates = [c for c in (stated, implied) if c is not None]
        return max(candidates) if candidates else None

    def effective_tolerance_mm(self) -> float | None:
        if self.precision.tolerance_mm is not None:
            return self.precision.tolerance_mm
        # "tight" sits exactly at what a well-tuned FDM machine can hold, deliberately: it is
        # the option a customer picks for a part that mates with something, and it must lead to
        # a quote rather than a decline. "press_fit" is genuinely beyond FDM and should decline.
        return {
            "cosmetic": 0.5,
            "standard": 0.25,
            "tight": 0.15,
            "press_fit": 0.08,
        }.get(self.precision.tolerance_class or "")


# --------------------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------------------


class GeometryReport(BaseModel):
    bbox_mm: tuple[float, float, float]
    volume_mm3: float
    surface_area_mm2: float
    triangle_count: int
    is_watertight: bool
    min_wall_mm: float | None = None
    overhang_fraction: float = 0.0
    footprint_mm2: float = 0.0
    height_to_footprint_ratio: float = 0.0
    fits_build_volume: bool = True
    warnings: list[str] = Field(default_factory=list)
    units_suspect: bool = Field(
        default=False,
        description="Bounding box implies the file may be in inches rather than millimetres",
    )

    def risk_score(self) -> float:
        """0-1 estimate of how likely this geometry is to fail on the plate.

        Feeds the pricing risk buffer. Deliberately simple and explainable — the real numbers
        should come from logged job outcomes once there are enough of them.
        """
        score = 0.0
        if self.height_to_footprint_ratio > 3:
            score += 0.25
        elif self.height_to_footprint_ratio > 1.5:
            score += 0.10
        if self.overhang_fraction > 0.5:
            score += 0.25
        elif self.overhang_fraction > 0.3:
            score += 0.12
        if self.min_wall_mm is not None and self.min_wall_mm < 0.8:
            score += 0.20
        if not self.is_watertight:
            score += 0.15
        if self.footprint_mm2 < 400:
            score += 0.10
        return min(score, 1.0)


# --------------------------------------------------------------------------------------
# Recommendation
# --------------------------------------------------------------------------------------


class RejectedMaterial(BaseModel):
    material_id: str
    name: str
    reason: str


class MaterialScore(BaseModel):
    material_id: str
    name: str
    score: float
    drivers: list[str] = Field(
        default_factory=list, description="Properties that most helped this material's score"
    )
    trade_off: str | None = None
    cost_per_kg: float
    in_stock: bool


class Recommendation(BaseModel):
    primary: MaterialScore
    alternates: list[MaterialScore] = Field(default_factory=list)
    rejected: list[RejectedMaterial] = Field(default_factory=list)
    rationale: str
    orientation_advice: str | None = None
    print_settings: dict[str, object] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    table_version: str = "unknown"
    escalate_to_resin: bool = False
    declined: bool = False
    declined_reason: str | None = None


# --------------------------------------------------------------------------------------
# Slicing and quoting
# --------------------------------------------------------------------------------------


class SliceResult(BaseModel):
    print_minutes: float
    filament_g: float
    support_g: float = 0.0
    layer_height_mm: float = 0.2
    estimated: bool = Field(
        default=False, description="True when derived from geometry rather than a real slice"
    )
    slicer: str = "estimator"


class CostLine(BaseModel):
    label: str
    amount: float
    detail: str | None = None


class Quote(BaseModel):
    material_id: str
    material_name: str
    quantity: int
    unit_price: float
    total_price: float
    currency: str
    lines: list[CostLine]
    print_minutes_each: float
    filament_g_each: float
    lead_time: LeadTime
    estimated: bool
    requires_manual_review: bool = False
    manual_review_reason: str | None = None
    minimum_applied: bool = False
    expires_hours: int = 168
