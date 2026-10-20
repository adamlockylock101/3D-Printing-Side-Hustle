"""The design feedback layer: structured findings, orientation, load across layers, holes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import trimesh
from conftest import l_bracket
from shapely.geometry import Point, Polygon

from worker.design import (
    _choose,
    band,
    design_load,
    find_holes,
    review,
    section_modulus_min,
)
from worker.geometry import analyse, analyse_mesh
from worker.materials import by_id, design_rules, load_materials
from worker.orientation import orient_mesh
from worker.schemas import (
    Aesthetics,
    Load,
    LoadType,
    OrientationCandidate,
    Precision,
    Requirements,
    Severity,
)

SETTINGS = {"walls": 4, "infill_percent": 40, "layer_height_mm": 0.2}


def run_review(mesh, material_id="petg", req=None, **kwargs):
    return review(
        mesh,
        analyse_mesh(mesh),
        by_id(material_id),
        req or Requirements(),
        SETTINGS,
        **kwargs,
    )


def finding(report, check):
    return next((f for f in report.findings if f.check == check), None)


def bending(qualitative="heavy", **load):
    return Requirements(load=Load(type=LoadType.BENDING, qualitative=qualitative, **load))


# --------------------------------------------------------------------------------------
# Section properties
# --------------------------------------------------------------------------------------


def test_section_modulus_of_a_rectangle_is_the_textbook_value():
    # b h^2 / 6 about the weak axis: 60 x 6 mm gives 360 mm3.
    rect = Polygon([(0, 0), (60, 0), (60, 6), (0, 6)])
    assert section_modulus_min(rect) == pytest.approx(360.0, rel=1e-6)


def test_section_modulus_subtracts_holes():
    solid = Point(0, 0).buffer(10, 256)
    tube = solid.difference(Point(0, 0).buffer(6, 256))
    # pi (D^4 - d^4) / (32 D) for a tube, against pi D^3 / 32 for the bar.
    assert section_modulus_min(solid) == pytest.approx(785.4, rel=0.01)
    assert section_modulus_min(tube) == pytest.approx(683.6, rel=0.01)


# --------------------------------------------------------------------------------------
# Structured findings from the existing checks
# --------------------------------------------------------------------------------------


def test_warnings_are_the_findings_messages(thin_tube_stl: Path, oversized_stl: Path):
    for path in (thin_tube_stl, oversized_stl):
        report = analyse(path)
        assert report.findings
        assert report.warnings == [f.message for f in report.findings]


def test_a_clean_part_has_no_findings_at_upload(box_stl: Path):
    report = analyse(box_stl)
    assert report.findings == []
    assert report.warnings == []


def test_thin_wall_finding_says_how_far_off_and_what_to_do(thin_tube_stl: Path):
    wall = finding(analyse(thin_tube_stl), "min_wall")
    assert wall.severity == Severity.ADVISE
    assert wall.measured == pytest.approx(0.3, abs=0.08)
    assert wall.threshold == pytest.approx(0.42)
    assert "Thicken" in wall.fix


def test_oversized_part_is_a_must_fix(oversized_stl: Path):
    found = finding(analyse(oversized_stl), "build_volume")
    assert found.severity == Severity.MUST_FIX
    assert found.measured > found.threshold
    assert "Split" in found.fix


def test_inch_model_finding_gives_the_likely_real_size(inch_scale_stl: Path):
    found = finding(analyse(inch_scale_stl), "units")
    assert found.severity == Severity.MUST_FIX
    # 2.0 inches across, so about 51 mm.
    assert "51 mm" in found.fix


def test_tall_part_finding_points_at_its_top(tall_spike_stl: Path):
    found = finding(analyse(tall_spike_stl), "aspect_ratio")
    assert found.location.z_mm == pytest.approx(90, abs=1)
    assert "brim" in found.fix


def test_broken_mesh_is_reported_as_a_finding(open_mesh_stl: Path):
    report = analyse(open_mesh_stl)
    assert {f.check for f in report.findings} >= {"mesh_integrity"}
    assert any("watertight" in w for w in report.warnings)


def test_triangle_count_threshold_comes_from_config(box_stl: Path):
    rules = design_rules()
    rules["max_triangles"] = 5
    report = analyse_mesh(trimesh.load(box_stl), rules)
    found = finding(report, "triangle_count")
    assert found.severity == Severity.INFO
    assert found.threshold == 5


# --------------------------------------------------------------------------------------
# Thresholds by material
# --------------------------------------------------------------------------------------


def test_material_design_rules_merge_over_the_process_defaults():
    pla, tpu = design_rules(by_id("pla")), design_rules(by_id("tpu_95a"))
    assert pla["min_wall_mm"] == pytest.approx(0.42)
    assert tpu["min_wall_mm"] == pytest.approx(0.8)
    assert tpu["holes"]["oversize_allowance_mm"] == pytest.approx(0.4)
    # Keys the material does not override still come through.
    assert tpu["holes"]["min_circularity"] == pla["holes"]["min_circularity"]


def test_a_wall_fine_in_pla_is_flagged_in_tpu():
    tube = trimesh.creation.annulus(r_min=9.4, r_max=10.0, height=30, sections=96)
    assert finding(run_review(tube, "pla").geometry, "min_wall") is None
    flagged = finding(run_review(tube, "tpu_95a").geometry, "min_wall")
    assert flagged is not None
    assert flagged.threshold == pytest.approx(0.8)


# --------------------------------------------------------------------------------------
# Orientation
# --------------------------------------------------------------------------------------


def test_a_box_prints_as_modelled(box_stl: Path):
    result = run_review(trimesh.load(box_stl))
    assert result.face_down == "bottom"
    chosen = result.geometry.orientation.chosen()
    assert chosen.support_mm3 == pytest.approx(0.0)
    assert finding(result.geometry, "orientation").severity == Severity.INFO


def test_an_upside_down_part_is_turned_over(l_bracket_mesh):
    # Uploaded with the base on top and the web hanging down: as modelled it needs support.
    upside_down = orient_mesh(l_bracket_mesh, "top")
    result = run_review(upside_down)
    assert result.face_down != "bottom"
    assert result.geometry.orientation.chosen().support_mm3 == pytest.approx(0.0)
    # Pricing runs on the part as it will print, so it sees no overhang.
    assert result.print_geometry.overhang_fraction == pytest.approx(0.0, abs=1e-6)


def test_every_candidate_is_reported(l_bracket_mesh):
    candidates = run_review(l_bracket_mesh).geometry.orientation.candidates
    assert {c.face_down for c in candidates} == {
        "bottom",
        "top",
        "front",
        "back",
        "left",
        "right",
    }
    assert min(c.time_index for c in candidates) == pytest.approx(1.0)


def dumbbell() -> trimesh.Trimesh:
    """Two 30 mm caps on an 8 mm stem: every orientation needs some support."""
    top = trimesh.creation.box(extents=(30, 30, 6))
    top.apply_translation((0, 0, 39))
    stem = trimesh.creation.box(extents=(8, 8, 36))
    stem.apply_translation((0, 0, 21))
    bottom = trimesh.creation.box(extents=(30, 30, 6))
    bottom.apply_translation((0, 0, 3))
    return trimesh.boolean.union([top, stem, bottom], engine="manifold")


def test_support_is_kept_off_the_cosmetic_face():
    part = dumbbell()
    free = run_review(part)
    assert free.geometry.orientation.chosen().support_mm3 > 0
    # Mark as cosmetic the very face that the free choice puts support on.
    marked = free.face_down
    req = Requirements(aesthetics=Aesthetics(visible=True, cosmetic_face=marked))
    kept = run_review(part, req=req)
    assert kept.face_down != marked
    assert kept.geometry.orientation.chosen().cosmetic_support_mm2 <= 5.0
    assert "keeps support off" in finding(kept.geometry, "orientation").message


def candidate(face, score, safety=None, cosmetic=0.0):
    return OrientationCandidate(
        face_down=face,
        support_mm3=0.0,
        support_fraction=0.0,
        bed_contact_mm2=100.0,
        height_mm=10.0,
        time_index=1.0,
        cosmetic_support_mm2=cosmetic,
        safety_factor=safety,
        score=score,
    )


RULES = design_rules()


def test_strength_beats_support_and_time_on_a_loaded_part():
    pool = [candidate("bottom", 0.0, safety=1.0), candidate("front", 0.5, safety=5.0)]
    decision = _choose(pool, RULES, None, None)
    assert decision.chosen.face_down == "front"
    assert decision.strength_decided


def test_near_equal_strength_leaves_the_choice_to_the_other_factors():
    pool = [candidate("bottom", 0.0, safety=4.5), candidate("front", 0.5, safety=5.0)]
    decision = _choose(pool, RULES, None, None)
    assert decision.chosen.face_down == "bottom"
    assert not decision.strength_decided


def test_strength_beats_the_cosmetic_face_and_says_so():
    pool = [
        candidate("bottom", 0.0, safety=1.0, cosmetic=0.0),
        candidate("front", 0.5, safety=5.0, cosmetic=400.0),
    ]
    decision = _choose(pool, RULES, "top", None)
    assert decision.chosen.face_down == "front"
    assert decision.cosmetic_conflict


def test_the_operator_override_is_honoured():
    pool = [candidate("bottom", 0.0, safety=1.0), candidate("front", 0.5, safety=5.0)]
    decision = _choose(pool, RULES, None, "bottom")
    assert decision.chosen.face_down == "bottom"
    assert decision.overridden


# --------------------------------------------------------------------------------------
# Load across the layers
# --------------------------------------------------------------------------------------


def test_the_l_bracket_is_laid_on_its_side_for_strength(l_bracket_mesh):
    result = run_review(l_bracket_mesh, req=bending())
    assert result.face_down in ("front", "back")
    strength = finding(result.geometry, "load_vs_layers")
    assert strength.band == "adequate"
    assert strength.severity == Severity.INFO
    assert "Strength decided the orientation" in strength.message
    assert "marginal" in strength.message  # what it would have been as modelled


def test_the_customer_sees_a_band_not_a_number(l_bracket_mesh):
    strength = finding(run_review(l_bracket_mesh, req=bending()).geometry, "load_vs_layers")
    assert strength.measured is None and strength.threshold is None
    customer_text = " ".join([strength.message, strength.why, strength.fix])
    assert "SF" not in customer_text and "MPa" not in customer_text
    # The operator gets the number, flagged as provisional.
    assert "SF " in strength.operator_note
    assert "provisional" in strength.operator_note


def test_a_weak_orientation_is_a_must_fix_with_concrete_fixes(l_bracket_mesh):
    # Forced to print on its left side, the base plate stands across the layers.
    req = bending(magnitude_n=300)
    result = run_review(l_bracket_mesh, "pla", req=req, orientation_override="left")
    strength = finding(result.geometry, "load_vs_layers")
    assert strength.band == "weak"
    assert strength.severity == Severity.MUST_FIX
    assert "fillet" in strength.fix
    assert "operator" in strength.message
    # No stocked material bonds well enough to rescue this one, so none is suggested.
    assert "print it in" not in strength.fix


def test_a_better_bonding_material_is_offered_when_it_changes_the_band(l_bracket_mesh):
    # 240 N upright: weak in PLA, but marginal in a material that bonds better between layers.
    req = bending(magnitude_n=240)
    pla = finding(
        run_review(l_bracket_mesh, "pla", req=req, orientation_override="bottom").geometry,
        "load_vs_layers",
    )
    assert pla.band == "weak"
    assert "print it in" in pla.fix and "would be marginal" in pla.fix
    # A material already ruled out for this job is never offered.
    offered = pla.fix.split("print it in ")[1].split(",")[0]
    rejected = next(m.id for m in load_materials() if m.name == offered)
    again = finding(
        run_review(
            l_bracket_mesh,
            "pla",
            req=req,
            orientation_override="bottom",
            excluded_materials={rejected},
        ).geometry,
        "load_vs_layers",
    )
    assert offered not in again.fix


def test_interlayer_strength_comes_from_the_material_table(l_bracket_mesh):
    pla = finding(
        run_review(l_bracket_mesh, "pla", req=bending(), orientation_override="bottom").geometry,
        "load_vs_layers",
    )
    petg = finding(
        run_review(l_bracket_mesh, "petg", req=bending(), orientation_override="bottom").geometry,
        "load_vs_layers",
    )
    pla_sf = float(pla.operator_note.split("SF ")[1].split()[0])
    petg_sf = float(petg.operator_note.split("SF ")[1].split()[0])
    # PETG: 48 MPa x 0.78; PLA: 55 MPa x 0.55.
    assert petg_sf / pla_sf == pytest.approx((48 * 0.78) / (55 * 0.55), rel=0.01)


def test_a_stated_load_overrides_the_assumed_one():
    newtons, source = design_load(bending(magnitude_n=120), RULES)
    assert newtons == pytest.approx(120)
    assert "you gave" in source


def test_cyclic_loads_are_factored_up():
    req = Requirements(load=Load(type=LoadType.CYCLIC, qualitative="moderate"))
    newtons, _ = design_load(req, RULES)
    assert newtons == pytest.approx(50 * 1.5)


def test_compression_does_not_overrule_orientation(l_bracket_mesh):
    req = Requirements(load=Load(type=LoadType.COMPRESSION, qualitative="heavy"))
    result = run_review(l_bracket_mesh, req=req)
    assert finding(result.geometry, "load_vs_layers") is None
    assert result.face_down == run_review(l_bracket_mesh).face_down


def test_no_load_means_no_strength_finding(l_bracket_mesh):
    assert finding(run_review(l_bracket_mesh).geometry, "load_vs_layers") is None


def test_bands_follow_the_configured_thresholds():
    assert band(2.5, RULES) == "adequate"
    assert band(1.5, RULES) == "marginal"
    assert band(0.7, RULES) == "weak"


# --------------------------------------------------------------------------------------
# Holes
# --------------------------------------------------------------------------------------


def test_holes_are_found_with_their_size_and_direction(hole_plate_mesh):
    holes = find_holes(hole_plate_mesh, RULES)
    vertical = sorted(round(h.diameter_mm, 1) for h in holes if h.axis == 2)
    horizontal = sorted(round(h.diameter_mm, 1) for h in holes if h.axis != 2)
    assert vertical == pytest.approx([3.0, 4.0, 8.0], abs=0.2)
    assert horizontal == pytest.approx([3.0, 6.0], abs=0.2)


def test_small_vertical_holes_and_all_horizontal_ones_are_flagged(hole_plate_mesh):
    found = [f for f in run_review(hole_plate_mesh, "pla").geometry.findings if f.check == "holes"]
    upright = [f for f in found if "upright" in f.message]
    sideways = [f for f in found if "side" in f.message]
    assert sorted(round(f.measured) for f in upright) == [3, 4]  # 8 mm is big enough
    assert sorted(round(f.measured) for f in sideways) == [3, 6]
    assert all(f.severity == Severity.ADVISE for f in found)


def test_hole_fix_uses_the_materials_allowance(hole_plate_mesh):
    def three_mm(material):
        found = run_review(hole_plate_mesh, material).geometry.findings
        return next(f for f in found if f.check == "holes" and "upright" in f.message)

    assert "3.20 mm" in three_mm("pla").fix
    assert "3.40 mm" in three_mm("tpu_95a").fix


def test_hole_location_is_in_model_coordinates(hole_plate_mesh):
    found = run_review(hole_plate_mesh, "pla").geometry.findings
    three = next(
        f for f in found if f.check == "holes" and f.measured < 3.5 and "upright" in f.message
    )
    # The 3 mm vertical hole is at x = 12, y = 25 in the model.
    centre = [
        (a + b) / 2 for a, b in zip(three.location.bbox_min, three.location.bbox_max, strict=True)
    ]
    assert centre[0] == pytest.approx(12, abs=0.5)
    assert centre[1] == pytest.approx(25, abs=0.5)


def test_fit_critical_parts_are_told_we_will_ream(hole_plate_mesh):
    req = Requirements(precision=Precision(fit_critical=True))
    found = run_review(hole_plate_mesh, "pla", req=req).geometry.findings
    assert any("ream it" in f.why for f in found if f.check == "holes")


def test_a_plain_box_has_no_holes(box_stl: Path):
    assert find_holes(trimesh.load(box_stl), RULES) == []


def test_design_rules_hand_back_a_copy():
    design_rules()["max_triangles"] = 5
    design_rules(by_id("tpu_95a"))["holes"]["oversize_allowance_mm"] = 9
    assert design_rules()["max_triangles"] == 1_500_000
    assert design_rules(by_id("tpu_95a"))["holes"]["oversize_allowance_mm"] == 0.4


# --------------------------------------------------------------------------------------
# Found by seeding through the real endpoints
# --------------------------------------------------------------------------------------


def test_a_tube_is_not_balanced_on_its_side_to_save_layers():
    """The demo standoff was laid down because fewer layers looked quicker.

    Lying, a round part rests on a line and rolls, and its bore becomes a sagging horizontal
    hole. Its near-flat facets used to be counted as bed contact.
    """
    standoff = trimesh.creation.annulus(r_min=4, r_max=9, height=70, sections=64)
    result = run_review(standoff, "pla")
    assert result.face_down in ("bottom", "top")
    lying = next(c for c in result.geometry.orientation.candidates if c.face_down == "front")
    assert lying.bed_contact_mm2 < 100


def test_the_weak_point_is_at_the_root_not_the_free_tip(l_bracket_mesh):
    """The web is fixed by the base, so it fails where it meets the base, about 6 mm up."""
    strength = finding(
        run_review(l_bracket_mesh, req=bending(), orientation_override="bottom").geometry,
        "load_vs_layers",
    )
    assert strength.location.z_mm == pytest.approx(6.7, abs=1.0)


def test_overlapping_bodies_are_judged_as_the_profile_they_make(open_mesh_stl: Path):
    """The demo sign bracket is two overlapping boxes, not one solid.

    Cut as one mesh, the coincident faces closed into section loops that were not there and the
    part was never laid on its side. Cut body by body and merged, each layer is the true L.
    """
    result = run_review(trimesh.load(open_mesh_stl), req=bending())
    assert result.face_down in ("front", "back")
    assert finding(result.geometry, "load_vs_layers").band == "adequate"


def test_an_open_mesh_gets_no_strength_band(box_stl: Path):
    """A mesh with a hole in its surface has no true sections; say so rather than guess."""
    box = trimesh.load(box_stl)
    box.update_faces(np.arange(len(box.faces)) != 0)  # knock one triangle out
    result = run_review(box, req=bending())
    strength = finding(result.geometry, "load_vs_layers")
    assert strength.band is None
    assert strength.severity == Severity.ADVISE
    assert "could not check" in strength.message
    assert all(c.safety_factor is None for c in result.geometry.orientation.candidates)


def test_touching_bodies_are_judged_as_the_profile_they_make():
    """Two watertight bodies that only touch: each section is one L, not two rectangles."""
    profile_a = Polygon([(0, 0), (80, 0), (80, 6), (0, 6)])
    profile_b = Polygon([(0, 6), (6, 6), (6, 56), (0, 56)])
    halves = [trimesh.creation.extrude_polygon(p, 60) for p in (profile_a, profile_b)]
    bracket = trimesh.util.concatenate(halves)
    bracket.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    whole = run_review(l_bracket(), req=bending())
    split = run_review(bracket, req=bending())
    assert split.face_down == whole.face_down
    assert finding(split.geometry, "load_vs_layers").band == "adequate"


def test_strength_wording_when_both_ways_are_in_the_same_band(l_bracket_mesh):
    """TPU bonds well between layers, so under a moderate load upright is adequate too."""
    req = bending("moderate")
    strength = finding(run_review(l_bracket_mesh, "tpu_95a", req=req).geometry, "load_vs_layers")
    assert strength.band == "adequate"
    assert "still be adequate, but with far less margin" in strength.message
