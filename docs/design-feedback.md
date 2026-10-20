# Design feedback

A printability layer in the worker. It is not a DFM pass. FDM tolerates most geometry, and the
slicer already handles support and drops features it cannot print. This catches the few
things that make a functional printed part fail or disappoint, and ties them to the material
the engine has just recommended.

Every check produces a `DesignFinding`: what is wrong, where it is, how far off it is, why it
matters and what to change. Severity is `info`, `advise` or `must_fix`. A `must_fix` sends
the quote to manual review. It does not decline the job; declining stays with the selection
engine. `GeometryReport.warnings` is still filled, from the findings' one-line messages, so
anything that read the old warnings keeps working.

## Two passes

| When | Code | What it knows | Checks |
| --- | --- | --- | --- |
| Upload (`/analyse`) | `findings.py` via `geometry.py` | the mesh only | build volume, units, thin walls, overhang, aspect ratio, triangle count, mesh integrity |
| Quote (`/quote`) | `design.py` | the material and the requirements | the same checks with the material's thresholds, in the print orientation, plus orientation, load across layers and holes |

The quote page shows the quote-time set. It replaces the upload-time set rather than adding to
it, so nothing appears twice (see section 2.5 of [CASE_STUDY.md](../CASE_STUDY.md)).

## Orientation

The six axis-aligned faces-down are each scored on support volume, bed contact, height and a
relative print-time proxy. The time proxy only ranks orientations of the same part against
each other: the estimator's per-layer cost is not trustworthy in absolute terms
([slicing.md](slicing.md)). The candidates are then filtered in this order:

1. **Strength**, for load types that pull layers apart (tension, bending, shear, impact,
   cyclic). The strongest orientation wins unless another is within `strength_margin` of it.
2. **The cosmetic face**, if the customer named one (`aesthetics.cosmetic_face`). Orientations
   that put support on it are dropped. If only weaker orientations keep it clean, strength
   wins and the finding says so.
3. **Stability.** Orientations with less than `min_bed_contact_mm2` flat on the plate are
   passed over when a stable one exists. Contact counts faces that are genuinely flat on the
   bed, so a round part balanced on its side does not qualify.

The chosen face travels in `print_settings["orientation"]`. The quote slice, the risk buffer
and the approved artifact all use it, so the price is for the print that will run. The
operator can override it from the admin order page. That re-quotes the job, and if the price
moves the page shows the difference from what the customer paid.

## Load across the layers

We do not know which way the load pushes; the requirements record its type, size and
duration, not its direction. The check is therefore a proxy, and the finding says so.

- It assumes a sideways load at the far end of the part, as on a bracket.
- For each build axis it cuts the part into layers and finds the weakest layer interface: the
  largest (lever) / (section modulus).
- The far end is taken to be the slighter end, as a bracket's web is slighter than its base,
  so the weak point lands at the root.
- The safety factor is `tensile_mpa x z_strength_ratio` over the bending stress. The load is
  the customer's number if they gave one, otherwise an assumed figure for light, moderate or
  heavy, times a dynamic factor for impact and cyclic loads.

**Customers see a band** (adequate, marginal or weak) and the fix. The numeric safety factor is
on the admin page only, in `operator_note` and the orientation table: `z_strength_ratio` is
provisional, so the number would look more precise than it is. The storefront strips both
fields before anything reaches a browser (`apps/web/src/lib/findings.ts`).

Multi-body meshes, such as a CAD export of overlapping solids, are cut one body at a time and
merged layer by layer. Cut as one mesh, their coincident faces close into section loops that
are not there. A mesh with an open body gets no band at all: an `advise` finding says the
strength was not checked and the operator checks it by eye.

## Holes

Round holes are found as near-circular inner rings in cross-sections along each axis, in the
print orientation.

- Upright holes under `vertical_undersize_below_mm` print undersize. The fix gives the
  diameter to model, using the material's `oversize_allowance_mm`, or says to drill or ream.
- Holes printed on their side go oval and sag at the top. The fix suggests a teardrop top or
  reaming to size.

## Thresholds

All of them are in `data/materials.yaml` under `process_defaults.fdm_04_nozzle.design`, each
with a comment saying where the number comes from. A material can override any of them with
its own `design:` block. TPU, PETG, PA12 and PA6-CF do, for wall thickness, overhang angle and
hole allowances. Most of the numbers are shop rules of thumb, not datasheet values, and are
marked as such. The `risk_score()` weights stay in code: they are pricing weights, not design
thresholds.

## Verified against

- `services/worker/tests/test_design.py`: each check, the orientation rules, the material
  overrides, and regressions for what the demo seed exposed.
- `scripts/seed_demo.py`: two parts added, run through the real endpoints with real slices.
  - `hole-plate.stl`: upright holes of 3, 4 and 8 mm, and 3 and 6 mm holes through the side.
  - `l-bracket.stl`: a clean solid modelled upright, so it is weak across its layers as
    modelled.

The first seed run against real slices caught three faults the unit tests had not:

1. The standoff was laid on its side. Its faceted cylinder's near-flat facets counted as bed
   contact, and fewer layers looked quicker.
2. The sign bracket's weak point was reported at its free tip rather than its root.
3. The sign bracket, two overlapping boxes, was never laid on its side for strength: its
   sections came back as separate rectangles.

Each now has a regression test.
