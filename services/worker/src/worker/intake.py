"""Intake: customer prose to a structured requirements vector.

The one job here is translation. The model fills in a schema and nothing else — it does not
pick a material, does not quote, and does not see the property table. Selection stays in
selection.py where it is deterministic and auditable. See docs/material-selection.md section 1.

Two paths, and both always work:
  * With ANTHROPIC_API_KEY set, Claude does the extraction.
  * Without one — or if the call fails — a keyword extractor fills in what it can. It is
    obviously weaker, so it leans on the follow-up questions to cover the gaps.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from pydantic import BaseModel, Field

from .schemas import (
    Aesthetics,
    BrittlenessTolerance,
    CostSensitivity,
    Environment,
    LeadTime,
    Lifecycle,
    Load,
    LoadDuration,
    LoadType,
    Moisture,
    Precision,
    Requirements,
    Thermal,
)

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_TOKENS = 4000

SYSTEM_PROMPT = """\
You work intake for a 3D printing service. Your only job is to turn a customer's description \
of their part into a structured requirements record. You do not choose materials, quote prices, \
or give printing advice — a separate deterministic engine does that from the record you produce.

Rules:

1. Record only what the customer stated or clearly implied. Leave a field null when they did not \
address it. A null is useful — it becomes a follow-up question. A guess is not.
2. Draw reasonable physical inferences from context, and list each one in `assumptions` so the \
customer can correct it. Examples of fair inferences:
   - "goes in my car" / "on the dashboard" implies sunlight_hot_car = true (a parked car reaches \
70-80 C).
   - "outside", "in the garden", "on the roof" implies outdoor_uv = true.
   - "holds up a shelf" / "takes my weight" implies a sustained load in bending or compression.
   - "snaps together", "clips on" implies the part must flex without shattering.
   - "just checking it fits" implies lifecycle = fit_check.
3. Do not inflate requirements. If someone wants a desk toy, that is `cosmetic` with no load — \
not an end-use structural part. Over-specifying pushes them into an expensive material they do \
not need.
4. `summary` is one or two plain sentences the customer will be shown to confirm, in their own \
terms. No jargon, no material names.

