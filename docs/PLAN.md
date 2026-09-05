# Build Plan

## 1. What the service actually is

A **made-to-order functional parts service**, differentiated by material selection expertise
rather than by price. Anyone can print a PLA trinket; the pitch here is "tell us what the part
has to survive and we'll tell you what it should be made of, and why."

That framing drives three decisions:

- The intake questionnaire is the product, not paperwork. It is also the marketing asset.
- Every quote ships with a short **material rationale** the customer can read and challenge.
  Cheap competitors do not do this; it justifies a price premium and reduces disputes.
- Automation is worth building because the margin per job is thin and the operator's time is
  the scarce resource.

## 2. Customer journey

```
Ad / Etsy / Upwork / referral
        │
        ▼
 Landing page ──► Upload mesh (STL/3MF/STEP/OBJ)
        │
        ▼
 Automatic geometry analysis  (size, volume, manifold check, wall thickness, overhangs)
        │
        ▼
 Intake: freeform "what's it for?" + adaptive follow-up questions
        │
        ▼
 Material recommendation (1 primary + 2 alternates, with rationale + orientation advice)
        │
        ▼
 Instant quote (headless slice → real time & mass) ──► Stripe checkout
        │
        ▼
 Job lands in OPERATOR REVIEW queue  ◄──── you approve / adjust material / re-quote / reject
        │
        ▼
 Approved ──► shop agent slices with final profile ──► uploads to printer ──► prints
        │
        ▼
 Status page + email updates ──► QC photo ──► ship ──► review request
```

The only mandatory human step is the review gate. Everything either side of it runs unattended.

## 3. Architecture

Three deployable pieces. Keeping them separate matters because the printer lives on a home
network and the storefront must not.

### 3.1 Web app (cloud)

- **Next.js (App Router) + TypeScript**, deployed on Vercel.
- **Postgres** (Supabase or Neon) for orders, customers, quotes, queue state.
- **Object storage** (Cloudflare R2 or Supabase Storage) for uploaded meshes and generated
  G-code. Signed URLs only; meshes are customer IP.
- **Stripe** for payments (Checkout + webhooks). Deposit-on-order, or pay-in-full — see open questions.
- **three.js** for in-browser mesh preview so the customer confirms they uploaded the right file
  and at the right scale. Catches the single most common order error (mm vs inch).
- **Auth**: guest checkout by default with a magic-link account for repeat/B2B customers.
  Forcing signup before a quote kills conversion.

### 3.2 Analysis + quoting worker (cloud container)

Python, because the mesh and slicing ecosystem is Python/CLI. Runs on Fly.io, Railway, or a
container on the same box as the agent.

- `trimesh` / `numpy-stl` for geometry: bounding box, volume, surface area, watertightness,
  self-intersection, minimum wall thickness sampling, overhang fraction, projected footprint.
- **Headless slicer** (`prusa-slicer --export-gcode` or `orca-slicer` CLI) against your real
  machine profiles → authoritative print time, filament mass, support mass. This is what makes
  instant quotes honest instead of a guess based on bounding-box volume.
- LLM call for intake parsing (see §5) with a strict JSON schema.
- Returns a `QuoteResult` the web app persists.

Slicing a big model takes 5–60 s, so this is a job queue, not a request handler. Customer sees
"analysing your part" with a progress state, quote arrives on-page and by email.

### 3.3 Shop agent (your network)

A small Python service on a Raspberry Pi or mini-PC next to the printers.

- **Outbound-only.** It polls (or holds a websocket to) the cloud API for approved jobs. No port
  forwarding, no exposing the printer to the internet, no dynamic DNS. This is the single most
  important security decision in the build.
- Downloads the approved G-code, uploads to the printer, starts the job.
- Streams back: printer state, progress %, nozzle/bed temps, layer, webcam stills, errors.
- Handles the "printer offline" case gracefully — jobs stay queued, you get an alert.

Printer API by ecosystem:

| Ecosystem | Interface | Automation quality |
| --- | --- | --- |
| Klipper + Moonraker | Full REST/websocket API | Best. Upload, start, pause, cancel, query, macros |
| OctoPrint (Marlin) | REST API + plugins | Very good |
| Prusa (MK4/XL/Core One) | PrusaLink local HTTP API / PrusaConnect | Good |
| Bambu Lab | LAN-mode MQTT + FTPS, or Bambu Cloud | Workable, unofficial libs, firmware churn |
| Elegoo / Anycubic resin | Mostly manual or vendor cloud | Poor — treat resin as a manual lane |

