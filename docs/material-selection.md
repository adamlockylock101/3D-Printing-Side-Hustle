# Material Selection Engine

The core of the service. A deterministic rules engine over a curated property table, fed by an
LLM that only does natural-language → structured-requirements translation.

## 1. Why not just ask an LLM?

Because it will confidently invent an HDT value, and you will be the one who has to explain to a
customer why their bracket sagged. Split the responsibilities:

| Job | Who does it | Why |
| --- | --- | --- |
| Prose → requirements vector | LLM, strict JSON schema | Language understanding is the thing LLMs are actually good at |
| Requirements → material | Rules engine over your table | Reproducible, auditable, correctable, and yours |
| Rationale → prose | LLM, but only over facts the engine emitted | Nice writing, zero invented numbers |

Every recommendation is then reproducible: same inputs, same output, and you can point at the
exact rule that eliminated a candidate.

## 2. Requirements schema

What the LLM extracts (all fields nullable, each with a confidence score):

```yaml
lifecycle:            prototype | fit_check | functional_prototype | end_use | cosmetic
load:
  type:               none | tension | compression | bending | shear | impact | cyclic | clamping
  magnitude_n:        number | null          # or qualitative: light / moderate / heavy
  duration:           momentary | intermittent | sustained     # sustained ⇒ creep matters
brittleness_tolerance: must_not_shatter | prefer_ductile | indifferent | stiffness_preferred
thermal:
  max_service_c:      number | null
  min_service_c:      number | null
  sunlight_hot_car:   bool                   # the sneaky one — a car interior hits 70-80 C
environment:
  outdoor_uv:         bool
  moisture:           dry | humid | splash | immersed
  chemicals:          [none | fuels | oils | solvents | acids | bases | alcohols]
  food_contact:       bool
  skin_contact:       bool
precision:
  tolerance_mm:       number | null          # or: cosmetic / standard / tight / press_fit
  fit_critical:       bool
  min_feature_mm:     number | null
aesthetics:
  visible:            bool
  colour:             string | null
  finish:             as_printed | smooth | paintable
cost_sensitivity:     low | medium | high
lead_time:            relaxed | standard | rush
quantity:             integer
notes_freeform:       string
```

Fields the customer didn't cover become the follow-up questions — ordered by how much each one
would change the outcome, not by schema order. Ask at most five.

## 3. Selection algorithm

### Step 1 — Hard filters (knock-out)

Eliminate any material that fails a stated requirement outright. Record the reason; the operator
UI shows the rejection list, and it's genuinely useful for explaining a quote.

```
max_service_c > hdt_045_c × 0.85            → reject (safety margin on heat deflection)
outdoor_uv and uv_resistance < GOOD         → reject
immersed and water_absorption > 1.0%        → reject   (kills nylon for wet duty)
chemicals ∩ material.attacked_by ≠ ∅        → reject
food_contact and not food_safe_capable      → reject
brittleness = must_not_shatter and
    elongation_at_break < 10%               → reject
tolerance_mm < process_capability_mm        → reject   (drives FDM → resin escalation)
part_bbox > printer.build_volume            → reject   (or flag for splitting)
requires_hardened_nozzle and no printer has one → reject
requires_enclosure and no enclosed printer      → reject
```

### Step 2 — Weighted score on survivors

```
score = Σ wᵢ · normalise(propertyᵢ)
```

Weights are derived from the requirements, not fixed. Examples:

- `lifecycle = prototype` + `cost_sensitivity = high` → weight cost 0.5, printability 0.3,
  mechanicals 0.2. PLA wins, correctly.
- `load.type = impact` + `must_not_shatter` → weight notched impact 0.4, elongation 0.25.
  PETG/ABS/nylon rise, PLA and any CF-filled grade fall.
- `load.duration = sustained` → creep resistance becomes a first-class term, which is the term
  that quietly eliminates PLA from anything holding a load for months.
- `precision.fit_critical` → weight dimensional stability and shrinkage; penalise high-warp and
  hygroscopic materials.

### Step 3 — Printability and stock adjustment

Multiply by a practical factor: do you have it in stock, does it need drying, what's its real
failure rate on your machines, does it need a hardened nozzle. A theoretically ideal material you
don't stock and can't print reliably is not the right answer.

### Step 4 — Output

- **Primary** recommendation with a rationale that cites the properties that decided it.
- **Two alternates** framed as trade-offs: "cheaper but softens above 55 °C", "tougher but +40%
  cost and a day longer".
- **Rejected list** with one-line reasons.
- **Orientation advice** — see §4.
- **Print settings**: walls, infill %, infill pattern, layer height, derived from load type. A
  bracket in bending wants more perimeters, not more infill; this is worth saying out loud since
  most customers assume the opposite.

## 4. Orientation and anisotropy

This is the highest-value thing you know that your competitors don't say. FDM parts are
substantially weaker across layer lines, so the *same material* can be twice as strong depending
on how it sits on the plate.

Approximate Z-to-XY strength ratios (validate on your machines):

| Material | Z / XY tensile |
| --- | --- |
| PLA | 0.45–0.65 |
| PETG | 0.70–0.85 |
| ABS/ASA | 0.50–0.65 |
| PC | 0.55–0.70 |
| PA (nylon) | 0.60–0.75 |
| PA-CF / PET-CF | 0.35–0.50 (fibres align in-plane) |
| TPU | 0.85–0.95 |

So: if the customer states a load direction, the engine emits an orientation recommendation
("printed flat so the layer lines run across your bending load, not along it"), and the operator
review screen shows it next to the slicer preview. For CF-filled materials the anisotropy is
severe enough that a bad orientation is worse than a cheaper material printed well — say so in
the rationale.

## 5. When FDM isn't the answer

Escalate to resin (or to "we can't do this") when:

- `tolerance_mm < 0.15` or `min_feature_mm < 0.8` → resin.
- Smooth cosmetic surface with fine detail (miniatures, jewellery masters) → resin.
- Optical clarity → neither process does this well; be honest rather than take the order.
- Certified biocompatible, flame-rated, or load-certified → decline. This is a "no" that protects
  the business.

Resin's weaknesses go in the same table: most standard resins are brittle (elongation 5–10%),
UV-degrading over time, and unsuitable for sustained load. The engine should reject them for
functional outdoor parts as firmly as it rejects PLA for a hot car.

## 6. Keeping the table honest

`data/materials.sample.yaml` is a starting point compiled from typical published values — treat
every number as provisional until you've checked it against the datasheet for the specific brand
and spool you actually buy, because grade-to-grade variation within "PETG" is larger than most
people assume.

Two habits worth building in from the start:

1. **Version the table.** Each recommendation stores the table version it used, so a quote can
   always be reconstructed.
2. **Feed real results back.** Log every job's outcome (succeeded, warped, failed, customer
   complained) against the material and geometry risk score. After ~100 jobs you have failure
   rates for your machines, which is better data than any datasheet for pricing risk and for
   the printability factor in Step 3.
