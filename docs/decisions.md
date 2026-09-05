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
- G-code goes to the printer as a **`.3mf` project file**, not raw `.gcode` — Bambu's slicer
  metadata (plate, AMS mapping, filament assignment) lives in the 3mf. So the slicing step uses
  **Bambu Studio / OrcaSlicer CLI**, not PrusaSlicer.
- AMS slot mapping matters: the agent must confirm the required filament is loaded in a known
  slot before starting, or the job prints in the wrong material.
- Enclosed machines (X1C/P1S) unlock ABS/ASA/PC/PA; an A1/A1 mini limits the catalogue to
  PLA/PETG/TPU. Which model(s) you have is still open — see Q-A below.

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
