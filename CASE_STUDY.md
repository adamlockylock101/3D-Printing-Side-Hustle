# Case study: building and debugging this with AI

This service was built end to end in a Claude Code session — plan, worker, storefront, operator
queue, real slicing. What follows is not a summary of what was built; the README covers that.
It is an account of what went wrong, how each fault was found, and what the numbers were.

The short version: **a green test suite said almost nothing about whether the product worked.**
Every defect below was found by running the thing — driving it in a browser, seeding it through
its own endpoints, reading the G-code it emitted — and not one by testing units of it.

---

## 1. 109 passing tests, and a checkout flow nobody could complete

At commit `bb8e8ca` the worker suite stood at **109 tests, all passing**. Coverage was real, not
decorative: hard filters, weighting, declining, pricing arithmetic, geometry warnings, safety
screening, quote persistence, HTTP contracts.

The checkout flow did not work. A customer could not get from a file to a paid order.

Every test asked "does this function answer correctly given these inputs?" None asked "can a
person get through this?" Those are different questions, and only the second one is the product.

### Seeding by driving the real endpoints

The obvious way to populate a demo database is to insert rows. That was rejected in favour of
`scripts/seed_demo.py`, which drives the actual HTTP endpoints — upload the mesh to
`/api/analyse`, post the description to `/api/intake`, apply answers, request a quote, check
out — and lets the running services produce every geometry report, recommendation and price.

It costs more to write and runs slower. It also found three of the five bugs in section 2.
Inserting rows directly would have produced a demo database that looked perfect while the code
that fills it was broken, because the failure was in the *sequence* of calls, not in any one of
them.

Same reasoning applies to the browser. `scripts/devstack.sh` brings up Postgres, the worker and
the storefront in one command specifically so that walking the flow is cheap enough to do often.

---

## 2. Five faults, found by using it

### 2.1 A quote form that never terminated

**Symptom.** Driving the flow in a browser: upload, describe the part, answer five questions,
click "See the recommendation" — and get five *more* questions. Then more. The only escape was
the "Skip the rest" button.

**Cause.** The worker is stateless. `next_questions()` returns the highest-impact unanswered
questions each time it is called, capped at `MAX_FOLLOW_UPS = 5`. The client's termination check
was:

```js
if (data.follow_ups.length && data.follow_ups.some((q) => !(q.field in answers))) {
```

The questions coming back were by definition ones the customer had just *not* been asked, so the
condition was always true. The form paginated through the whole catalogue of eleven candidate
questions, five at a time.

**Fix.** A counter would have capped the symptom while leaving the client unable to tell a
genuinely new question from a lower-priority one. Instead the worker now answers that question
directly: `/intake/answers` computes the applicable question set before and after applying the
answers, ignoring the display cap, and returns `newly_relevant` — the questions the answers
actually unlocked. Asking about load duration only makes sense once we know there is a load.
The client shows one round plus at most one short follow-on (`MAX_QUESTION_ROUNDS = 2`).

### 2.2 A clock gear recommended in TPU 95A

**Symptom.** Seeding a "gear blank for a hobby clock — it turns constantly and needs to mesh
properly" returned **TPU 95A**, a flexible filament, for a part whose entire purpose is holding
a dimension.

**Cause.** This was not a bug in the code; the code did exactly what it was told. Cyclic loading
raises the toughness weight by 0.25, and toughness is scored from elongation at break and
notched impact. TPU has 500% elongation and does not break in notched Izod at all, so it scored
maximally on the dimension the requirements had made dominant.

Nothing pushed back. The `precision` scoring dimension is built from warp rank and process
capability — and TPU is *low-warp* and prints at the same `process_capability_mm` as every other
FDM material. On the axis that should have eliminated it, TPU looked identical to PETG.

**Fix.** No weighting change could fix this, because the scoring inputs contained no signal
about elastomers being dimensionally unstable under load. It needed a hard filter:

```python
ELASTOMER_ELONGATION = 200.0
```

