# Open Questions

Answers to §1 change what gets built and in what order. §2–§5 can be settled during Phase 0.

## 1. Blocking — needed before Phase 1

### Hardware
1. **Which printers do you have now, and what firmware?** (Bambu / Prusa / Klipper-Moonraker /
   OctoPrint / other.) This is the single biggest determinant of how automated Phase 3 can be.
   Klipper+Moonraker gives a full API; Bambu LAN control depends on unofficial libraries.
2. How many printers, and are any **enclosed**? Without an enclosure, ABS/ASA/PC/nylon come off
   the offering entirely and the material table shrinks to PLA/PETG/TPU.
3. **Hardened nozzle** on any machine? Gates all CF-filled materials.
4. Multi-material (AMS/MMU)? Affects soluble supports and colour options.
5. Any **resin** printer? If not, tight-tolerance and fine-detail jobs get declined rather than escalated.
6. Do you have a **filament dryer**, and are you willing to run a drying-before-print step as part
   of the workflow? Nylon and PC are not viable without it.

### Hosting and stack
7. Cloud storefront + local shop agent (recommended), or **everything self-hosted** at home?
   Self-hosting means uptime, backups, and TLS are yours; it saves maybe $30/month.
8. Are you comfortable in **TypeScript/Next.js**, or would you rather the whole thing be Python
   (FastAPI + HTMX/Streamlit)? A stack you can debug at 11pm beats a marginally better one.
9. Is this something you want to **build yourself with me**, or have built for you to a working state?

### Commerce
10. **Where do you take payment** — Stripe on your own site, or Etsy checkout as the primary rail?
    Etsy takes a cut and hides the customer, but supplies traffic.
11. **Pay in full up front, or deposit then balance?** Custom parts are non-refundable in practice;
    full payment up front is normal for made-to-order and simplifies everything.
12. **Country and tax** — you're subject to whichever of GST/VAT/sales tax applies where you are,
    and Stripe Tax handles it if configured. Where are you operating and shipping from?
13. **Minimum order value** and maximum print time you'll accept as an auto-quote?

### Scope of the offering
14. Which materials do you actually want to **stock and offer on day one**? Recommending something
    you don't stock is worse than not offering it.
15. Local pickup, domestic shipping, international? Shipping cost calculation is easy to get wrong
    for large/light parts (dimensional weight).

## 2. Product behaviour

16. Should customers be able to **override** the recommendation ("I want it in PLA anyway")? My
    take: yes, with a logged acknowledgement — it removes an argument and protects you.
17. **Auto-approve rules** — do you want small, safe, cheap jobs to skip your review once you trust
    the system, or is every job gated forever?
18. Customer-facing **live status and webcam**, or just email milestones? Webcam is a great trust
    signal and a support-load reducer, but it also invites "why has it not moved" messages.
19. Multi-part orders and assemblies — one quote per file, or per order?
20. Do you want to offer **post-processing** as line items: support removal (assumed), sanding,
    vapour smoothing, painting, heat-set threaded inserts, annealing?
21. **Design services** — model repair, DfAM review, "make this printable", full CAD from a sketch?
    This is likely your highest-margin offering and the natural Upwork product.
22. **NDA / confidentiality option** for engineering clients? B2B customers will ask.

## 3. Operations

23. Turnaround you're willing to commit to, and do you want **rush pricing** tiers?
24. Reprint policy on failed prints — automatic and silent, or your call each time?
25. Do you want **filament inventory tracking** with low-stock and drying alerts?
26. Plate **nesting/batching** across multiple orders — big efficiency win, meaningful complexity.
27. Capacity ceiling: at what queue depth should the site stop taking orders or extend lead times
    automatically?

## 4. Growth

28. Is there a **niche** you want to lead with? "Any 3D printing" competes on price with print
    farms; "engineering-grade functional parts, material selection included" is defensible and
    matches your background. Choosing one narrows the ads, the copy, and the material table.
29. Do you want the **free material selection report** as a lead magnet (email capture, SEO
    long-tail, converts into orders)?
30. B2B/repeat accounts with saved parts and reorder-in-one-click, or one-off consumers only?

## 5. Guardrails

31. Confirm the **prohibited parts** list: firearms components, medical/implantable, safety-critical
    structural, anything under load where failure injures someone. Where do you want the line?
32. How long do you **retain customer meshes** after fulfilment, and do you say so publicly?
33. Do you want an explicit **anisotropy/property disclaimer** shown on every quote, not just in
    the terms? (Strongly recommended — it's the claim most likely to come back at you.)
