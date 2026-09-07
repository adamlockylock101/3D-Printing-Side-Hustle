"""HTTP surface for the worker.

The Next.js app owns customers, orders and payments; this service owns everything that touches
a mesh or the material table. Keeping the split clean means the storefront never needs trimesh
and the engine never needs to know what an order is.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import storage
from .config import reload_config, shop_config
from .geometry import UnsupportedMesh, analyse
from .intake import FollowUp, IntakeResult, apply_answers, extract, next_questions
from .materials import by_id, load_materials, table_version
from .pricing import build_quote
from .safety import screen
from .schemas import GeometryReport, Quote, Recommendation, Requirements
from .selection import select_material
from .slicing import SlicerUnavailable, find_slicer, produce_artifact, slice_mesh

log = logging.getLogger(__name__)

# Large enough to mean "no cap" for a catalogue of about a dozen questions.
UNCAPPED = 999

app = FastAPI(
    title="Print shop worker",
    version="0.1.0",
    description="Geometry analysis, material selection, slicing and quoting.",
)


# --------------------------------------------------------------------------------------
# Request and response bodies
# --------------------------------------------------------------------------------------


class AnalyseResponse(BaseModel):
    upload_id: str
    filename: str
    geometry: GeometryReport


class IntakeRequest(BaseModel):
    text: str = Field(description="The customer's own description of what the part is for")


class IntakeResponse(BaseModel):
    requirements: Requirements
    summary: str
    assumptions: list[str]
    extracted_by: str
    follow_ups: list[FollowUp]
    allowed: bool = True
    declined_reason: str | None = None


class AnswersRequest(BaseModel):
    requirements: Requirements
    answers: dict[str, object] = Field(default_factory=dict)


class AnswersResponse(BaseModel):
    requirements: Requirements
    follow_ups: list[FollowUp]
    newly_relevant: list[FollowUp] = Field(
        default_factory=list,
        description=(
            "Questions that only became applicable because of the answers just given — asking "
            "about load duration once we know there is a load, say. These are worth a second "
            "round; the rest of follow_ups is just the lower-priority tail and asking it turns "
            "a short form into a long one."
        ),
    )


class RecommendRequest(BaseModel):
    requirements: Requirements
    geometry: GeometryReport | None = None


class QuoteRequest(BaseModel):
    upload_id: str
    requirements: Requirements
    material_id: str | None = Field(
        default=None, description="Override the recommendation. Logged as a customer override."
    )


class SliceRequest(BaseModel):
    upload_id: str
    material_id: str
    settings: dict[str, object] = Field(default_factory=dict)
    job_ref: str = Field(default="job", description="Used to name the produced file")


class QuoteResponse(BaseModel):
    recommendation: Recommendation
    quote: Quote | None = None
    geometry: GeometryReport
    overridden: bool = False
    override_acknowledgement: str | None = None


# --------------------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "materials_table": table_version(),
        "slicer": find_slicer() or "estimator only",
        "intake_model": "claude" if os.environ.get("ANTHROPIC_API_KEY") else "heuristic",
    }


@app.get("/config")
def public_config() -> dict[str, object]:
    """The subset of shop config the storefront may show a customer."""
    cfg = shop_config()
    return {
        "currency": cfg["currency"],
        "minimum_order": cfg["commerce"]["minimum_order"],
        "quote_valid_hours": cfg["commerce"]["quote_valid_hours"],
        "rush_multipliers": cfg["pricing"]["rush_multipliers"],
        "shipping": cfg["shipping"],
        "materials": [
            {"id": m.id, "name": m.name, "colours": list(m.colours)}
            for m in load_materials()
            if m.in_stock
        ],
    }


@app.get("/materials")
def materials() -> dict[str, object]:
    """Full property table, for the operator screen."""
    return {
        "version": table_version(),
        "materials": [
            {
                "id": m.id,
                "name": m.name,
                "process": m.process,
                "tensile_mpa": m.tensile_mpa,
                "elongation_pct": m.elongation_pct,
                "hdt_045_c": m.hdt_045_c,
                "z_strength_ratio": m.z_strength_ratio,
                "uv_resistance": m.uv_resistance,
                "cost_per_kg": m.cost_per_kg,
                "in_stock": m.in_stock,
                "colours": list(m.colours),
                "notes": m.notes,
            }
            for m in load_materials()
        ],
    }


@app.post("/analyse", response_model=AnalyseResponse)
async def analyse_upload(file: UploadFile = File(...)) -> AnalyseResponse:
    data = await file.read()
    try:
        upload_id, path = storage.store(file.filename or "part.stl", data)
    except storage.UploadRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        report = analyse(path)
    except UnsupportedMesh as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("Mesh analysis failed for %s", upload_id)
        raise HTTPException(
            status_code=400,
            detail="We could not read that mesh. It may be corrupt or empty.",
        ) from exc

    return AnalyseResponse(
        upload_id=upload_id, filename=file.filename or "part.stl", geometry=report
    )


@app.post("/intake", response_model=IntakeResponse)
def intake(body: IntakeRequest) -> IntakeResponse:
    verdict = screen(body.text)
    if not verdict.allowed:
        return IntakeResponse(
            requirements=Requirements(raw_text=body.text),
            summary="",
            assumptions=[],
            extracted_by="screening",
            follow_ups=[],
            allowed=False,
            declined_reason=verdict.message,
        )

    result: IntakeResult = extract(body.text)
    return IntakeResponse(
        requirements=result.requirements,
        summary=result.summary,
        assumptions=result.assumptions,
        extracted_by=result.extracted_by,
        follow_ups=next_questions(result.requirements),
    )


@app.post("/intake/answers", response_model=AnswersResponse)
def intake_answers(body: AnswersRequest) -> AnswersResponse:
    # Which questions applied before the answers, ignoring the display cap, so that "newly
    # relevant" means genuinely unlocked rather than merely promoted up the list.
    applicable_before = {q.field for q in next_questions(body.requirements, limit=UNCAPPED)}

    updated = apply_answers(body.requirements, body.answers)
    applicable_after = next_questions(updated, limit=UNCAPPED)

    return AnswersResponse(
        requirements=updated,
        follow_ups=next_questions(updated),
        newly_relevant=[q for q in applicable_after if q.field not in applicable_before],
    )


@app.post("/recommend", response_model=Recommendation)
def recommend(body: RecommendRequest) -> Recommendation:
    return select_material(body.requirements, geometry=body.geometry)


@app.post("/quote", response_model=QuoteResponse)
def quote(body: QuoteRequest) -> QuoteResponse:
    try:
        path = storage.resolve(body.upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="That upload has expired or was never stored."
        ) from exc

    geometry = analyse(path)
    recommendation = select_material(body.requirements, geometry=geometry)

    if recommendation.declined:
        return QuoteResponse(recommendation=recommendation, quote=None, geometry=geometry)

    material_id = body.material_id or recommendation.primary.material_id
    material = by_id(material_id)
    if material is None:
        raise HTTPException(status_code=400, detail=f"Unknown material {material_id!r}")

    overridden = (
        body.material_id is not None and body.material_id != recommendation.primary.material_id
    )
    acknowledgement = None
    if overridden:
        # The customer is allowed to overrule us, but the record has to show that they did and
        # what they were told. See docs/open-questions.md Q16.
        acknowledgement = (
            f"You have chosen {material.name} instead of our recommended "
            f"{recommendation.primary.name}. We will print it in {material.name} as asked. "
            "Our recommendation and the reasons for it are attached to this order."
        )

    sliced = slice_mesh(path, material, recommendation.print_settings, geometry)
    built = build_quote(material, sliced, geometry, body.requirements)

    return QuoteResponse(
        recommendation=recommendation,
        quote=built,
        geometry=geometry,
        overridden=overridden,
        override_acknowledgement=acknowledgement,
    )


@app.post("/slice")
def slice_for_print(body: SliceRequest) -> FileResponse:
    """Produce the real .3mf for an approved job.

    Deliberately strict: an approved job needs a file the printer can run, so a missing or
    failing slicer is an error here rather than a silent fall back to an estimate.
    """
    try:
        path = storage.resolve(body.upload_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="That upload has expired or was never stored."
        ) from exc

    material = by_id(body.material_id)
    if material is None:
        raise HTTPException(status_code=400, detail=f"Unknown material {body.material_id!r}")

    safe_ref = "".join(c for c in body.job_ref if c.isalnum() or c in "-_")[:48] or "job"
    destination = storage.upload_dir() / "artifacts" / f"{safe_ref}-{material.id}.3mf"

    try:
        produce_artifact(path, material, body.settings, destination)
    except SlicerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return FileResponse(
        destination, media_type="model/3mf", filename=f"{safe_ref}-{material.id}.3mf"
    )


@app.post("/admin/reload-config")
def admin_reload_config() -> dict[str, str]:
    """Pick up edits to shop.yaml or materials.yaml without a restart."""
    reload_config()
    return {"status": "reloaded", "materials_table": table_version()}