Any material above that elongation is rejected when the part is `fit_critical`, when the
tolerance class is `tight` or `press_fit`, or when the stated tolerance is ≤ 0.2 mm — with the
reason "too elastic to hold a dimension; it deforms under the load that would check the fit."
The gear now gets PETG. TPU remains available wherever dimensions do not matter.

**The general point.** A weighted scoring system will confidently return a nonsense answer when
a constraint exists in the physics but not in the feature set. The failure is silent, and the
prose rationale it generates reads perfectly convincing.

### 2.3 A bearing seat quoted without anyone asking about tolerance

**Symptom.** "A bearing seat for a spindle. Indoors." was quoted in PETG. The tolerance question
was never asked.

**Cause.** Follow-up questions were ranked by a fixed table of impact weights, and precision sat
at 0.60. For this description the questions above it were load type (0.95), lifecycle (0.90),
service temperature (0.85), outdoor UV (0.75) and brittleness (0.70) — putting tolerance sixth,
exactly one place past the five the form shows. On the one class of part where the dimension
*is* the requirement, the question that decides it fell off the bottom of the list.

**Fix.** The ranking now reads the customer's own words. `_CONTEXT_BOOSTS` promotes tolerance by
0.5 when the description contains fit language (bearing, press fit, mates with, shaft, spindle,
thread, tolerance); heat words promote service temperature; outdoor words promote UV.
`_LIFECYCLE_DAMPING` works the other way — someone printing a display piece is not asked how
much load it carries, which was wasting one of five slots. The keyword extractor also now reads
that same language as `fit_critical`, recording the inference so the customer can correct it.

A bearing seat is now asked about tolerance first, and correctly declined as beyond FDM.

### 2.4 A questionnaire option that could never be satisfied

**Symptom.** Found while seeding: two of four demo parts were declined outright.

**Cause.** The intake form offers four tolerance options, including "Tight — it mates with other
parts". That mapped to 0.12 mm. The FDM process floor is 0.15 mm. **Selecting it always
declined the job.**

Anyone ordering a part that has to fit something else — a large share of real functional work —
would have been turned away by a form option presented as a normal choice.

**Fix.** `tight` now maps to 0.15 mm, exactly what a tuned machine holds. `press_fit` stays at
0.08 mm and still declines, correctly, because that genuinely is beyond the process.

This one is worth dwelling on: it was invisible to unit tests because every test that exercised
the declining path *asserted the decline*. The tests confirmed the code did what it was written
to do. What was wrong was that the form offered a choice the engine could never honour, and no
assertion covered the relationship between the two.

### 2.5 The WebGL preview, and warnings printed twice

Two rendering faults from the same browser walk.

The mesh preview was constructed with `renderer.setSize(w, h, false)`. With `updateStyle` off,
the canvas keeps its intrinsic size regardless of its container — so the part rendered outside
its card and across the rest of the page. Fixed by passing `true` and setting explicit CSS
dimensions, with the container clipped.

The geometry warnings appeared twice on the quote screen. The worker deliberately copies
`geometry.warnings` into `recommendation.warnings` so a `Recommendation` stands alone as an API
response — reasonable on its own terms — and the page rendered both objects. Fixed in the UI by
passing the already-displayed warnings down and filtering, rather than by weakening the API
contract.

Neither is subtle. Both survived a full test suite because neither is testable without rendering
the page.

---

## 3. Replacing the estimate with a real slice

Quoting originally used a geometric estimator: shell volume from surface area times wall
thickness, plus infill fraction, with a flat per-layer time overhead. It exists so a quote can be
produced with no slicer installed, and everything it produces is flagged `estimated`.

### Getting PrusaSlicer running headless

PrusaSlicer 2.7.2 installs from the Ubuntu archive
(`apt-get install --no-install-recommends prusa-slicer`). It reports itself as "with GUI
support", but `--export-gcode` runs with no display.

The first real slice returned `total filament used [g] = 0.00`. PrusaSlicer computes mass from
`filament_density`, which is unset unless a profile supplies it. That forced a decision that
turned out to matter more than the slicer itself.

### Profiles are generated, not hand-written

