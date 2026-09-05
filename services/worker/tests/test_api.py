"""End-to-end tests through the HTTP surface, using FastAPI's test client."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from worker.api import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTSHOP_UPLOAD_DIR", str(tmp_path / "uploads"))


def upload(path: Path):
    with path.open("rb") as fh:
        return client.post("/analyse", files={"file": (path.name, fh, "model/stl")})


# --------------------------------------------------------------------------------------
# Service info
# --------------------------------------------------------------------------------------


def test_health_reports_what_is_actually_wired_up():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["materials_table"]
    assert "slicer" in body and "intake_model" in body


def test_public_config_exposes_only_stocked_materials():
    body = client.get("/config").json()
    assert body["currency"]
    assert body["minimum_order"] > 0
    assert all("cost_per_kg" not in m for m in body["materials"]), "cost must not leak to customers"
    assert {m["id"] for m in body["materials"]} <= {
        "pla",
        "pla_tough",
        "petg",
        "asa",
        "tpu_95a",
        "pa6_cf",
    }


def test_materials_endpoint_carries_the_full_table_for_the_operator():
    body = client.get("/materials").json()
    assert body["version"]
    assert len(body["materials"]) >= 10
    assert all("cost_per_kg" in m for m in body["materials"])


# --------------------------------------------------------------------------------------
# Upload and analysis
# --------------------------------------------------------------------------------------


def test_upload_returns_geometry(box_stl: Path):
    response = upload(box_stl)
    assert response.status_code == 200
    body = response.json()
    assert body["upload_id"]
    assert body["geometry"]["bbox_mm"] == [40.0, 30.0, 20.0]
    assert body["geometry"]["is_watertight"] is True


def test_the_same_mesh_uploaded_twice_reuses_its_id(box_stl: Path):
    first = upload(box_stl).json()["upload_id"]
    second = upload(box_stl).json()["upload_id"]
    assert first == second


def test_unsupported_file_type_is_rejected_with_a_readable_message(tmp_path: Path):
    bad = tmp_path / "drawing.step"
    bad.write_bytes(b"not a mesh")
    with bad.open("rb") as fh:
        response = client.post("/analyse", files={"file": (bad.name, fh, "application/step")})
    assert response.status_code == 400
    assert ".stl" in response.json()["detail"]


def test_empty_file_is_rejected(tmp_path: Path):
    empty = tmp_path / "empty.stl"
    empty.write_bytes(b"")
    with empty.open("rb") as fh:
        response = client.post("/analyse", files={"file": (empty.name, fh, "model/stl")})
    assert response.status_code == 400


# --------------------------------------------------------------------------------------
# Intake
# --------------------------------------------------------------------------------------


def test_intake_parses_text_and_returns_follow_ups():
    response = client.post("/intake", json={"text": "A bracket for a shelf in my garden shed."})
    body = response.json()
    assert body["allowed"] is True
    assert body["requirements"]["environment"]["outdoor_uv"] is True
    assert body["follow_ups"]
    assert body["extracted_by"]


def test_intake_declines_prohibited_descriptions_without_quoting():
    response = client.post("/intake", json={"text": "A suppressor baffle for my rifle"})
    body = response.json()
    assert body["allowed"] is False
    assert body["declined_reason"]
    assert body["follow_ups"] == []


def test_answers_round_trip_and_shrink_the_question_list():
    first = client.post("/intake", json={"text": "A small part."}).json()
    answers = {q["field"]: q["options"][0]["value"] for q in first["follow_ups"]}
    second = client.post(
        "/intake/answers", json={"requirements": first["requirements"], "answers": answers}
    ).json()
    remaining = {q["field"] for q in second["follow_ups"]}
    assert not (remaining & set(answers))


# --------------------------------------------------------------------------------------
# Recommendation and quoting
# --------------------------------------------------------------------------------------


def test_recommend_returns_a_material_with_a_rationale():
    body = client.post(
        "/recommend",
        json={
            "requirements": {
                "lifecycle": "end_use",
                "environment": {"outdoor_uv": True},
                "load": {"type": "bending", "duration": "sustained"},
            }
        },
    ).json()
    assert body["primary"]["material_id"] == "asa"
    assert "anisotropic" in body["rationale"].lower()
    assert body["orientation_advice"]
    assert body["rejected"]


def test_full_quote_flow(box_stl: Path):
    upload_id = upload(box_stl).json()["upload_id"]
    body = client.post(
        "/quote",
        json={
            "upload_id": upload_id,
            "requirements": {"lifecycle": "prototype", "cost_sensitivity": "high", "quantity": 2},
        },
    ).json()
    assert body["quote"]["total_price"] > 0
    assert body["quote"]["currency"]
    assert body["quote"]["lines"]
    assert body["recommendation"]["primary"]["material_id"]
    assert body["overridden"] is False


def test_customer_override_is_honoured_and_recorded(box_stl: Path):
    upload_id = upload(box_stl).json()["upload_id"]
    body = client.post(
        "/quote",
        json={
            "upload_id": upload_id,
            "requirements": {"lifecycle": "prototype", "cost_sensitivity": "high"},
            "material_id": "pa6_cf",
        },
    ).json()
    assert body["overridden"] is True
    assert body["quote"]["material_id"] == "pa6_cf"
    assert "instead of our recommended" in body["override_acknowledgement"]
    # The recommendation we disagreed with is still attached to the order.
    assert body["recommendation"]["primary"]["material_id"] != "pa6_cf"


def test_declined_requirements_produce_no_quote(box_stl: Path):
    upload_id = upload(box_stl).json()["upload_id"]
    body = client.post(
        "/quote",
        json={
            "upload_id": upload_id,
            "requirements": {"precision": {"tolerance_mm": 0.02}},
        },
    ).json()
    assert body["quote"] is None
    assert body["recommendation"]["declined"] is True
    assert body["recommendation"]["declined_reason"]


def test_unknown_upload_is_a_404():
    response = client.post("/quote", json={"upload_id": "does-not-exist.stl", "requirements": {}})
    assert response.status_code == 404


def test_unknown_material_override_is_rejected(box_stl: Path):
    upload_id = upload(box_stl).json()["upload_id"]
    response = client.post(
        "/quote",
        json={"upload_id": upload_id, "requirements": {}, "material_id": "unobtainium"},
    )
    assert response.status_code == 400


def test_upload_id_cannot_escape_the_upload_directory():
    response = client.post("/quote", json={"upload_id": "../../../etc/passwd", "requirements": {}})
    assert response.status_code == 404
