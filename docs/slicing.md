# Slicing

Quotes are priced from a real slice when a slicer is available, and from a geometry estimator
when one is not. This page covers how the slicer is wired in, and — more usefully — how far
apart those two numbers actually are.

## What is installed

PrusaSlicer 2.7.2, from the Ubuntu archive:

```bash
apt-get install -y --no-install-recommends prusa-slicer
```

It ships with GUI support compiled in, but `--export-gcode` runs headless with no display. The
worker finds it via `SLICER_BIN`, or on the `PATH`. `scripts/devstack.sh` exports it
automatically, and `GET /health` reports which slicer and how many profiles are in use.

OrcaSlicer and Bambu Studio are also supported. They take JSON settings bundles and export a
`.3mf` project rather than G-code, which is what a Bambu machine actually needs — the plate
layout and AMS filament assignment live in the 3mf and have nowhere to go in raw G-code. The
worker picks the right command shape and output format from the binary name.

## Profiles are generated, not hand-written

`scripts/gen_slicer_profiles.py` writes one complete `.ini` per stocked FDM material into
`config/slicer-profiles/prusaslicer/`. Printer geometry comes from `config/shop.yaml`; density,
temperatures and flow limits come from `data/materials.yaml`.

This matters more than it sounds. Hand-maintained profiles drift: if the material table says
PETG is 1.27 g/cm³ and the profile says 1.24, every quote is quietly wrong and nothing tells
you. Regenerate after editing either file:

```bash
scripts/gen_slicer_profiles.py
```

### The profile has to model the right machine

The first pass at this set no speeds, so PrusaSlicer used its own defaults: 60 mm/s perimeters,
1500 mm/s² acceleration — an MK3-class machine. Quoted times came out **2–5× longer** than a
Bambu X1C would take, which would have overcharged every customer for machine time.

Profiles now carry kinematics per printer family (`MACHINE_PROFILES` in the generator), tracking
Bambu Studio's 0.20 mm Standard profile: 300 mm/s inner perimeters, 500 mm/s travel,
10000 mm/s² acceleration. On a machine that fast the real limit is not the feedrate but how
quickly the hotend can melt plastic, so each material also carries `max_volumetric_mm3_s`.

**If you change printers, change the kinematics.** A profile describing the wrong machine
produces confidently wrong prices.

## Estimator vs. real slice

Same four parts as the demo seed, same customer answers, same recommended material and print
settings. Reproduce with `scripts/compare_slicing.py`.

| Part | Material | Settings | Mass est. | Mass real | Err | Time est. | Time real | Err |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sign-bracket | ASA | 5 walls / 40% | 46.9 g | 35.5 g | **+32%** | 89 min | 79 min | +12% |
| enclosure-lid | PLA | 2 walls / 10% | 31.4 g | 27.3 g | +15% | 47 min | 34 min | **+38%** |
| standoff | PLA | 5 walls / 40% | 17.3 g | 18.4 g | −6% | 42 min | 136 min | **−69%** |
| gear-blank | PETG | 5 walls / 40% | 13.3 g | 9.1 g | **+46%** | 21 min | 31 min | −31% |

What that does to the price:

| Part | Qty | Price est. | Price real | Err |
| --- | --- | --- | --- | --- |
| sign-bracket | 3 | $81.39 | $76.55 | +6% |
| enclosure-lid | 1 | $25.00 | $25.00 | 0% (minimum order) |
| standoff | 8 | $177.08 | $271.80 | **−35%** |
| gear-blank | 1 | $25.00 | $25.00 | 0% (minimum order) |

### Where it holds

- **Chunky parts with large layer areas.** The sign bracket is the estimator's best case: a
  solid L-shape, few layers relative to its volume. Price within 6%.
- **Small parts generally**, because the minimum order absorbs the error. Two of four parts
  priced identically despite time being off by 31–38%, which is worth knowing — it means the
  estimator's accuracy simply does not matter below the minimum.
- **Mass is respectable.** Within ±46% on every part and usually much closer, because shell
  area plus infill fraction is a fair model of what gets extruded. It errs high, which is the
  safe direction.

### Where it breaks

**Tall parts with small layer cross-sections.** The standoff — an 18 mm tube, 70 mm tall — is
underestimated by 69% on time and 35% on price. That is the difference between a profitable
job and a loss-making one, and there are eight of them on that order.

The mechanism is measurable. Slicing the same standoff at two layer heights:

| Layer height | Layers | Material | Time |
| --- | --- | --- | --- |
| 0.20 mm | 350 | 14.81 cm³ | 81 min |
| 0.12 mm | 582 | 14.87 cm³ | 136 min |

Identical material, 232 more layers, 54 more minutes — **14.1 seconds per layer**. The
estimator assumes 1.6 s. It is not cooling: forcing `slowdown_below_layer_time = 0` changes the
time not at all. It is geometry. The annulus is a 64-facet polygon, so every perimeter loop is
64 short segments, and at 10000 mm/s² the toolhead never reaches its commanded 300 mm/s before
it has to decelerate into the next corner. The feedrate histogram shows thousands of moves at
15–35 mm/s on a profile whose slowest print speed is 50.

Curved and faceted geometry is **acceleration-limited, not flow-limited**, and nothing in the
estimator's inputs — volume, surface area, bounding box — can see that. Fixing it properly
needs toolpath length and segment count, which is to say it needs a slicer.

### What to do about it

Don't tune the estimator against these four numbers. Its bias is geometry-dependent — it runs
high on time for chunky parts and catastrophically low for tall thin ones — so a single
correction factor would trade one error for another.

Instead:

1. **Keep real slicing on in production.** It is the default whenever `SLICER_BIN` resolves.
2. **Treat an estimated quote as provisional.** The customer already sees this, and
   `requires_manual_review` should stay firmly on for estimated quotes above the minimum order.
3. **Watch tall parts.** A height-to-footprint ratio above about 3 is where the estimator is
   least trustworthy, and it already feeds the geometry risk score for exactly that reason.