## 4. Data model (first cut)

```
customers        id, email, name, company, stripe_customer_id, is_b2b, created_at
uploads          id, customer_id, filename, storage_key, sha256, format, bytes
geometry         upload_id, bbox_xyz, volume_mm3, area_mm2, is_watertight, min_wall_mm,
                 overhang_frac, triangle_count, fits_build_volume, warnings[]
requirements     id, upload_id, raw_text, structured_json, confidence, unanswered_fields[]
recommendations  id, requirements_id, primary_material, alternates[], rationale_md,
                 orientation_advice, rejected_materials[] (+ why), infill, walls
quotes           id, upload_id, material, print_minutes, filament_g, support_g,
                 cost_breakdown_json, price_cents, expires_at, status
orders           id, quote_id, customer_id, stripe_payment_intent, status, due_date,
                 shipping_address, notes
jobs             id, order_id, printer_id, gcode_key, state, attempts,
                 started_at, finished_at, failure_reason
printers         id, name, kind, build_volume, enclosed, nozzle_mm, hardened_nozzle,
                 ams_slots, agent_last_seen
filament_stock   id, material_id, colour, grams_remaining, lot, opened_at, dried_at
events           id, entity, entity_id, type, payload_json, created_at   -- audit trail
```

`events` is worth having from day one. When a customer asks "why did my part cost that", or a
print fails, you want the full decision trail.

## 5. Intake: freeform text plus adaptive questions

Both, in one flow — freeform first, structured follow-up second.

1. One open box: *"What's this part for? Tell us how it'll be used, what it attaches to, and
   anything it has to survive."* Most customers write something useful, and it takes 20 seconds.
2. An LLM parses that into the structured requirements schema (see
   [material-selection.md](material-selection.md) §2), returning `null` for anything not stated
   and a confidence per field.
3. The system asks **only** the missing fields that would change the material choice — typically
   three to five questions, as chips/sliders, not a wall of form inputs. If someone writes
   "outdoor bracket holding a 5 kg sign, needs to last years", you don't ask about UV or load;
   you ask about temperature range and precision.
4. A short plain-language summary is shown back: *"Load-bearing, outdoor, up to 60 °C, moderate
   precision, cost-sensitive, end-use part."* Customer confirms or edits. This is the contract —
   it's what you're quoting against, and it's what protects you if the part is misused later.

**The LLM never picks the material.** It only converts prose into a requirements vector. The
selection itself is a deterministic, auditable rules engine over your curated property table.
That keeps recommendations reproducible, defensible, and correctable — and it's where your
materials background actually becomes a moat rather than a marketing line.

## 6. Pricing

```
price = material_cost + machine_cost + labour + risk_buffer + margin   (+ shipping, + rush)

material_cost = (filament_g + support_g) × (1 + waste_factor) × $/g
machine_cost  = print_hours × machine_rate      # depreciation + power + maintenance + nozzle/belt wear
labour        = setup_fixed + post_processing_estimate + packing_fixed
risk_buffer   = price_subtotal × failure_rate(material, geometry_risk_score)
```

Notes that matter in practice:

- **A minimum order value is non-negotiable.** Below roughly $15–25 you lose money on handling
  regardless of print time. Set it before you launch, not after the first bad order.
- **Charge for risk, not just resin.** A tall thin PC part with 70% overhangs has a real chance
  of failing at hour nine. `failure_rate` should key off material and a geometry risk score
  (height/footprint ratio, overhang fraction, thin walls, bed contact area).
- **Rush tiers** are close to free money — same work, different queue position.
- **Batch discounting**: quantity ≥ 5 shares setup and often shares a plate. Make the discount
  explicit so the quote looks fair.
- Auto-decline or route to manual quote anything over a print-time threshold (say 24 h) or
  outside the build volume, rather than silently quoting a job you don't want.

## 7. Operator review queue

One screen, everything on it:

- Mesh preview + slicer preview (colour by overhang/support), geometry warnings.
- Customer's own words, next to the parsed requirements summary.
- Recommended material with rationale, alternates, and **what was rejected and why**.
- Quote breakdown, editable — change material or profile and it re-quotes live.
- Actions: **Approve** / **Approve with changes** / **Request info** / **Refund & decline**.
- Filament check: does the recommended material exist in stock, in the right colour, and is it dry?

Keyboard-first. If review takes more than ~60 seconds per job on average, the automation isn't
paying for itself and something upstream needs fixing.

