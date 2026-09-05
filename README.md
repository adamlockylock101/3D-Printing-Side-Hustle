# 3D Printing Service

An automated, quote-to-print pipeline for a materials-engineer-run 3D printing service.

Customers upload a mesh, answer a short set of questions about how the part will be used, and
the system recommends a material — with the engineering reasoning attached — prices the job,
takes payment, and drops it into a queue. The operator reviews and approves, which slices the
plate ready for the printer.

## Documents

| Doc | What's in it |
| --- | --- |
| [docs/setup.md](docs/setup.md) | How to run it: prerequisites, env vars, slicer, Stripe, Etsy, deploying |
| [docs/PLAN.md](docs/PLAN.md) | Architecture, data model, pricing, printer integration, roadmap |
| [docs/decisions.md](docs/decisions.md) | Stack decisions and what each one implies |
| [docs/agent-contract.md](docs/agent-contract.md) | The phase 3 shop agent's API, fixed in advance |
| [docs/material-selection.md](docs/material-selection.md) | The requirements-to-material engine — the core differentiator |
| [docs/open-questions.md](docs/open-questions.md) | What is still undecided, and the defaults assumed meanwhile |
| [data/materials.yaml](data/materials.yaml) | Seed material property table (needs validation against supplier datasheets) |

## Layout

```
apps/web/           Next.js storefront, operator queue, Stripe and Etsy
services/worker/    FastAPI: geometry, material selection, slicing, quoting
config/shop.yaml    Pricing, printers, stocked materials, auto-approve, prohibited parts
data/materials.yaml The material property table the engine reasons over
docs/               Plan, decisions, setup, open questions
```

## Status

Phases 0&ndash;2 are built: instant quoting, both payment rails, and the operator review queue.
Approving a job produces a ready-to-print `.3mf` that you send to the printer yourself.

Phase 3 &mdash; the shop agent that dispatches to the Bambu printers automatically &mdash; is not
built. Its API is fixed in [docs/agent-contract.md](docs/agent-contract.md) so it drops in without
reworking anything either side of it.

Before going live, validate `data/materials.yaml` against the datasheets for the filament you
actually buy, and settle the remaining items in [docs/open-questions.md](docs/open-questions.md).

## Quick start

```bash
cd services/worker && uv venv .venv && source .venv/bin/activate && uv pip install -e ".[dev]"
cd ../../apps/web && pnpm install && cp .env.example .env.local && pnpm prisma db push
cd ../.. && pnpm worker      # terminal 1
             pnpm dev        # terminal 2
```

Full detail in [docs/setup.md](docs/setup.md).
