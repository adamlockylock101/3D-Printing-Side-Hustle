"""The light geometry checks, as structured findings.

These run at upload, before any material is known, using the process defaults; and again at
quote time with the recommended material's thresholds and the orientation it will print in.
Each one says what it measured, against what, where, why it matters and what to change. The
one-line `message` is what `GeometryReport.warnings` carries, so it keeps the wording those
warnings always had.
"""

from __future__ import annotations

from typing import Any

from .schemas import DesignFinding, FindingLocation, Severity


def _whole_part(bbox: tuple[float, float, float]) -> FindingLocation:
    return FindingLocation(
        description="The whole part",
        bbox_min=(0.0, 0.0, 0.0),
        bbox_max=bbox,
    )


def build_volume(
    bbox: tuple[float, float, float], build: tuple[float, float, float], fits: bool
) -> DesignFinding | None:
    if fits:
        return None
    largest = max(bbox)
    return DesignFinding(
        check="build_volume",
        severity=Severity.MUST_FIX,
        message=(
            f"The part is {bbox[0]:.0f} x {bbox[1]:.0f} x {bbox[2]:.0f} mm, which does not fit "
            f"the {build[0]:.0f} x {build[1]:.0f} x {build[2]:.0f} mm build volume. It will need "
            "splitting into sections, or scaling down."
        ),
        measured=round(largest, 1),
        threshold=round(max(build), 1),
        unit="mm",
        location=_whole_part(bbox),
        why="No orientation fits it on the printer in one piece.",
        fix=(
            "Split the model into sections that each fit, with a dovetail, pins or bolt bosses "
            "to join them, or scale it down if the size is not critical."
        ),
    )


def units(
    bbox: tuple[float, float, float], build: tuple[float, float, float], rules: dict[str, Any]
) -> DesignFinding | None:
    largest = max(bbox)
    low = float(rules.get("units_min_dimension_mm", 5.0))
    high = max(build) * float(rules.get("units_max_build_multiple", 10.0))
    if low <= largest <= high:
        return None
    too_small = largest < low
    return DesignFinding(
        check="units",
        severity=Severity.MUST_FIX,
        message=(
            f"The largest dimension is {largest:.2f} mm, which looks like a unit mismatch "
            "(STL files carry no units, so a model drawn in inches arrives 25.4x too small). "
            "Please confirm the intended size."
        ),
        measured=round(largest, 2),
        threshold=low if too_small else round(high, 0),
        unit="mm",
        location=_whole_part(bbox),
        why=(
            "We print the file at the size it says. If it was drawn in inches or metres, the "
            "part arrives the wrong size and the quote is for the wrong part."
        ),
        fix=(
            f"Re-export in millimetres. If it was drawn in inches, it should be about "
            f"{largest * 25.4:.0f} mm across."
            if too_small
            else "Re-export in millimetres; this looks like a model drawn in metres or scaled up."
        ),
    )


def min_wall(min_wall_mm: float | None, rules: dict[str, Any]) -> DesignFinding | None:
    threshold = float(rules.get("min_wall_mm", 0.42))
    if min_wall_mm is None or min_wall_mm >= threshold:
        return None
    return DesignFinding(
        check="min_wall",
        # Advise, not must-fix: the thickness is sampled, not solved, so it can be wrong.
        severity=Severity.ADVISE,
        message=(
            f"The thinnest wall measures about {min_wall_mm:.2f} mm, below the "
            f"{threshold:.2f} mm a 0.4 mm nozzle can lay down. Those features will "
            "be dropped or come out fragile."
        ),
        measured=round(min_wall_mm, 2),
        threshold=threshold,
        unit="mm",
        location=FindingLocation(description="Thinnest sampled wall; check thin ribs and fins"),
        why=(
            "The nozzle lays plastic in lines of a fixed width. A wall thinner than one line "
            "is either skipped by the slicer or printed as a single fragile strand."
        ),
        fix=(
            f"Thicken those walls to at least {max(threshold * 2, 0.8):.1f} mm (two lines), "
            "or remove the feature if it is cosmetic."
        ),
    )


def overhang(
    fraction: float, rules: dict[str, Any], bbox: tuple[float, float, float], oriented: bool
) -> DesignFinding | None:
    threshold = float(rules.get("max_overhang_fraction", 0.4))
    if fraction <= threshold:
        return None
    angle = float(rules.get("overhang_angle_deg", 45))
    where = " in the orientation we will print it" if oriented else ""
    return DesignFinding(
        check="overhang",
        severity=Severity.ADVISE,
        message=(
            f"About {fraction * 100:.0f}% of the surface overhangs past {angle:.0f} degrees"
            f"{where}, so the part needs substantial support. Expect visible witness marks on "
            "those faces."
        ),
        measured=round(fraction, 3),
        threshold=threshold,
        unit="fraction of surface",
        location=_whole_part(bbox),
        why=(
            "Support holds up surfaces printed in mid-air. It costs material and time, and "
            "leaves a rough surface where it is broken away."
        ),
        fix=(
            f"Chamfer downward-facing edges to {angle:.0f} degrees or steeper, split the part "
            "so each piece prints flat, or mark the face that matters so we keep support off it."
        ),
    )


def aspect_ratio(ratio: float, rules: dict[str, Any], height: float) -> DesignFinding | None:
    threshold = float(rules.get("max_aspect_ratio", 4.0))
    if ratio <= threshold:
        return None
    return DesignFinding(
        check="aspect_ratio",
        severity=Severity.ADVISE,
        message=(
            "The part is tall relative to its footprint and may need a brim to stay on the plate."
        ),
        measured=round(ratio, 2),
        threshold=threshold,
        unit="height / sqrt(footprint)",
        location=FindingLocation(description="Upper part of the print", z_mm=round(height, 1)),
        why=(
            "A tall narrow print is levered by the nozzle at every layer. If it lets go of the "
            "bed partway up, the whole print is lost."
        ),
        fix=(
            "We will add a brim. A wider base, or a flat face it can be printed on, would make "
            "it more reliable."
        ),
    )


def triangle_count(count: int, rules: dict[str, Any]) -> DesignFinding | None:
    threshold = int(rules.get("max_triangles", 1_500_000))
    if count <= threshold:
        return None
    return DesignFinding(
        check="triangle_count",
        severity=Severity.INFO,
        message=(
            "Very high triangle count. The mesh may have been exported at unnecessary "
            "resolution; this slows slicing but does not affect the print."
        ),
        measured=float(count),
        threshold=float(threshold),
        unit="triangles",
        why="The printer cannot resolve detail finer than about 0.1 mm anyway.",
        fix="Export with a coarser chord tolerance (0.01-0.05 mm is plenty).",
    )


def base_findings(
    *,
    bbox: tuple[float, float, float],
    build: tuple[float, float, float],
    fits: bool,
    min_wall_mm: float | None,
    overhang_fraction: float,
    aspect: float,
    height: float,
    triangles: int,
    rules: dict[str, Any],
    oriented: bool = False,
) -> list[DesignFinding]:
    checks = [
        build_volume(bbox, build, fits),
        units(bbox, build, rules),
        min_wall(min_wall_mm, rules),
        overhang(overhang_fraction, rules, bbox, oriented),
        aspect_ratio(aspect, rules, height),
        triangle_count(triangles, rules),
    ]
    return [finding for finding in checks if finding is not None]