`scripts/gen_slicer_profiles.py` emits one complete `.ini` per stocked material. Printer geometry
comes from `config/shop.yaml`; density, temperatures and volumetric flow limits come from
`data/materials.yaml`.

Hand-maintained profiles drift. If the material table says PETG is 1.27 g/cm³ and the profile
says 1.24, every quote is quietly wrong in a way nothing surfaces. Generating them means the
density the slicer weighs filament with is definitionally the density the quote is priced on.
This also pushed print temperatures and melt-rate ceilings into the material table where they
belong (`nozzle_c`, `bed_c`, `max_volumetric_mm3_s`), taking it from version 0.1.0 to 0.3.0.

### The kinematics mistake: 2–5× too much machine time

The first generated profiles set no speeds. PrusaSlicer therefore used its own defaults —
60 mm/s perimeters, 1500 mm/s² acceleration — which describe an MK3-class machine, not the
CoreXY the shop config declares.

The first comparison run looked like this:

| Part | Time est. | Time "real" | Err |
| --- | --- | --- | --- |
| sign-bracket | 89 min | 198 min | −55% |
| enclosure-lid | 47 min | 174 min | −73% |
| standoff | 42 min | 201 min | −79% |
| gear-blank | 21 min | 68 min | −69% |

**What gave it away was the consistency.** Every part wrong in the same direction, by a similar
large factor, is a systematic error — a wrong constant somewhere — not an estimator that happens
to be bad. Genuine estimator error would scatter. Checking the emitted G-code header confirmed
it:

```
; perimeter_speed = 60
; machine_max_acceleration_extruding = 1500,1250
```

Had this gone unexamined, the "real" slice would have overcharged every customer for machine
time by a factor of three or four, and it would have looked more authoritative than the estimate
it replaced.

Profiles now carry kinematics per printer family (`MACHINE_PROFILES`): 300 mm/s inner perimeters,
500 mm/s travel, 10000 mm/s² acceleration, tracking Bambu Studio's 0.20 mm Standard profile. On a
machine that fast the binding constraint is not the feedrate but how quickly the hotend melts
plastic, so each material carries `max_volumetric_mm3_s` as well.

### What the estimator actually costs

Same four parts, same answers, same materials, after the kinematics fix:

| Part | Material | Settings | Mass est. | Mass real | Err | Time est. | Time real | Err |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sign-bracket | ASA | 5w / 40% | 46.9 g | 35.5 g | +32% | 89 min | 79 min | +12% |
| enclosure-lid | PLA | 2w / 10% | 31.4 g | 27.3 g | +15% | 47 min | 34 min | +38% |
| standoff | PLA | 5w / 40% | 17.3 g | 18.4 g | −6% | 42 min | 136 min | **−69%** |
| gear-blank | PETG | 5w / 40% | 13.3 g | 9.1 g | +46% | 21 min | 31 min | −31% |

| Part | Qty | Price est. | Price real | Err |
| --- | --- | --- | --- | --- |
| sign-bracket | 3 | $81.39 | $76.55 | +6% |
| enclosure-lid | 1 | $25.00 | $25.00 | 0% (minimum order) |
| standoff | 8 | $177.08 | $271.80 | **−35%** |
| gear-blank | 1 | $25.00 | $25.00 | 0% (minimum order) |

Mass holds up reasonably and errs high, which is the safe direction. Chunky parts price within
6%. Two of four parts price identically despite time errors of 31–38%, because the minimum order
absorbs them — worth knowing, since it means estimator accuracy is irrelevant below that
threshold.

### Why the standoff is 69% out

The standoff is an 18 mm tube, 70 mm tall. Slicing it at two layer heights isolates the cause:

| Layer height | Layers | Material | Time |
| --- | --- | --- | --- |
| 0.20 mm | 350 | 14.81 cm³ | 81 min |
| 0.12 mm | 582 | 14.87 cm³ | 136 min |

Identical material extruded. 232 more layers. 54 more minutes — **14.1 seconds per layer**,
against the estimator's assumed 1.6 s. Since the material is the same, essentially the entire
print time on this part is per-layer cost.

