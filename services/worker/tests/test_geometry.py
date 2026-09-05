from __future__ import annotations

from pathlib import Path

import pytest

from worker.geometry import UnsupportedMesh, analyse


def test_box_measures_correctly(box_stl: Path):
    report = analyse(box_stl)
    assert report.bbox_mm == pytest.approx((40.0, 30.0, 20.0))
    assert report.volume_mm3 == pytest.approx(24_000, rel=0.01)
    assert report.is_watertight
    assert report.fits_build_volume
    assert report.warnings == []
    assert report.overhang_fraction == pytest.approx(0.0, abs=1e-6)


def test_box_footprint_is_the_projected_area(box_stl: Path):
    report = analyse(box_stl)
    assert report.footprint_mm2 == pytest.approx(1200.0, rel=0.01)


def test_thin_walls_are_detected_and_warned_about(thin_tube_stl: Path):
    report = analyse(thin_tube_stl)
    assert report.min_wall_mm == pytest.approx(0.3, abs=0.08)
    assert any("thinnest wall" in w for w in report.warnings)


def test_oversized_part_does_not_fit(oversized_stl: Path):
    report = analyse(oversized_stl)
    assert not report.fits_build_volume
    assert any("build volume" in w for w in report.warnings)


def test_inch_scale_model_is_flagged(inch_scale_stl: Path):
    report = analyse(inch_scale_stl)
    assert report.units_suspect
    assert any("unit mismatch" in w for w in report.warnings)


def test_tall_narrow_part_scores_as_risky(tall_spike_stl: Path, box_stl: Path):
    spike = analyse(tall_spike_stl)
    block = analyse(box_stl)
    assert spike.height_to_footprint_ratio > block.height_to_footprint_ratio
    assert spike.risk_score() > block.risk_score()


def test_unsupported_format_is_rejected_with_a_readable_message(tmp_path: Path):
    bad = tmp_path / "model.step"
    bad.write_text("not a mesh")
    with pytest.raises(UnsupportedMesh) as excinfo:
        analyse(bad)
    assert ".stl" in str(excinfo.value)


def test_risk_score_stays_in_range(tall_spike_stl: Path, thin_tube_stl: Path, box_stl: Path):
    for fixture in (tall_spike_stl, thin_tube_stl, box_stl):
        assert 0.0 <= analyse(fixture).risk_score() <= 1.0
