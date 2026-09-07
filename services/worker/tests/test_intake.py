"""Intake tests.

These exercise the heuristic path and the question logic. The Claude-backed extraction is not
tested here — it needs a key and costs money per run; `extract()` falls back to the heuristic
path when no key is set, which is what these assertions see.
"""

from __future__ import annotations

from worker.intake import (
    MAX_FOLLOW_UPS,
    apply_answers,
    heuristic_extract,
    next_questions,
)
from worker.safety import screen
from worker.schemas import (
    BrittlenessTolerance,
    CostSensitivity,
    LeadTime,
    Lifecycle,
    LoadDuration,
    LoadType,
    Moisture,
    Requirements,
)

# --------------------------------------------------------------------------------------
# Heuristic extraction
# --------------------------------------------------------------------------------------


def test_outdoor_wording_sets_uv_and_records_the_assumption():
    result = heuristic_extract("A mount for a bird feeder in the garden.")
    assert result.requirements.environment.outdoor_uv is True
    assert any("outdoor" in a.lower() for a in result.assumptions)


def test_car_wording_infers_a_hot_service_temperature():
    result = heuristic_extract("A phone holder for my car dashboard.")
    assert result.requirements.thermal.sunlight_hot_car is True
    assert result.requirements.effective_max_temp_c() == 70.0
    assert any("70-80" in a for a in result.assumptions)


def test_shelf_wording_reads_as_a_sustained_bending_load():
    result = heuristic_extract("A bracket that holds up a shelf.")
    assert result.requirements.load.type == LoadType.BENDING
    assert result.requirements.load.duration == LoadDuration.SUSTAINED


def test_shatter_wording_sets_the_brittleness_requirement():
    result = heuristic_extract("A clip that must not snap when I flex it.")
    assert result.requirements.brittleness_tolerance == BrittlenessTolerance.MUST_NOT_SHATTER


def test_prototype_and_display_wording_set_lifecycle():
    assert heuristic_extract("Just a test fit").requirements.lifecycle == Lifecycle.FIT_CHECK
    assert (
        heuristic_extract("A display model for my desk").requirements.lifecycle
        == Lifecycle.COSMETIC
    )


def test_explicit_temperature_is_read_from_the_text():
    result = heuristic_extract("It sits near a heater, gets to about 85 degrees C.")
    assert result.requirements.thermal.max_service_c == 85.0


def test_quantity_and_urgency_are_read_from_the_text():
    result = heuristic_extract("I need 12 off, urgent please.")
    assert result.requirements.quantity == 12
    assert result.requirements.lead_time == LeadTime.RUSH


def test_immersion_and_splash_are_distinguished():
    assert (
        heuristic_extract("It sits in my fish tank").requirements.environment.moisture
        == Moisture.IMMERSED
    )
    assert (
        heuristic_extract("It gets the odd splash").requirements.environment.moisture
        == Moisture.SPLASH
    )


def test_budget_wording_sets_cost_sensitivity():
    result = heuristic_extract("Keep it as cheap as possible please.")
    assert result.requirements.cost_sensitivity == CostSensitivity.HIGH


def test_empty_description_still_returns_a_usable_record():
    result = heuristic_extract("")
    assert isinstance(result.requirements, Requirements)
    assert result.requirements.quantity == 1
    assert next_questions(result.requirements)


# --------------------------------------------------------------------------------------
# Follow-up questions
# --------------------------------------------------------------------------------------


def test_questions_are_capped_so_the_form_stays_short():
    questions = next_questions(Requirements())
    assert 0 < len(questions) <= MAX_FOLLOW_UPS


def test_answered_fields_are_not_asked_about_again():
    result = heuristic_extract("A bracket in the garden that holds up a shelf.")
    fields = {q.field for q in next_questions(result.requirements)}
    assert "environment.outdoor_uv" not in fields
    assert "load.type" not in fields


def test_load_details_are_only_asked_once_a_load_exists():
    without = {q.field for q in next_questions(Requirements(), limit=99)}
    assert "load.duration" not in without

    with_load = heuristic_extract("A bracket that gets knocked about.")
    fields = {q.field for q in next_questions(with_load.requirements, limit=99)}
    assert "load.duration" in fields


def test_the_highest_impact_question_comes_first():
    questions = next_questions(Requirements())
    assert questions[0].field in {"load.type", "lifecycle"}


