# Setup

Two services. The worker owns anything touching a mesh or the material table; the Next.js app
owns customers, orders and payments.

## Prerequisites

- Node 20+ and pnpm
- Python 3.11+ (and [uv](https://docs.astral.sh/uv/), or plain venv + pip)
- Postgres — local, [Neon](https://neon.tech) or [Supabase](https://supabase.com)
- Optional but recommended: Bambu Studio or OrcaSlicer, for real slicing rather than estimates

## The quick way (local development)

```bash
scripts/devstack.sh up        # Postgres, worker and storefront, with URLs printed
scripts/devstack.sh seed      # realistic orders, put through the real customer flow
scripts/devstack.sh restart   # after changing worker code — it does not hot-reload
scripts/devstack.sh down
```

The seed drives the actual HTTP endpoints rather than writing rows straight into the database.
That is deliberate: seed data inserted directly hides exactly the bugs seeding is meant to
expose, and three real ones turned up this way.

The rest of this page is the manual setup, and what each variable changes.

## First run

```bash
# 1. Worker
cd services/worker
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest -q                       # 106 tests, no external services needed

# 2. Storefront
cd ../../apps/web
pnpm install
cp .env.example .env.local      # fill in DATABASE_URL at minimum
pnpm prisma db push             # creates the schema
```

Then, in two terminals from the repo root:

```bash
pnpm worker        # http://localhost:8000  (docs at /docs)
pnpm dev           # http://localhost:3000
```

Visit `/quote` and put a part through. It works with nothing but `DATABASE_URL` set — quotes
come out as geometry estimates and checkout tells the customer you'll invoice by hand.

## Environment variables

| Variable | Needed for | Without it |
| --- | --- | --- |
| `DATABASE_URL` | Everything past a quote | Quotes still render; checkout returns a clean 503 |
| `WORKER_URL` | Talking to the worker | Defaults to `http://localhost:8000` |
| `ANTHROPIC_API_KEY` | Claude-backed intake parsing | Falls back to keyword extraction; the follow-up questions carry more of the load |
| `SLICER_BIN` | Real print times and masses | Falls back to the geometry estimator, flagged `estimated` everywhere it shows |
| `SLICER_PROFILES` | Machine-specific slicing | Uses slicer defaults, which will not match your printer |
| `STRIPE_SECRET_KEY` | Online payment | Orders are recorded and you invoice manually — the phase 0 path |
| `STRIPE_WEBHOOK_SECRET` | Marking orders paid | The webhook refuses unsigned requests, so orders stay in `AWAITING_PAYMENT` |
| `ADMIN_TOKEN` | The operator queue | You cannot sign in to `/admin` |
| `ETSY_API_KEY`, `ETSY_ACCESS_TOKEN`, `ETSY_SHOP_ID` | Importing Etsy orders | The import button reports that Etsy is not configured |
| `AGENT_TOKEN` | The shop agent (phase 3) | Not used yet |

Set `ANTHROPIC_API_KEY` and `SLICER_BIN` early — they are the two that most change quote quality.

## Configuring the shop

Almost everything you'd want to change is in `config/shop.yaml`, not in code: pricing rates, the
minimum order, rush multipliers, quantity breaks, printer capabilities, which materials you
stock, the auto-approve rules and the prohibited-parts list.

`data/materials.yaml` is the property table the selection engine reasons over. **Validate every
number against the datasheet for the filament you actually buy before you go live** — the seeded
values are typical figures for generic grades, and brand-to-brand variation within a family like
PETG is wider than most people expect.

Both files are re-read on `POST /admin/reload-config`, so you don't need to restart to change a
price. Bump `version` in `materials.yaml` whenever you edit it: every recommendation stores the
version it used, so an old quote stays reconstructable.

## Slicing

See [slicing.md](slicing.md) for the full picture, including how far off the estimator is when
no slicer is available.

```bash
# PrusaSlicer, from the distro (Linux)
apt-get install -y --no-install-recommends prusa-slicer

# Or point at an existing install
export SLICER_BIN=/Applications/BambuStudio.app/Contents/MacOS/BambuStudio   # macOS
```

The worker also finds a slicer on the `PATH`, and `scripts/devstack.sh` exports `SLICER_BIN`
for you. Check what is actually in use with `curl localhost:8000/health`.

Profiles are **generated, not hand-written**:

```bash
scripts/gen_slicer_profiles.py
```

That writes one `.ini` per stocked material into `config/slicer-profiles/prusaslicer/`, taking
printer geometry from `config/shop.yaml` and density, temperatures and flow limits from
`data/materials.yaml`. Regenerate after editing either. If you use OrcaSlicer or Bambu Studio
instead, put their JSON bundles in `config/slicer-profiles/orca/` as `machine.json` and
`<material_id>.json`.

Pin the slicer version and keep the profiles in this repo. A slicer upgrade that changes profile
semantics will change your quoted times, and you want that to be a visible commit.

## Stripe

1. Create the webhook endpoint at `https://yourdomain/api/webhooks/stripe`, subscribed to
   `checkout.session.completed` and `checkout.session.expired`.
2. Put the signing secret in `STRIPE_WEBHOOK_SECRET`. The route rejects unsigned requests — without
   this, anyone who finds the URL can mark orders paid.
3. Locally: `stripe listen --forward-to localhost:3000/api/webhooks/stripe`.

Shipping countries are set in `src/app/api/checkout/route.ts` (`allowed_countries`) and currently
allow AU and NZ.

## Etsy

Create an app at <https://www.etsy.com/developers/your-apps> and complete the OAuth flow to get an
access token. Etsy has no order webhook worth relying on, so the import is a pull: hit **Import
Etsy orders** in `/admin`, or schedule `POST /api/etsy/sync`.

Etsy orders arrive with money attached but no mesh, so they land in `AWAITING_FILES` and the buyer
needs pointing at `/quote` to complete intake.

## Deploying

- **Storefront** → Vercel. Set the environment variables above; `pnpm build` runs `prisma generate`.
- **Worker** → any container host (Fly.io, Railway) close to the storefront. It needs `config/` and
  `data/` on disk, so deploy from the repo root and set `PRINTSHOP_ROOT`.
- **Uploads** are on local disk under `uploads/`, content-addressed. That is fine for one box;
  move `services/worker/src/worker/storage.py` to S3/R2 when the worker stops being a single
  instance. Set a retention window and schedule `storage.purge()` — see open questions Q32.

## Running the tests

```bash
pnpm test:worker          # 106 Python tests
pnpm --filter web typecheck
pnpm --filter web lint
pnpm --filter web build
```

The worker tests need no database, no API key and no slicer. That is deliberate — the selection
engine is the part most worth being able to test on a laptop in thirty seconds.
