import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { Rationale } from "@/components/Rationale";
import { isOperator } from "@/lib/admin-auth";
import { db } from "@/lib/db";
import { formatDuration, formatMoney } from "@/lib/money";
import type { CostLine, GeometryReport, Recommendation, Requirements } from "@/lib/types";
import { advanceOrder, approveOrder, declineOrder } from "../../actions";

export const dynamic = "force-dynamic";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
    </div>
  );
}

/** The requirements the quote was priced against, in the operator's language rather than JSON. */
function requirementsSummary(req: Requirements): string[] {
  const bits: string[] = [];
  if (req.lifecycle) bits.push(req.lifecycle.replace(/_/g, " "));
  if (req.load?.type && req.load.type !== "none") {
    const detail = [req.load.qualitative, req.load.duration].filter(Boolean).join(", ");
    bits.push(`${req.load.type} load${detail ? ` (${detail})` : ""}`);
  }
  if (req.thermal?.max_service_c) bits.push(`up to ${req.thermal.max_service_c} C`);
  if (req.thermal?.sunlight_hot_car) bits.push("sun or parked car");
  if (req.environment?.outdoor_uv) bits.push("outdoors");
  if (req.environment?.moisture && req.environment.moisture !== "dry") {
    bits.push(String(req.environment.moisture));
  }
  if (req.environment?.chemicals?.length) bits.push(req.environment.chemicals.join(", "));
  if (req.precision?.tolerance_class) bits.push(`${req.precision.tolerance_class} tolerance`);
  if (req.brittleness_tolerance) bits.push(req.brittleness_tolerance.replace(/_/g, " "));
  if (req.cost_sensitivity) bits.push(`cost sensitivity ${req.cost_sensitivity}`);
  if (req.lead_time && req.lead_time !== "standard") bits.push(`${req.lead_time} turnaround`);
  return bits;
}

