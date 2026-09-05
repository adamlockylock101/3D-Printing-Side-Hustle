"""The material property table, plus the shop's view of it (what is actually stocked)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import materials_config, shop_config

UV_RANK = {"poor": 0, "fair": 1, "good": 2, "excellent": 3}
WARP_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class Material:
    id: str
    name: str
    process: str
    tensile_mpa: float
    elongation_pct: float
    impact_notched: float | None
    hdt_045_c: float
    z_strength_ratio: float
    creep_resistance: int
    uv_resistance: str
    water_absorption_pct: float
    attacked_by: tuple[str, ...]
    density_g_cm3: float
    cost_per_kg: float
    printability: int
    warp: str
    requires_enclosure: bool
    requires_hardened_nozzle: bool
    requires_drying: bool
    food_safe_capable: bool
    notes: str = ""

    # Set from config/shop.yaml, not the property table.
    in_stock: bool = False
    colours: tuple[str, ...] = field(default_factory=tuple)

    @property
    def uv_rank(self) -> int:
        return UV_RANK.get(self.uv_resistance, 0)

    @property
    def warp_rank(self) -> int:
        return WARP_RANK.get(self.warp, 1)

    @property
    def is_resin(self) -> bool:
        return self.process.startswith("resin")

    def cost_per_gram(self) -> float:
        return self.cost_per_kg / 1000.0


def _coerce(raw: dict[str, Any], stocked: dict[str, list[str]]) -> Material:
    stock_entry = stocked.get(raw["id"])
    return Material(
        id=raw["id"],
        name=raw["name"],
        process=raw["process"],
        tensile_mpa=float(raw["tensile_mpa"]),
        elongation_pct=float(raw["elongation_pct"]),
        impact_notched=(
            None if raw.get("impact_notched") is None else float(raw["impact_notched"])
        ),
        hdt_045_c=float(raw["hdt_045_c"]),
        z_strength_ratio=float(raw["z_strength_ratio"]),
        creep_resistance=int(raw["creep_resistance"]),
        uv_resistance=str(raw["uv_resistance"]),
        water_absorption_pct=float(raw["water_absorption_pct"]),
        attacked_by=tuple(raw.get("attacked_by") or ()),
        density_g_cm3=float(raw["density_g_cm3"]),
        cost_per_kg=float(raw["cost_per_kg"]),
        printability=int(raw["printability"]),
        warp=str(raw["warp"]),
        requires_enclosure=bool(raw["requires_enclosure"]),
        requires_hardened_nozzle=bool(raw["requires_hardened_nozzle"]),
        requires_drying=bool(raw["requires_drying"]),
        food_safe_capable=bool(raw["food_safe_capable"]),
        notes=(raw.get("notes") or "").strip(),
        in_stock=stock_entry is not None,
        colours=tuple(stock_entry or ()),
    )


def load_materials() -> list[Material]:
    cfg = materials_config()
    stocked = {
        entry["id"]: entry.get("colours", []) for entry in shop_config().get("stocked_materials", [])
    }
    return [_coerce(raw, stocked) for raw in cfg["materials"]]


def table_version() -> str:
    return str(materials_config().get("version", "unknown"))


def process_capability_mm(process: str) -> float:
    defaults = materials_config().get("process_defaults", {})
    key = "resin_msla" if process.startswith("resin") else "fdm_04_nozzle"
    return float(defaults.get(key, {}).get("process_capability_mm", 0.20))


def process_tolerance_floor_mm(process: str) -> float:
    """Tightest tolerance the process can be pushed to. Below this, decline rather than promise."""
    defaults = materials_config().get("process_defaults", {})
    key = "resin_msla" if process.startswith("resin") else "fdm_04_nozzle"
    return float(defaults.get(key, {}).get("tolerance_floor_mm", 0.15))


def process_min_feature_mm(process: str) -> float:
    defaults = materials_config().get("process_defaults", {})
    key = "resin_msla" if process.startswith("resin") else "fdm_04_nozzle"
    return float(defaults.get(key, {}).get("min_feature_mm", 0.8))


def by_id(material_id: str) -> Material | None:
    for material in load_materials():
        if material.id == material_id:
            return material
    return None
