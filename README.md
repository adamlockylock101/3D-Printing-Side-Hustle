# 3D Printing Service

An automated, quote-to-print pipeline for a materials-engineer-run 3D printing service.

Customers upload a mesh, answer a short set of questions about how the part will be used,
and the system recommends a material, prices the job, takes payment, and drops the job into
a queue. The operator reviews and approves; an agent on the shop network slices, dispatches
to the printer, and reports status back.

## Documents

| Doc | What's in it |
| --- | --- |
| [docs/PLAN.md](docs/PLAN.md) | Architecture, data model, pricing, printer integration, roadmap |
| [docs/material-selection.md](docs/material-selection.md) | The requirements-to-material engine — the core differentiator |
| [docs/open-questions.md](docs/open-questions.md) | Decisions needed before Phase 1 build starts |
| [data/materials.yaml](data/materials.yaml) | Seed material property table (needs validation against supplier datasheets) |

## Status

Planning. Nothing implemented yet — the stack and printer integration choices in
[docs/open-questions.md](docs/open-questions.md) determine what gets built first.