export default async function AdminOrderPage({ params }: { params: Promise<{ id: string }> }) {
  if (!(await isOperator())) redirect("/admin");
  const { id } = await params;

  const order = await db.order.findUnique({
    where: { id },
    include: { customer: true, quote: { include: { upload: true } }, jobs: true },
  });
  if (!order) notFound();

  const events = await db.event.findMany({
    where: { entity: "order", entityId: order.id },
    orderBy: { createdAt: "desc" },
    take: 20,
  });

  const quote = order.quote;
  const recommendation = quote?.recommendation as unknown as Recommendation | undefined;
  const requirements = quote?.requirements as unknown as Requirements | undefined;
  const geometry = quote?.upload.geometry as unknown as GeometryReport | undefined;
  const lines = (quote?.breakdown ?? []) as unknown as CostLine[];

  const approve = approveOrder.bind(null, order.id);
  const decline = declineOrder.bind(null, order.id);

  return (
    <div className="space-y-8">
      <div>
        <Link href="/admin" className="text-sm text-accent hover:underline">
          &larr; Back to the queue
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          {quote?.upload.filename ?? "Order"}{" "}
          <span className="text-base font-normal text-muted">
            {order.status.replace(/_/g, " ").toLowerCase()}
          </span>
        </h1>
        <p className="mt-1 text-sm text-muted">
          {order.customer.email} &middot; {order.channel.toLowerCase()} &middot;{" "}
          {formatMoney(order.amountCents, order.currency)}
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          {geometry && (
            <section className="card">
              <h2 className="font-semibold">Geometry</h2>
              <dl className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-3">
                <Field label="Size">
                  {geometry.bbox_mm.map((v) => v.toFixed(0)).join(" x ")} mm
                </Field>
                <Field label="Volume">{(geometry.volume_mm3 / 1000).toFixed(1)} cm3</Field>
                <Field label="Footprint">{geometry.footprint_mm2.toFixed(0)} mm2</Field>
                <Field label="Thinnest wall">
                  {geometry.min_wall_mm ? `${geometry.min_wall_mm.toFixed(2)} mm` : "not measured"}
                </Field>
                <Field label="Overhang">{Math.round(geometry.overhang_fraction * 100)}%</Field>
                <Field label="Watertight">{geometry.is_watertight ? "yes" : "no"}</Field>
              </dl>
              {geometry.warnings.length > 0 && (
                <ul className="mt-4 space-y-2">
                  {geometry.warnings.map((warning) => (
                    <li
                      key={warning}
                      className="rounded-md border border-warn/30 bg-warn/5 px-3 py-2 text-sm text-warn"
                    >
                      {warning}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {requirements && (
            <section className="card">
              <h2 className="font-semibold">What they asked for</h2>
              {requirements.raw_text && (
                <blockquote className="mt-3 border-l-2 border-rule pl-4 text-sm italic text-muted">
                  {requirements.raw_text}
                </blockquote>
              )}
              <p className="mt-3 text-sm">{requirementsSummary(requirements).join(" \u00b7 ")}</p>
              {order.operatorNotes && (
                <p className="mt-3 rounded-md bg-rule/30 px-3 py-2 text-sm">
                  <span className="font-medium">Customer note:</span> {order.operatorNotes}
                </p>
              )}
            </section>
          )}

          {recommendation && (
            <section className="card">
              <h2 className="font-semibold">
                Recommendation{" "}
                <span className="text-sm font-normal text-muted">
                  table {recommendation.table_version}
                </span>
              </h2>
              {quote?.overridden && (
                <p className="mt-3 rounded-md border border-warn/30 bg-warn/5 px-3 py-2 text-sm text-warn">
                  The customer chose {quote.materialId.toUpperCase()} over our recommended{" "}
                  {recommendation.primary.name}. Print what they asked for unless it&rsquo;s
                  unsafe.
                </p>
              )}
              <div className="mt-3">
                <Rationale text={recommendation.rationale} />
              </div>
              {recommendation.orientation_advice && (
                <p className="mt-3 rounded-md border border-accent/30 bg-accentSoft px-3 py-2 text-sm">
                  {recommendation.orientation_advice}
                </p>
              )}
              {recommendation.rejected.length > 0 && (
                <details className="mt-4">
                  <summary className="cursor-pointer text-sm font-medium text-accent">
                    Ruled out ({recommendation.rejected.length})
                  </summary>
                  <ul className="mt-2 space-y-1 text-sm">
                    {recommendation.rejected.map((item) => (
                      <li key={item.material_id} className="flex gap-2">
                        <span className="w-28 shrink-0 font-medium">{item.name}</span>
                        <span className="text-muted">{item.reason}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </section>
          )}
        </div>

        <div className="space-y-6">
          {quote && (
            <section className="card">
              <h2 className="font-semibold">Quote</h2>
              <dl className="mt-3 space-y-2">
                <Field label="Material">
                  <span className="uppercase">{quote.materialId}</span>
                </Field>
                <Field label="Quantity">{quote.quantity}</Field>
                <Field label="Print time">{formatDuration(quote.printMinutes)} each</Field>
                <Field label="Material mass">{quote.filamentGrams.toFixed(0)} g each</Field>
                <Field label="Slice">
                  {quote.estimated ? "estimated from geometry" : "real slice"}
                </Field>
              </dl>
              <table className="mt-4 w-full text-sm">
                <tbody>
                  {lines.map((line) => (
                    <tr key={line.label}>
                      <th scope="row" className="py-1 text-left font-normal text-muted">
                        {line.label}
                      </th>
                      <td className="tabular py-1 text-right">
                        {formatMoney(Math.round(line.amount * 100), quote.currency)}
                      </td>
                    </tr>
                  ))}
                  <tr className="border-t border-rule">
                    <th scope="row" className="py-1.5 text-left font-semibold">
                      Total
                    </th>
                    <td className="tabular py-1.5 text-right font-semibold">
                      {formatMoney(quote.priceCents, quote.currency)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </section>
          )}

          {order.status === "IN_REVIEW" && quote && (
            <section className="card">
              <h2 className="font-semibold">Decide</h2>
              <form action={approve} className="mt-4 space-y-3">
                <div>
                  <label className="label" htmlFor="materialId">
                    Print in
                  </label>
                  <input
                    id="materialId"
                    name="materialId"
                    defaultValue={quote.materialId}
                    className="input mt-1"
                  />
                  <p className="mt-1 text-xs text-muted">
                    Changing this is recorded against the order. Tell the customer if the price
                    moves.
                  </p>
                </div>
                <div>
                  <label className="label" htmlFor="notes">
                    Notes to self
                  </label>
                  <textarea id="notes" name="notes" className="input mt-1 min-h-16" />
                </div>
                <button type="submit" className="btn-primary w-full">
                  Approve and queue
                </button>
              </form>

              <form action={decline} className="mt-6 space-y-3 border-t border-rule pt-4">
                <label className="label" htmlFor="reason">
                  Or decline, with a reason the customer will see
                </label>
                <textarea id="reason" name="reason" required className="input min-h-16" />
                <button type="submit" className="btn-secondary w-full text-bad">
                  Decline and refund
                </button>
              </form>
            </section>
          )}

          {["APPROVED", "PRINTING", "READY", "SHIPPED"].includes(order.status) && (
            <section className="card">
              <h2 className="font-semibold">Move it along</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {(["PRINTING", "READY", "SHIPPED", "COMPLETED"] as const).map((status) => (
                  <form key={status} action={advanceOrder.bind(null, order.id, status)}>
                    <button type="submit" className="chip">
                      {status.toLowerCase()}
                    </button>
                  </form>
                ))}
              </div>
            </section>
          )}

          {order.jobs.length > 0 && (
            <section className="card">
              <h2 className="font-semibold">Print jobs</h2>
              <ul className="mt-3 space-y-3 text-sm">
                {order.jobs.map((job) => (
                  <li key={job.id}>
                    <div className="flex justify-between gap-2">
                      <span>
                        Attempt {job.attempt} &middot;{" "}
                        <span className="uppercase">{job.materialId}</span>
                      </span>
                      <span className="text-muted">{job.state.toLowerCase()}</span>
                    </div>
                    <a
                      href={`/api/admin/jobs/${job.id}/artifact`}
                      className="mt-1 inline-block text-accent hover:underline"
                    >
                      Download sliced .3mf
                    </a>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted">
                Slicing needs SLICER_BIN pointing at Bambu Studio or OrcaSlicer. Until the shop
                agent is running, download the plate and send it to the printer yourself.
              </p>
            </section>
          )}

          <section className="card">
            <h2 className="font-semibold">History</h2>
            <ul className="mt-3 space-y-2 text-sm">
              {events.map((event) => (
                <li key={event.id} className="flex justify-between gap-3">
                  <span>{event.type.replace(/[._]/g, " ")}</span>
                  <time className="shrink-0 text-muted" dateTime={event.createdAt.toISOString()}>
                    {event.createdAt.toLocaleString("en-AU")}
                  </time>
                </li>
              ))}
              {events.length === 0 && <li className="text-muted">Nothing recorded yet.</li>}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
