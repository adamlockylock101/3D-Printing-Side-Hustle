"""Slicing.

Two paths. When a slicer binary is configured we run the real thing against the real machine
profile and read time and mass out of the generated G-code — that is what makes an instant
quote honest. Without one we fall back to a geometry estimator, and every downstream object
is flagged `estimated=True` so nothing silently presents a guess as a measurement.

Bambu machines take a `.3mf` project file rather than raw G-code (the AMS mapping and plate
metadata live in the 3mf), so the target slicer is Bambu Studio or OrcaSlicer, not PrusaSlicer.
See docs/decisions.md D1.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .materials import Material
from .schemas import GeometryReport, SliceResult

SLICER_CANDIDATES = ("bambu-studio", "orca-slicer", "orcaslicer", "prusa-slicer", "prusaslicer")
SLICE_TIMEOUT_S = 300

# Effective volumetric flow for a 0.4 mm nozzle once travel, acceleration and cooling limits are
# accounted for. Bench flow is higher; this is the number that matches real wall-clock times.
EFFECTIVE_FLOW_MM3_S = 9.0

# Per-layer fixed overhead: z-hop, seam, retraction, minimum layer time.
LAYER_OVERHEAD_S = 1.6

TIME_RE = re.compile(
    r";\s*(?:estimated printing time|total estimated time).*?=\s*"
    r"(?:(\d+)d\s*)?(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?",
    re.IGNORECASE,
)
FILAMENT_G_RE = re.compile(r";\s*(?:total )?filament used \[g\]\s*=\s*([\d.]+)", re.IGNORECASE)
SUPPORT_G_RE = re.compile(
    r";\s*support (?:filament|material) used \[g\]\s*=\s*([\d.]+)", re.IGNORECASE
)


def find_slicer() -> str | None:
    """Locate a slicer binary from SLICER_BIN or the PATH."""
    explicit = os.environ.get("SLICER_BIN")
    if explicit and Path(explicit).exists():
        return explicit
    for candidate in SLICER_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
    return None


# --------------------------------------------------------------------------------------
# Estimator fallback
# --------------------------------------------------------------------------------------


def estimate(geometry: GeometryReport, material: Material, settings: dict[str, Any]) -> SliceResult:
    """Estimate time and mass from geometry alone.

    Deliberately conservative and explainable. Shell volume is surface area times the wall
    thickness; whatever is left inside is filled at the infill fraction. Good to roughly
    +/-25% on typical parts, which is close enough to quote from when it is clearly labelled
    as an estimate and reviewed before it is committed to.
    """
    walls = int(settings.get("walls", 3))
    infill = float(settings.get("infill_percent", 20)) / 100.0
    layer_height = float(settings.get("layer_height_mm", 0.2))
    extrusion_width = 0.45

    shell_thickness = walls * extrusion_width
    shell_volume = min(geometry.surface_area_mm2 * shell_thickness, geometry.volume_mm3)
    core_volume = max(geometry.volume_mm3 - shell_volume, 0.0)
    extruded_mm3 = shell_volume + core_volume * infill

    support_mm3 = 0.0
    if geometry.overhang_fraction > 0.05:
        # Support scales with the overhanging area and how far it has to reach down. Half the
        # part height is a reasonable mean drop for a typical part.
        support_area = geometry.surface_area_mm2 * geometry.overhang_fraction
        support_mm3 = support_area * (geometry.bbox_mm[2] * 0.5) * 0.12

    density = material.density_g_cm3 / 1000.0  # g per mm^3
    filament_g = extruded_mm3 * density
    support_g = support_mm3 * density

    layers = max(1, math.ceil(geometry.bbox_mm[2] / layer_height))
    extrude_seconds = (extruded_mm3 + support_mm3) / EFFECTIVE_FLOW_MM3_S
    overhead_seconds = layers * LAYER_OVERHEAD_S
    print_minutes = (extrude_seconds + overhead_seconds) / 60.0

    return SliceResult(
        print_minutes=round(print_minutes, 1),
        # Three decimals, not two: a part small enough to round to 0.00 g would otherwise trip
        # the "we could not measure this" guard in pricing and mask the real problem, which is
        # usually that the model is scaled wrong.
        filament_g=round(filament_g, 3),
        support_g=round(support_g, 3),
        layer_height_mm=layer_height,
        estimated=True,
        slicer="estimator",
    )


# --------------------------------------------------------------------------------------
# Real slicing
# --------------------------------------------------------------------------------------


def _parse_gcode_stats(text: str) -> tuple[float | None, float | None, float]:
    minutes: float | None = None
    match = TIME_RE.search(text)
    if match:
        days, hours, mins, secs = (int(g or 0) for g in match.groups())
        minutes = days * 1440 + hours * 60 + mins + secs / 60.0

    grams: float | None = None
    grams_match = FILAMENT_G_RE.search(text)
    if grams_match:
        grams = float(grams_match.group(1))

    support = 0.0
    support_match = SUPPORT_G_RE.search(text)
    if support_match:
        support = float(support_match.group(1))

    return minutes, grams, support


def _read_output_stats(output: Path) -> tuple[float | None, float | None, float]:
    """Pull stats out of a .gcode file, or out of the G-code embedded in a .3mf archive."""
    if output.suffix.lower() == ".3mf":
        with zipfile.ZipFile(output) as archive:
            for name in archive.namelist():
                if name.endswith((".gcode", ".gcode.md5", ".gcode.txt")) and name.endswith(
                    ".gcode"
                ):
                    with archive.open(name) as fh:
                        return _parse_gcode_stats(fh.read().decode("utf-8", "ignore"))
        return None, None, 0.0
    return _parse_gcode_stats(output.read_text(encoding="utf-8", errors="ignore"))


def _build_command(
    binary: str,
    mesh_path: Path,
    material: Material,
    settings: dict[str, Any],
    output: Path,
    profile_dir: Path,
) -> list[str]:
    cmd = [
        binary,
        "--export-3mf",
        str(output),
        "--slice",
        "0",
        "--layer-height",
        str(settings.get("layer_height_mm", 0.2)),
        "--wall-loops",
        str(settings.get("walls", 3)),
        "--sparse-infill-density",
        f"{settings.get('infill_percent', 20)}%",
    ]
    machine_profile = profile_dir / "machine.json"
    process_profile = profile_dir / f"{material.id}.json"
    if machine_profile.exists() and process_profile.exists():
        cmd += ["--load-settings", f"{machine_profile};{process_profile}"]
    cmd.append(str(mesh_path))
    return cmd


def _profile_dir() -> Path:
    return Path(os.environ.get("SLICER_PROFILES", "config/slicer-profiles"))


def slice_mesh(
    mesh_path: str | Path,
    material: Material,
    settings: dict[str, Any],
    geometry: GeometryReport,
    profile_dir: Path | None = None,
) -> SliceResult:
    """Slice for real if a slicer is available, otherwise estimate.

    Never raises on slicer failure: a quote that arrives as an estimate beats a 500.
    """
    binary = find_slicer()
    if binary is None:
        return estimate(geometry, material, settings)

    profile_dir = profile_dir or _profile_dir()
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "out.3mf"
        cmd = _build_command(binary, Path(mesh_path), material, settings, output, profile_dir)
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=SLICE_TIMEOUT_S, text=True)
            minutes, grams, support = _read_output_stats(output)
        except (subprocess.SubprocessError, OSError, zipfile.BadZipFile):
            return estimate(geometry, material, settings)

    if minutes is None or grams is None:
        return estimate(geometry, material, settings)

    return SliceResult(
        print_minutes=round(minutes, 1),
        filament_g=round(grams, 2),
        support_g=round(support, 2),
        layer_height_mm=float(settings.get("layer_height_mm", 0.2)),
        estimated=False,
        slicer=Path(binary).name,
    )


class SlicerUnavailable(RuntimeError):
    pass


def produce_artifact(
    mesh_path: str | Path,
    material: Material,
    settings: dict[str, Any],
    destination: Path,
    profile_dir: Path | None = None,
) -> SliceResult:
    """Slice to a real .3mf on disk, for an approved job.

    Unlike `slice_mesh`, this raises rather than estimating: an approved job needs a file the
    printer can actually run, and quietly handing back an estimate would be worse than an error.

    The .3mf carries the plate layout, AMS filament assignment and slicer metadata that a Bambu
    machine needs — raw G-code is not enough. See docs/decisions.md D1.
    """
    binary = find_slicer()
    if binary is None:
        raise SlicerUnavailable(
            "No slicer binary configured. Set SLICER_BIN to your Bambu Studio or OrcaSlicer "
            "executable, or export the plate from the slicer by hand."
        )

    profile_dir = profile_dir or _profile_dir()
    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = _build_command(binary, Path(mesh_path), material, settings, destination, profile_dir)
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=SLICE_TIMEOUT_S, text=True)
    except subprocess.CalledProcessError as exc:
        raise SlicerUnavailable(f"The slicer failed: {exc.stderr or exc.stdout}".strip()) from exc
    except (subprocess.SubprocessError, OSError) as exc:
        raise SlicerUnavailable(f"The slicer could not be run: {exc}") from exc

    if not destination.exists():
        raise SlicerUnavailable("The slicer produced no output file.")

    minutes, grams, support = _read_output_stats(destination)
    return SliceResult(
        print_minutes=round(minutes or 0.0, 1),
        filament_g=round(grams or 0.0, 2),
        support_g=round(support, 2),
        layer_height_mm=float(settings.get("layer_height_mm", 0.2)),
        estimated=False,
        slicer=Path(binary).name,
    )
