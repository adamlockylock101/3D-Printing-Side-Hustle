# Decisions

Recorded as they're made, with the consequences that follow. Supersedes the matching entries in
[open-questions.md](open-questions.md).

## D1 — Printers: Bambu Lab

**Consequence.** Printer control is the least automatable part of the chosen stack. Bambu machines
expose no official local API; the shop agent talks **LAN-mode MQTT (port 8883) plus FTPS (990)**
using the printer's access code, or falls back to Bambu Cloud.

What this means in practice:

- **Turn on LAN Mode / Developer Mode** on the printer and keep the access code. Cloud-only mode
  makes local automation dramatically harder and ties you to their availability.
- Pin the printer firmware version and **test the agent after every firmware update** — the
  unofficial protocol is what breaks. The agent is written so the transport is one swappable
  module (`agent/transports/`), so a break is a contained fix, not a rewrite.
- ~~G-code goes to the printer as a **`.3mf` project file**, not raw `.gcode` — Bambu's slicer
  metadata (plate, AMS mapping, filament assignment) lives in the 3mf. So the slicing step uses
  **Bambu Studio / OrcaSlicer CLI**, not PrusaSlicer.~~ **Superseded — see the note below.**
- AMS slot mapping matters: the agent must confirm the required filament is loaded in a known
  slot before starting, or the job prints in the wrong material.
- Enclosed machines (X1C/P1S) unlock ABS/ASA/PC/PA; an A1/A1 mini limits the catalogue to
  PLA/PETG/TPU. Which model(s) you have is still open — see Q-A below.

> **Superseded (slicer).** The code does not do this yet. **PrusaSlicer 2.7.2 is the current
> default**: it is the only slicer with generated profiles (`config/slicer-profiles/prusaslicer/`),
> and it exports G-code, not a `.3mf`. Those profiles approximate Bambu kinematics but carry
> generic `marlin2` start/end G-code and no plate or AMS metadata, so the output is fine for
> pricing but is not the file a Bambu machine expects. The worker *can* drive Bambu Studio or
> OrcaSlicer and export a `.3mf` (`services/worker/src/worker/slicing.py`), but only with
> hand-supplied JSON bundles in `config/slicer-profiles/orca/`, and none exist. Whether to switch
> is open — see Q-H below. The rest of D1 (Bambu printers, LAN-mode MQTT + FTPS, firmware
> pinning, AMS checks) still stands.

## D2 — Stack: Next.js storefront + Python worker

- `apps/web` — Next.js (App Router), TypeScript, Tailwind, Prisma over Postgres.
- `services/worker` — FastAPI. Owns everything mesh- and materials-related: geometry analysis,
  the selection engine, slicing, quoting, LLM intake parsing.
- The web app never does geometry. It stores files, calls the worker, persists results.

## D3 — Payments: Stripe **and** Etsy from day one

- Stripe Checkout is the primary rail on your own site; full margin, you keep the customer.
- Etsy is a second front door. Two listing types: fixed-price SKUs, and a "Custom Quote" deposit
  listing whose description links to your intake page.
- **Both funnel into one queue.** An Etsy order is imported via the Etsy API v3 and becomes an
  order row with `channel = 'etsy'`; the operator queue doesn't care where a job came from.
- Etsy orders arrive *without* a mesh or requirements, so importing one creates a job in state
  `awaiting_files` and triggers a message asking the buyer to complete the intake form.

## D4 — Scope: full MVP, phases 0–2

Storefront, instant quoting, both payment rails, and the operator review queue. The shop agent
(phase 3) comes after; until then "approve" produces a downloadable, ready-to-print 3mf and you
send it to the printer yourself. The agent's API contract is defined up front
([agent-contract.md](agent-contract.md)) so that swap is additive.

> **Superseded (approval output).** Approving produces whatever the configured slicer emits:
> **G-code from PrusaSlicer** (the current default), or a `.3mf` project from Bambu Studio or
> OrcaSlicer. The download is named and typed from the worker's response. With the default
> setup that is G-code, not a ready-to-print 3mf for the Bambu machines — see the D1 note and
> Q-H. The scope (phases 0–2, agent contract fixed up front) still stands.

## Still open — defaults assumed for now

These are configured in `config/shop.yaml` and changing them is a one-line edit, so the build
isn't blocked. Confirm when you can:

| Ref | Question | Assumed default |
| --- | --- | --- |
| Q-A | Which Bambu models, how many, enclosed? | One X1C-class enclosed machine, 256³ build volume, AMS present |
| Q-B | Hardened nozzle fitted? | Yes — CF materials enabled |
| Q-C | Country / currency / tax | AUD, GST-registered, Stripe Tax on |
| Q-D | Minimum order value | $25 |
| Q-E | Max auto-quoted print time | 24 h; longer routes to manual quote |
| Q-F | Materials stocked day one | PLA, Tough PLA, PETG, ASA, TPU 95A, PA6-CF |
| Q-G | Payment timing | Full payment up front |
| Q-H | Switch slicing to Bambu Studio or OrcaSlicer for the Bambu machines, so approval yields a `.3mf` the printer accepts? Needs JSON profile bundles (ideally generated, like the PrusaSlicer ones) and a re-run of the quote comparison | PrusaSlicer 2.7.2 for quoting and approval output. Until this is settled, re-slice the part in Bambu Studio before it goes on a Bambu printer |
