"""Tests that drive a real slicer.

Skipped when no slicer binary is present, so the suite still runs on a bare checkout. Where one
is installed these are the only tests that prove the quote is measured rather than estimated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worker.geometry import analyse
from worker.materials import by_id
from worker.slicing import (
    SlicerFamily,
    artifact_suffix,
    estimate,
    find_slicer,
    profile_dir,
    slice_mesh,
    slicer_family,
)

pytestmark = [
    pytest.mark.real_slicer,
    pytest.mark.skipif(find_slicer() is None, reason="no slicer binary installed"),
]

SETTINGS = {"walls": 3, "infill_percent": 20, "layer_height_mm": 0.2, "infill_pattern": "gyroid"}


def test_a_real_slice_is_not_flagged_as_estimated(box_stl: Path):
    geometry = analyse(box_stl)
    material = by_id("petg")
    result = slice_mesh(box_stl, material, SETTINGS, geometry)

    assert result.estimated is False
    assert result.slicer != "estimator"
    assert result.print_minutes > 0
    assert result.filament_g > 0


def test_slice_mass_is_physically_possible(box_stl: Path):
    """Extruded mass must sit between a hollow shell and a fully solid part."""
    geometry = analyse(box_stl)
    material = by_id("petg")
    result = slice_mesh(box_stl, material, SETTINGS, geometry)

    solid_g = geometry.volume_mm3 * material.density_g_cm3 / 1000.0
    assert 0.1 * solid_g < result.filament_g < solid_g


def test_more_infill_really_does_use_more_material(box_stl: Path):
    geometry = analyse(box_stl)
    material = by_id("petg")
    light = slice_mesh(box_stl, material, {**SETTINGS, "infill_percent": 10}, geometry)
    heavy = slice_mesh(box_stl, material, {**SETTINGS, "infill_percent": 60}, geometry)

    assert heavy.filament_g > light.filament_g
    assert heavy.print_minutes > light.print_minutes
    assert not (light.estimated or heavy.estimated)


def test_denser_material_weighs_more_for_the_same_toolpaths(box_stl: Path):
    geometry = analyse(box_stl)
    petg = slice_mesh(box_stl, by_id("petg"), SETTINGS, geometry)  # 1.27 g/cm3
    pp = slice_mesh(box_stl, by_id("pp"), SETTINGS, geometry)  # 0.90 g/cm3
    assert petg.filament_g > pp.filament_g


def test_a_generated_profile_exists_for_every_stocked_fdm_material():
    """A missing profile means the slicer silently falls back to its own defaults."""
    binary = find_slicer()
    directory = profile_dir(slicer_family(binary))
    if slicer_family(binary) is not SlicerFamily.PRUSA:
        pytest.skip("profile layout differs for Orca/Bambu")

    from worker.materials import load_materials

    missing = [
        m.id
        for m in load_materials()
        if m.in_stock and m.process == "fdm" and not (directory / f"{m.id}.ini").exists()
    ]
    assert not missing, f"no slicer profile for: {', '.join(missing)}"


def test_the_estimator_is_in_the_right_ballpark(box_stl: Path):
    """The fallback should be roughly right on a simple part, or it is not worth having.

    Deliberately loose: this is a smoke test that the estimator has not drifted into nonsense,
    not a claim of accuracy. The real comparison across part shapes is in docs/slicing.md.
    """
    geometry = analyse(box_stl)
    material = by_id("petg")
    real = slice_mesh(box_stl, material, SETTINGS, geometry)
    guess = estimate(geometry, material, SETTINGS)

    assert 0.4 < guess.filament_g / real.filament_g < 2.5
    assert 0.3 < guess.print_minutes / real.print_minutes < 3.0


def test_artifact_suffix_matches_the_slicer_family():
    binary = find_slicer()
    expected = ".gcode" if slicer_family(binary) is SlicerFamily.PRUSA else ".3mf"
    assert artifact_suffix(binary) == expected
