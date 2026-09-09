#!/usr/bin/env python3
"""Compare the geometric estimator against a real slice, part by part.

The estimator exists so a quote can be produced without a slicer. This measures how much that
costs in accuracy, using the same parts and the same answers the demo seed uses, so the numbers
are the ones a real customer would have been quoted.

Run it after changing the estimator, or after changing slicer profiles:

    scripts/compare_slicing.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "worker" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from seed_demo import CASES, build_meshes  # noqa: E402
from worker.geometry import analyse  # noqa: E402
from worker.intake import apply_answers, heuristic_extract  # noqa: E402
from worker.materials import by_id  # noqa: E402
from worker.pricing import build_quote  # noqa: E402
from worker.selection import select_material  # noqa: E402
from worker.slicing import estimate, find_slicer, slice_mesh  # noqa: E402


def pct(guess: float, truth: float) -> str:
    if truth <= 0:
        return "n/a"
    delta = (guess - truth) / truth * 100
    return f"{delta:+.0f}%"


def main() -> None:
    binary = find_slicer()
    if binary is None:
        raise SystemExit(
            "No slicer binary found. Set SLICER_BIN or install one — there is nothing to "
            "compare against."
        )
    print(f"Slicer: {binary}\n")

    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        meshes = build_meshes(Path(tmp))

        for case in CASES:
            mesh = meshes[case["file"]]
            geometry = analyse(mesh)

            # Same path the customer takes: describe it, answer the follow-ups, get a material.
            intake = heuristic_extract(case["text"])
            requirements = apply_answers(intake.requirements, case["answers"])
            recommendation = select_material(requirements, geometry=geometry)
            if recommendation.declined:
                print(f"{case['file']}: declined — {recommendation.declined_reason}")
                continue

            material_id = case.get("override") or recommendation.primary.material_id
            material = by_id(material_id)
            settings = recommendation.print_settings

            guess = estimate(geometry, material, settings)
            real = slice_mesh(mesh, material, settings, geometry)
            if real.estimated:
                print(f"{case['file']}: slicer failed, skipping")
                continue

            quote_guess = build_quote(material, guess, geometry, requirements)
            quote_real = build_quote(material, real, geometry, requirements)

            rows.append({
                "part": case["file"].replace(".stl", ""),
                "material": material.name,
                "walls": settings["walls"],
                "infill": settings["infill_percent"],
                "volume_cm3": geometry.volume_mm3 / 1000,
                "overhang": geometry.overhang_fraction,
                "g_guess": guess.filament_g + guess.support_g,
                "g_real": real.filament_g + real.support_g,
                "min_guess": guess.print_minutes,
                "min_real": real.print_minutes,
                "price_guess": quote_guess.total_price,
                "price_real": quote_real.total_price,
                "qty": quote_real.quantity,
                "currency": quote_real.currency,
            })

    if not rows:
        raise SystemExit("Nothing to compare.")

    print(f"{'part':18s} {'material':10s} {'settings':11s}  "
          f"{'mass est':>9s} {'mass real':>9s} {'err':>6s}   "
          f"{'time est':>9s} {'time real':>9s} {'err':>6s}")
    print("-" * 108)
    for r in rows:
        settings = f"{r['walls']}w/{r['infill']}%"
        print(
            f"{r['part']:18s} {r['material']:10s} {settings:11s}  "
            f"{r['g_guess']:8.1f}g {r['g_real']:8.1f}g {pct(r['g_guess'], r['g_real']):>6s}   "
            f"{r['min_guess']:8.0f}m {r['min_real']:8.0f}m {pct(r['min_guess'], r['min_real']):>6s}"
        )

    print()
    print(f"{'part':18s} {'qty':>4s}  {'price est':>10s} {'price real':>11s} {'err':>6s}   "
          f"what the estimator missed")
    print("-" * 108)
    for r in rows:
        cur = r["currency"]
        print(
            f"{r['part']:18s} {r['qty']:4d}  {cur} {r['price_guess']:7.2f} {cur} {r['price_real']:8.2f} "
            f"{pct(r['price_guess'], r['price_real']):>6s}   "
            f"vol {r['volume_cm3']:.1f} cm3, overhang {r['overhang'] * 100:.0f}%"
        )


if __name__ == "__main__":
    main()