Sensible auto-approve rules once you trust the system: PLA/PETG, under 4 hours, under $60, from
a returning customer, no geometry warnings. Keep everything else gated.

## 8. Post-print

- QC photo taken by the agent from the webcam at job end (and a prompt to attach a proper
  photo). Attach to the order — huge for dispute resolution and for reviews.
- Auto-generate a packing slip + shipping label (Shippo/EasyPost, or your local carrier's API).
- Automated review request email a few days after delivery. Etsy reviews compound; this is the
  highest-ROI automation in the whole system.
- Failed print → automatic reprint job at the front of the queue, customer notified before they
  notice. A reprint you volunteered is a five-star review; one you were chased for isn't.

## 9. Channels

| Channel | How it actually works | Automation |
| --- | --- | --- |
| **Etsy** | Listings must have a price. Sell fixed SKUs *and* a "Custom Quote — 3D Printing" deposit listing that links to your intake page. Etsy API v3 can pull orders into your queue | Partial |
| **Upwork** | Services/project catalogue, not products. Manual bidding; use it for engineering-consult jobs (material selection reports, DfAM review) at a higher rate | Manual |
| **Google Ads** | Point at your own landing page, not Etsy. Intent keywords: "3d printing service <city>", "PETG printing service", "nylon 3d printing near me". Track quote-start → quote-complete → paid | Full |
| **Own site** | Where the real margin is — no marketplace fee, you keep the customer | Full |

One good lead magnet given your background: a free **material selection report** (no print
required). It ranks for long-tail search, collects emails, and converts a chunk of readers into
print orders.

## 10. Risk and legal

Not optional, and cheaper to set up now than to retrofit:

- **Terms of service**: customer warrants they own or are licensed for the geometry; you get a
  licence to print it. No claim of design fitness on your side.
- **Prohibited parts list**, enforced at intake: firearm components, medical implants or anything
  contacting internal tissue, safety-critical structural or life-support parts, anything the
  customer describes as load-bearing above a threshold you're not prepared to underwrite.
- **Material property disclaimer**, and mean it: printed parts are anisotropic and typically
  reach only 40–80% of the datasheet value in Z. Your recommendation is engineering guidance,
  not a certification. State it on the quote, not buried in the ToS.
- **Data handling**: customer meshes are confidential. Signed URLs, defined retention window,
  and an NDA option for engineering clients — B2B customers will ask.
- **Insurance**: worth a conversation with a broker once you're taking functional-part orders.

## 11. Roadmap

**Phase 0 — validate (1–2 weeks).** Landing page, upload form, intake questions, quote by email
within 24 h, manual everything. Etsy listing live. Goal: do 10 orders by hand and find out what
customers actually ask for. Do not skip this; it will change the schema.

**Phase 1 — instant quote.** Geometry analysis, materials table, selection engine, headless
slicing, Stripe checkout. This is the biggest single lift and the biggest conversion win.

**Phase 2 — queue and review.** Orders DB, operator review screen, G-code generation, status
emails, customer status page.

**Phase 3 — shop agent.** Printer dispatch, live status, webcam, failure detection, auto-reprint.
The gap between Phase 2 and 3 is "click approve then walk to the printer" — perfectly workable
while you're building.

**Phase 4 — scale.** Multi-printer scheduling, filament inventory with drying reminders, plate
nesting/batching across orders, B2B accounts with net terms, quoting API for repeat clients,
overflow to a partner farm.

Phases 0–2 are a viable business on their own. Phase 3 is what makes it a side hustle rather
than a second job.

## 12. What's genuinely hard

Flagging these now so they don't surprise you mid-build:

- **Headless slicing in a cloud container** is fiddly (GUI slicers in CLI mode, profile drift
  when you update the slicer, memory on big meshes). Pin the slicer version and treat profiles
  as versioned config in this repo.
- **STEP/IGES support** needs a CAD kernel (`cadquery`/OCCT) — meaningfully more work than STL.
  Ship STL/3MF/OBJ first; 3MF is the one worth prioritising because it carries units and colour.
- **Wall-thickness analysis** is genuinely difficult to do well. Ray-cast sampling gets you a
  usable warning; don't over-invest.
- **Bambu LAN control** relies on unofficial libraries and breaks on firmware updates. If printer
  automation is the point, Klipper/Moonraker is the path of least resistance.
- **Quoting accuracy vs. speed** — a full slice is accurate but slow. Cache by mesh hash +
  material + profile, and it's instant on repeats.
