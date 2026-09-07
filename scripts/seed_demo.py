#!/usr/bin/env python3
"""Seed a development database by driving the real customer flow over HTTP.

Nothing here is fabricated: every geometry report, recommendation and price comes out of the
running services exactly as a customer would receive it. That matters — seed data written
directly into the database hides precisely the bugs seeding is supposed to expose.

Usage: scripts/devstack.sh seed
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from pathlib import Path

WEB = os.environ.get("NEXT_PUBLIC_SITE_URL", "http://localhost:3000")


def post(path: str, body: dict) -> dict:
    request = urllib.request.Request(
        WEB + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def upload(path: Path) -> dict:
    boundary = "----seed-boundary"
    payload = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: model/stl\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        WEB + "/api/analyse",
        data=payload,
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def build_meshes(into: Path) -> dict[str, Path]:
    import trimesh

    def write(name: str, mesh) -> Path:
        target = into / name
        mesh.export(target)
        return target

    plate = trimesh.creation.box(extents=(80, 60, 6))
    plate.apply_translation((0, 0, 3))
    web = trimesh.creation.box(extents=(6, 60, 50))
    web.apply_translation((-37, 0, 31))

    return {
        "sign-bracket.stl": write("sign-bracket.stl", trimesh.util.concatenate([plate, web])),
        "enclosure-lid.stl": write("enclosure-lid.stl", trimesh.creation.box(extents=(140, 90, 3))),
        "standoff.stl": write(
            "standoff.stl", trimesh.creation.annulus(r_min=4, r_max=9, height=70, sections=64)
        ),
        "gear-blank.stl": write(
            "gear-blank.stl", trimesh.creation.cylinder(radius=22, height=8, sections=96)
        ),
    }


CASES = [
    {
        "file": "sign-bracket.stl",
        "text": "A bracket to hold a 5 kg shop sign on an outside wall. It stays up all year in "
                "the sun and rain. It must not snap if someone knocks it. I need 3 of them.",
        "answers": {
            "lifecycle": "end_use", "thermal.max_service_c": "70", "load.duration": "sustained",
            "load.qualitative": "moderate", "precision.tolerance_class": "standard",
            "environment.moisture": "splash", "cost_sensitivity": "medium",
        },
        "email": "jo.mercer@example.com", "person": "Jo Mercer",
        "notes": "Black if you have it. Needed before the shop reopens on the 20th.",
    },
    {
        "file": "enclosure-lid.stl",
        "text": "Lid for a project box that sits on my desk. Just checking the cutouts line up "
                "before I commit to the real thing. Cheap as possible.",
        "answers": {
            "lifecycle": "fit_check", "load.type": "none", "cost_sensitivity": "high",
            "aesthetics.visible": "false", "precision.tolerance_class": "standard",
        },
        "email": "sam.okafor@example.com", "person": "Sam Okafor", "notes": "",
    },
    {
        # Deliberately overrides the recommendation, so the operator queue has an override to show.
        "file": "standoff.stl",
        "text": "Standoffs for a motor mount. They get bolted down tight and there's constant "
                "vibration. Needs 8 of them, fairly urgent.",
        "answers": {
            "lifecycle": "end_use", "load.type": "clamping", "load.duration": "sustained",
            "load.qualitative": "heavy", "thermal.max_service_c": "50",
            "precision.tolerance_class": "tight",
        },
        "email": "rita.venn@example.com", "person": "Rita Venn",
        "notes": "Vibration is the main worry — last set worked loose.",
        "override": "pla",
    },
    {
        "file": "gear-blank.stl",
        "text": "A gear blank for a hobby clock. It turns constantly and needs to mesh properly. "
                "Indoors, room temperature.",
        "answers": {
            "lifecycle": "end_use", "load.type": "cyclic", "load.duration": "sustained",
            "load.qualitative": "light", "precision.tolerance_class": "tight",
            "aesthetics.visible": "true",
        },
        "email": "dan.whitlock@example.com", "person": "Dan Whitlock", "notes": "",
    },
]


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        meshes = build_meshes(Path(tmp))
        for case in CASES:
            analysis = upload(meshes[case["file"]])
            intake = post("/api/intake", {"text": case["text"]})
            applied = post(
                "/api/intake/answers",
                {"requirements": intake["requirements"], "answers": case["answers"]},
            )
            quote_body = {
                "uploadId": analysis["upload_id"],
                "filename": case["file"],
                "bytes": meshes[case["file"]].stat().st_size,
                "requirements": applied["requirements"],
            }
            if case.get("override"):
                quote_body["materialId"] = case["override"]
            quote = post("/api/quote", quote_body)

            if not quote.get("quoteId"):
                reason = quote.get("recommendation", {}).get("declined_reason", "no quote")
                print(f"{case['file']:22s} -> DECLINED: {reason}")
                continue

            order = post(
                "/api/checkout",
                {
                    "quoteId": quote["quoteId"], "email": case["email"],
                    "name": case["person"], "notes": case["notes"],
                },
            )
            print(
                f"{case['file']:22s} -> {quote['quote']['material_name']:8s} "
                f"{quote['quote']['total_price']:>8.2f}  "
                f"(recommended {quote['recommendation']['primary']['name']})  "
                f"/orders/{order['orderToken']}"
            )

    print(
        "\nOrders are in AWAITING_PAYMENT because Stripe is not configured here. "
        "Mark them paid the way the webhook does:\n"
        "  psql -h 127.0.0.1 -p 5433 -U printshop -d printshop "
        "-c \"update \\\"Order\\\" set status='IN_REVIEW' where status='AWAITING_PAYMENT'\""
    )


if __name__ == "__main__":
    main()