Return the structured record only."""


class IntakeExtraction(BaseModel):
    """What the model fills in. Deliberately excludes anything it should not be deciding."""

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
    summary: str = Field(description="One or two plain sentences for the customer to confirm")
    assumptions: list[str] = Field(
        default_factory=list, description="Inferences drawn beyond what was stated outright"
    )

    def to_requirements(self, raw_text: str) -> Requirements:
        data = self.model_dump(exclude={"summary", "assumptions"})
        return Requirements(**data, raw_text=raw_text)


class IntakeResult(BaseModel):
    requirements: Requirements
    summary: str
    assumptions: list[str] = Field(default_factory=list)
    extracted_by: str = "heuristic"


# --------------------------------------------------------------------------------------
# Claude-backed extraction
# --------------------------------------------------------------------------------------


def _client() -> Any | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:  # pragma: no cover - dependency is declared, this is belt and braces
        return None
    return anthropic.Anthropic()


def extract(raw_text: str) -> IntakeResult:
    """Extract requirements from freeform text, falling back to keywords if the API is unavailable.

    Never raises. A failed extraction degrades to the heuristic path and the follow-up questions
    pick up the slack; it must not take the quote flow down with it.
    """
    client = _client()
    if client is None:
        return heuristic_extract(raw_text)

    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": raw_text}],
            output_format=IntakeExtraction,
        )
        if getattr(response, "stop_reason", None) == "refusal":
            log.warning("Intake extraction refused; falling back to heuristics")
            return heuristic_extract(raw_text)
        extraction = response.parsed_output
    except Exception:
        log.exception("Intake extraction failed; falling back to heuristics")
        return heuristic_extract(raw_text)

    return IntakeResult(
        requirements=extraction.to_requirements(raw_text),
        summary=extraction.summary,
        assumptions=extraction.assumptions,
        extracted_by=MODEL,
    )


# --------------------------------------------------------------------------------------
# Heuristic fallback
# --------------------------------------------------------------------------------------

_OUTDOOR = r"outdoor|outside|garden|roof|yard|weather|rain|sun|balcony|patio|fence|mailbox"
_CAR = r"\bcar\b|dashboard|vehicle|glovebox|glove box|windscreen|windshield|boot of"
_WATER = r"underwater|submerged|immersed|aquarium|pond|fish tank|in the water"
_SPLASH = r"splash|shower|bathroom|kitchen sink|washing|wet\b"
_LOAD_WORDS = {
    LoadType.IMPACT: r"impact|drop|dropped|hit|knock|smash|crash|shock",
    LoadType.CYCLIC: r"repeated|cycl|vibrat|back and forth|over and over|fatigue",
    LoadType.BENDING: r"bend|bracket|shelf|arm|lever|cantilever|overhang",
    LoadType.CLAMPING: r"clamp|bolt|screw|tighten|torque|fasten",
    LoadType.TENSION: r"pull|tension|hang|hanging|suspend",
    LoadType.COMPRESSION: r"compress|squash|press|weight on|stand on|foot",
}
_FIT_CRITICAL = (
    r"bearing|press[- ]?fit|interference fit|mates? with|mating|slots? into|slides? into|"
    r"snug|shaft|spindle|bushing|bush\b|axle|gear\b|thread(?:ed)?\b|tolerance|precise|"
    r"precision|line up|lines up|has to fit|must fit|exact"
)
_PROTOTYPE = r"prototype|proto\b|mock ?up|test fit|fit check|checking the fit|trial"
_END_USE = r"final|production|end use|end-use|customer|sell|selling|for good|permanent"
_COSMETIC = r"display|decorat|ornament|cosplay|prop\b|model\b|figurine|desk toy|show"


def _search(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def heuristic_extract(raw_text: str) -> IntakeResult:
    """Keyword extraction. A safety net, not a substitute for the model."""
    text = raw_text or ""
    assumptions: list[str] = []

    lifecycle = None
    if _search(_PROTOTYPE, text):
        lifecycle = Lifecycle.FIT_CHECK
    elif _search(_COSMETIC, text):
        lifecycle = Lifecycle.COSMETIC
    elif _search(_END_USE, text):
        lifecycle = Lifecycle.END_USE

    load_type = None
    for candidate, pattern in _LOAD_WORDS.items():
        if _search(pattern, text):
            load_type = candidate
            break

    duration = None
    if load_type is not None:
        if _search(r"permanent|always|constantly|all the time|holds|hold up|support", text):
            duration = LoadDuration.SUSTAINED
            assumptions.append("Assumed the load is applied continuously rather than briefly.")

    outdoor = _search(_OUTDOOR, text) or None
    if outdoor:
        assumptions.append("Assumed the part lives outdoors and needs UV resistance.")

    hot_car = _search(_CAR, text) or None
    if hot_car:
        assumptions.append("Assumed a parked car interior, which reaches 70-80 C in summer sun.")

    moisture = None
    if _search(_WATER, text):
        moisture = Moisture.IMMERSED
    elif _search(_SPLASH, text):
        moisture = Moisture.SPLASH

    max_temp = None
    temp_match = re.search(r"(\d{2,3})\s*(?:deg(?:rees)?\s*)?c(?:elsius)?\b", text, re.IGNORECASE)
    if temp_match:
        max_temp = float(temp_match.group(1))

    quantity = 1
    qty_match = re.search(
        r"\b(\d{1,4})\s*(?:off|pieces?|parts?|units?|copies|x)\b"
        r"|\b(?:need|want|make|print)\s+(\d{1,4})\b"
        r"|\b(\d{1,4})\s+of\s+(?:them|these|those)\b",
        text,
        re.I,
    )
    if qty_match:
        matched = next(g for g in qty_match.groups() if g)
        quantity = max(1, int(matched))

    # "bearing seat", "press fit", "mates with" all mean the dimension is the point of the
    # part. Without this the tolerance question ranks below the generic ones and gets cut.
    precision = Precision()
    if _search(_FIT_CRITICAL, text):
        precision = Precision(fit_critical=True)
        assumptions.append(
            "Assumed the fit matters dimensionally, because of how you described the part."
        )

    brittleness = None
    if _search(r"must not|can't break|cannot break|shatter|snap|brittle|flex|bend without", text):
        brittleness = BrittlenessTolerance.MUST_NOT_SHATTER

    cost = None
    if _search(r"cheap|budget|as cheap|low cost|inexpensive|tight budget", text):
        cost = CostSensitivity.HIGH
    elif _search(r"cost is no|money no object|whatever it takes|best possible", text):
        cost = CostSensitivity.LOW

    lead = LeadTime.STANDARD
    if _search(r"urgent|asap|rush|as soon as|tomorrow|by friday|deadline", text):
        lead = LeadTime.RUSH

    requirements = Requirements(
        lifecycle=lifecycle,
        load=Load(type=load_type, duration=duration),
        brittleness_tolerance=brittleness,
        thermal=Thermal(max_service_c=max_temp, sunlight_hot_car=hot_car),
        environment=Environment(outdoor_uv=outdoor, moisture=moisture),
        precision=precision,
        aesthetics=Aesthetics(),
        cost_sensitivity=cost,
        lead_time=lead,
        quantity=quantity,
        raw_text=raw_text,
    )
    return IntakeResult(
        requirements=requirements,
        summary=(
            "We read your description automatically. Please check the follow-up questions "
            "carefully — we could not parse as much detail as usual from your notes."
        ),
        assumptions=assumptions,
        extracted_by="heuristic",
    )


# --------------------------------------------------------------------------------------
# Adaptive follow-up questions
# --------------------------------------------------------------------------------------


class FollowUpOption(BaseModel):
    value: str
    label: str


class FollowUp(BaseModel):
    field: str
    question: str
    help_text: str | None = None
    options: list[FollowUpOption] = Field(default_factory=list)
    input_type: str = "choice"


MAX_FOLLOW_UPS = 5


def _opts(*pairs: tuple[str, str]) -> list[FollowUpOption]:
    return [FollowUpOption(value=v, label=label) for v, label in pairs]


def _catalogue(req: Requirements) -> list[tuple[float, FollowUp]]:
    """Candidate questions with an impact weight: how much the answer moves the decision."""
    structural = req.load.type not in (None, LoadType.NONE)
    candidates: list[tuple[float, FollowUp]] = []

    if req.lifecycle is None:
        candidates.append(
            (
                0.9,
                FollowUp(
                    field="lifecycle",
                    question="What stage is this part at?",
                    help_text=(
                        "A test fit and a part you'll rely on for years want different materials."
                    ),
                    options=_opts(
                        ("fit_check", "Just checking it fits"),
                        ("prototype", "An early prototype"),
                        ("functional_prototype", "A prototype that has to work properly"),
                        ("end_use", "The real thing, used for the long term"),
                        ("cosmetic", "For display or decoration"),
                    ),
                ),
            )
        )

    if req.load.type is None:
        candidates.append(
            (
                0.95,
                FollowUp(
                    field="load.type",
                    question="Does the part carry any load, and what kind?",
                    help_text="This is the single biggest factor in both material and orientation.",
                    options=_opts(
                        ("none", "Nothing — it just sits there"),
                        ("bending", "Something pushes or hangs on it sideways"),
                        ("compression", "Weight presses down on it"),
                        ("tension", "It gets pulled"),
                        ("impact", "It gets knocked or dropped"),
                        ("cyclic", "It flexes over and over"),
                        ("clamping", "It's bolted or clamped tight"),
                    ),
                ),
            )
        )

    if structural and req.load.duration is None:
        candidates.append(
            (
                0.8,
                FollowUp(
                    field="load.duration",
                    question="Is the load constant, or only now and then?",
                    help_text=(
                        "Plastics creep: a material that holds fine for an afternoon can sag over "
                        "months under the same load."
                    ),
                    options=_opts(
                        ("momentary", "Brief moments only"),
                        ("intermittent", "On and off"),
                        ("sustained", "Constantly, for as long as it's in service"),
                    ),
                ),
            )
        )

    if structural and req.load.qualitative is None and req.load.magnitude_n is None:
        candidates.append(
            (
                0.7,
                FollowUp(
                    field="load.qualitative",
                    question="Roughly how much load?",
                    help_text="A rough weight in kilograms is ideal if you know it.",
                    options=_opts(
                        ("light", "Light — a few hundred grams"),
                        ("moderate", "Moderate — a few kilograms"),
                        ("heavy", "Heavy — 20 kg or more"),
                    ),
                ),
            )
        )

    if req.effective_max_temp_c() is None:
        candidates.append(
            (
                0.85,
                FollowUp(
                    field="thermal.max_service_c",
                    question="How hot does the part get?",
                    help_text=(
                        "Worth checking: a parked car reaches 70-80 C in summer, which is "
                        "well past what PLA survives."
                    ),
                    options=_opts(
                        ("20", "Room temperature only"),
                        ("50", "Warm — near a heater or in the sun"),
                        ("70", "In a car, or in direct summer sun"),
                        ("100", "Near an engine, oven or boiling water"),
                        ("150", "Hotter than that"),
                    ),
                ),
            )
        )

    if req.environment.outdoor_uv is None:
        candidates.append(
            (
                0.75,
                FollowUp(
                    field="environment.outdoor_uv",
                    question="Will it live outdoors?",
                    help_text="UV breaks down most printing plastics within a season or two.",
                    options=_opts(
                        ("false", "Indoors"),
                        ("true", "Outdoors, in daylight"),
                    ),
                ),
            )
        )

    if req.brittleness_tolerance is None:
        candidates.append(
            (
                0.7,
                FollowUp(
                    field="brittleness_tolerance",
                    question="If it's overloaded, what should happen?",
                    help_text="Stiff materials are stronger but snap; tough ones bend first.",
                    options=_opts(
                        ("must_not_shatter", "It must bend or deform, never shatter"),
                        ("prefer_ductile", "I'd prefer it to bend first"),
                        ("indifferent", "No preference"),
                        ("stiffness_preferred", "I want it as stiff as possible"),
                    ),
                ),
            )
        )

    if req.precision.tolerance_class is None and req.precision.tolerance_mm is None:
        candidates.append(
            (
                0.6,
                FollowUp(
                    field="precision.tolerance_class",
                    question="How precisely does it need to be made?",
                    help_text=(
                        "Tighter than about 0.15 mm needs a different process, and we'll say so."
                    ),
                    options=_opts(
                        ("cosmetic", "Roughly right is fine"),
                        ("standard", "Normal — it should fit where it's meant to"),
                        ("tight", "Tight — it mates with other parts"),
                        ("press_fit", "Very tight — a press fit or bearing seat"),
                    ),
                ),
            )
        )

    if req.environment.moisture is None:
        candidates.append(
            (
                0.5,
                FollowUp(
                    field="environment.moisture",
                    question="Does it get wet?",
                    options=_opts(
                        ("dry", "No, it stays dry"),
                        ("humid", "Humid air"),
                        ("splash", "Occasional splashes"),
                        ("immersed", "Sits in water"),
                    ),
                ),
            )
        )

    if req.cost_sensitivity is None:
        candidates.append(
            (
                0.45,
                FollowUp(
                    field="cost_sensitivity",
                    question="How much does price matter here?",
                    options=_opts(
                        ("high", "Keep it as cheap as possible"),
                        ("medium", "Balance cost and quality"),
                        ("low", "Get it right, cost is secondary"),
                    ),
                ),
            )
        )

    if req.aesthetics.visible is None:
        candidates.append(
            (
                0.35,
                FollowUp(
                    field="aesthetics.visible",
                    question="Will the part be on show?",
                    options=_opts(
                        ("false", "Hidden inside something"),
                        ("true", "Visible — appearance matters"),
                    ),
                ),
            )
        )

    return candidates


# Words in the customer's own description that make a particular question far more worth
# asking. A static ranking asks a bearing-seat customer about UV before tolerance.
_CONTEXT_BOOSTS: tuple[tuple[str, str, float], ...] = (
    (_FIT_CRITICAL, "precision.tolerance_class", 0.5),
    (r"hot|heat|warm|engine|oven|boiler|radiator|steam|sun\b|summer", "thermal.max_service_c", 0.4),
    (_OUTDOOR, "environment.outdoor_uv", 0.4),
    (_WATER + "|" + _SPLASH, "environment.moisture", 0.4),
    (r"strong|strength|load|weight|hold|support|carry|force|stress", "load.type", 0.3),
    (r"break|snap|crack|shatter|brittle|flex|bend", "brittleness_tolerance", 0.3),
    (r"cheap|budget|cost|price|expensive|afford", "cost_sensitivity", 0.3),
    (r"looks?|colour|color|finish|show|display|visible|paint", "aesthetics.visible", 0.3),
)


# Questions that stop being worth the customer's attention once we know what the part is for.
# Asking someone printing a display piece how much load it carries wastes one of five slots.
_LIFECYCLE_DAMPING: dict[Lifecycle, tuple[tuple[str, float], ...]] = {
    Lifecycle.COSMETIC: (
        ("load.type", -0.6),
        ("load.duration", -0.6),
        ("load.qualitative", -0.6),
        ("brittleness_tolerance", -0.3),
        ("thermal.max_service_c", -0.4),
    ),
    Lifecycle.FIT_CHECK: (
        ("load.type", -0.5),
        ("load.duration", -0.5),
        ("load.qualitative", -0.5),
        ("thermal.max_service_c", -0.4),
        ("environment.outdoor_uv", -0.4),
        ("brittleness_tolerance", -0.3),
    ),
}


def _context_boosts(req: Requirements) -> dict[str, float]:
    """Weight adjustments from the customer's own wording and the stage the part is at."""
    boosts: dict[str, float] = {}

    text = req.raw_text or ""
    if text:
        for pattern, field, boost in _CONTEXT_BOOSTS:
            if _search(pattern, text):
                boosts[field] = boosts.get(field, 0.0) + boost

    for field, damping in _LIFECYCLE_DAMPING.get(req.lifecycle, ()):  # type: ignore[arg-type]
        boosts[field] = boosts.get(field, 0.0) + damping

    return boosts