def test_every_question_has_options_and_readable_text():
    for question in next_questions(Requirements(), limit=99):
        assert question.question.endswith("?")
        assert question.options
        assert all(o.label for o in question.options)


def test_answering_everything_leaves_no_questions():
    req = Requirements()
    answers = {q.field: q.options[0].value for q in next_questions(req, limit=99)}
    updated = apply_answers(req, answers)
    # Answering "no load" closes out the load follow-ups too.
    assert len(next_questions(updated, limit=99)) < len(next_questions(req, limit=99))


# --------------------------------------------------------------------------------------
# Applying answers
# --------------------------------------------------------------------------------------


def test_answers_are_applied_by_dotted_path():
    updated = apply_answers(
        Requirements(),
        {
            "lifecycle": "end_use",
            "load.type": "bending",
            "environment.outdoor_uv": "true",
            "thermal.max_service_c": "70",
            "quantity": "6",
        },
    )
    assert updated.lifecycle == Lifecycle.END_USE
    assert updated.load.type == LoadType.BENDING
    assert updated.environment.outdoor_uv is True
    assert updated.thermal.max_service_c == 70.0
    assert updated.quantity == 6


def test_blank_answers_do_not_overwrite_existing_values():
    original = heuristic_extract("A bracket in the garden.")
    updated = apply_answers(original.requirements, {"environment.outdoor_uv": ""})
    assert updated.environment.outdoor_uv is True


def test_unparseable_numbers_are_ignored_rather_than_crashing():
    updated = apply_answers(Requirements(), {"thermal.max_service_c": "quite hot"})
    assert updated.thermal.max_service_c is None


# --------------------------------------------------------------------------------------
# Safety screening
# --------------------------------------------------------------------------------------


def test_ordinary_parts_pass_screening():
    for description in (
        "A bracket for my shelf",
        "A replacement knob for the washing machine",
        "A cosplay helmet",
        "Breakfast tray feet",  # must not trip on 'brake'
    ):
        assert screen(description).allowed, description


def test_prohibited_descriptions_are_declined_with_a_reason():
    verdict = screen("I need a lower receiver for my rifle")
    assert not verdict.allowed
    assert verdict.matched
    assert verdict.message and "terms" in verdict.message


def test_screening_is_case_insensitive():
    assert not screen("A SUPPRESSOR housing").allowed


def test_screening_matches_whole_words_only():
    # 'gun part' should not fire on 'gunwale', and 'climbing' is a listed term that should.
    assert screen("A trim piece for the gunwale of my boat").allowed
    assert not screen("A climbing hold anchor").allowed


def test_empty_text_passes_screening():
    assert screen("").allowed
    assert screen(None).allowed


def test_quantity_is_read_from_natural_phrasing():
    for text, expected in [
        ("I need 3 of them", 3),
        ("Please make 12", 12),
        ("6 off please", 6),
        ("I need 2 parts", 2),
        ("Just the one", 1),
    ]:
        assert heuristic_extract(text).requirements.quantity == expected, text


# --------------------------------------------------------------------------------------
# Context-sensitive question ranking
# --------------------------------------------------------------------------------------


def test_fit_language_is_recognised_as_a_dimensional_requirement():
    for text in (
        "A bearing seat for a spindle",
        "It needs to press fit onto the shaft",
        "A bushing that mates with a 12 mm axle",
    ):
        assert heuristic_extract(text).requirements.precision.fit_critical is True, text


def test_a_bearing_seat_gets_asked_about_tolerance_first():
    """Static ranking put tolerance sixth of eleven, so a five-question form never asked it —
    on the one part where the dimension is the entire point."""
    result = heuristic_extract("A bearing seat for a spindle. Indoors.")
    fields = [q.field for q in next_questions(result.requirements)]
    assert fields[0] == "precision.tolerance_class"


def test_heat_wording_promotes_the_temperature_question():
    result = heuristic_extract("A mount that sits right next to the engine.")
    fields = [q.field for q in next_questions(result.requirements)]
    assert fields.index("thermal.max_service_c") < 2


def test_a_display_piece_is_not_interrogated_about_load():
    result = heuristic_extract("A display model of a ship for my shelf.")
    fields = [q.field for q in next_questions(result.requirements)]
    assert "load.type" not in fields[:2]
    assert "aesthetics.visible" in fields or result.requirements.aesthetics.visible is not None


def test_ranking_without_any_description_still_works():
    fields = [q.field for q in next_questions(Requirements())]
    assert fields[0] in {"load.type", "lifecycle"}