Cooling was ruled out directly: forcing `slowdown_below_layer_time = 0` changed the time not at
all. The actual cause is geometry. The annulus is a 64-facet polygon, so every perimeter loop is
64 short segments, and at 10000 mm/s² the toolhead never reaches its commanded 300 mm/s before
it must decelerate into the next corner. The feedrate histogram of the emitted G-code shows
thousands of moves at 15–35 mm/s on a profile whose slowest print speed is 50.

The part is **acceleration-limited, not flow-limited**. Nothing in the estimator's inputs —
volume, surface area, bounding box — can predict that. Doing so requires toolpath length and
segment count, which is to say it requires a slicer.

### The decision not to tune the estimator

The obvious next move is to raise `LAYER_OVERHEAD_S` until the standoff matches. It was rejected.

The estimator's bias is geometry-dependent, not constant: it runs 12–38% *high* on time for
chunky parts and 69% *low* on tall thin ones. A single correction factor moves the error around
rather than removing it, and makes the remaining error harder to reason about. Real slicing is
now the default whenever `SLICER_BIN` resolves; the estimator stays a labelled fallback with its
bias documented rather than a tuned approximation pretending to be a measurement.

### A test suite that quietly started lying

Installing the slicer changed the meaning of the existing tests. Anything exercising `/quote`
silently began doing real slicing — the same 117 tests went from 0.8 s to 2.8 s — so results
depended
on whether a slicer happened to be present, and CI would have tested something different from a
developer laptop.

Fixed with an autouse fixture that forces the estimator, plus a `real_slicer` marker for the
seven tests that genuinely need a binary and skip without one. **124 tests with a slicer
installed; 117 passed and 7 skipped without.**

---

## 4. The bug at the seam

After all of the above, re-seeding the demo against real slices surfaced one more.

The artifact download served a **valid PrusaSlicer G-code file named `standoff-pla.3mf`, with
`content-type: model/3mf`**.

The worker had been updated correctly: it emits G-code for PrusaSlicer, `.3mf` for Bambu Studio
and OrcaSlicer, and sets the content type to match. The Next.js admin route that proxies it still
hardcoded `.3mf` and `model/3mf` from before the slicing work.

Neither a Prusa nor a Bambu would accept the result. A file whose name lies about its contents is
worse than no file, because the failure surfaces at the printer.

**Why no unit test on either service could have caught it.** The worker's `artifact_suffix()` was
correct and directly tested (`test_artifact_suffix_matches_the_slicer_family`). The web route
was internally consistent too — it just held a stale belief about what the worker produces. Each
service was right about itself. The defect existed only in the *agreement between them*, and
neither one's tests can see that: the worker's tests never call the web route, and the web
route's tests (had any existed) would have mocked the worker with the same stale assumption
baked in.

It took a request that crossed the boundary and inspected the response headers. That is contract
testing, and this repo does not have it — the seam is still covered only by walking it.

The route now takes the format from the upstream response, so neither side guesses.

---

## 5. What generalises

- **Tests that pass are not evidence the product works.** 109 green tests coexisted with a
  checkout flow no one could complete. Unit tests verify functions against their author's
  intent; they cannot verify that a sequence of correct functions composes into a usable path.
- **Seed and demo data should come through the front door.** Writing rows directly produces a
  database that looks right while the code that should have produced it is broken.
- **A systematic error looks different from a bad estimate.** Four parts all wrong in the same
  direction by a similar factor pointed at a wrong constant, not a weak model. That distinction
  is what turned a plausible-looking slicer result into a caught bug.
- **Scoring systems fail silently when a constraint is missing from the feature set.** No
  weighting change could have kept TPU out of a clock gear; the inputs contained no signal for
  dimensional stability. The output was wrong *and* fluent.
- **Defects at a service boundary are invisible to both sides.** Two internally correct services
  can disagree, and only a call that crosses the seam will show it.
- **Don't tune an approximation to match a measurement you already have.** Keep the measurement,
  label the approximation, and document its bias.