def next_questions(req: Requirements, limit: int = MAX_FOLLOW_UPS) -> list[FollowUp]:
    """The unanswered questions that would most change the recommendation, highest impact first.

    Ranked by decision impact rather than schema order, nudged by what the customer actually
    wrote, and capped: an intake form that asks twelve questions gets abandoned, and the last
    seven rarely change the answer anyway.
    """
    boosts = _context_boosts(req)
    ranked = sorted(
        _catalogue(req),
        key=lambda item: item[0] + boosts.get(item[1].field, 0.0),
        reverse=True,
    )
    return [follow_up for _, follow_up in ranked[:limit]]


# --------------------------------------------------------------------------------------
# Applying answers
# --------------------------------------------------------------------------------------

_BOOL = {"true": True, "false": False, "yes": True, "no": False}


def apply_answers(req: Requirements, answers: dict[str, Any]) -> Requirements:
    """Fold follow-up answers back into the requirements, by dotted field path."""
    data = req.model_dump()
    for path, value in answers.items():
        if value is None or value == "":
            continue
        if isinstance(value, str) and value.lower() in _BOOL:
            value = _BOOL[value.lower()]
        target = data
        parts = path.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        leaf = parts[-1]
        # Numeric fields arrive as strings from an HTML form.
        if leaf in {
            "max_service_c",
            "min_service_c",
            "tolerance_mm",
            "min_feature_mm",
            "magnitude_n",
        }:
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
        elif leaf == "quantity":
            try:
                value = max(1, int(value))
            except (TypeError, ValueError):
                continue
        target[leaf] = value
    return Requirements(**data)
