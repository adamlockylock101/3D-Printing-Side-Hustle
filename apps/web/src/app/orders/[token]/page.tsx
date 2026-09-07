import { notFound } from "next/navigation";
import { db } from "@/lib/db";
import { formatDuration, formatMoney } from "@/lib/money";
import type { CostLine, Recommendation } from "@/lib/types";
import { Rationale } from "@/components/Rationale";

export const dynamic = "force-dynamic";
export const metadata = { title: "Your order" };

const STATUS_COPY: Record<string, { label: string; detail: string }> = {
  AWAITING_FILES: {
    label: "Waiting on your model",
    detail:
      "We have your order but not your file yet. Upload it and answer a few questions and we'll get started.",
  },
  AWAITING_PAYMENT: {
    label: "Waiting on payment",
    detail: "Once payment clears, your job goes into the review queue.",
  },
  IN_REVIEW: {
    label: "Being reviewed",
    detail:
      "Every job is checked by hand before it reaches the printer. If anything looks wrong we'll email you before we start.",
  },
  APPROVED: {
    label: "Approved and queued",
    detail: "Checked and cleared. It'll start as soon as a printer frees up.",
  },
  PRINTING: { label: "Printing", detail: "Your part is on the plate." },
  REPRINT_PENDING: {
    label: "Reprinting",
    detail:
      "The first attempt didn't come out to standard, so we're running it again. No charge, and no need to chase us.",
  },
  READY: { label: "Ready", detail: "Printed, cleaned up and checked. Packing it now." },
  SHIPPED: { label: "Shipped", detail: "On its way to you." },
  COMPLETED: { label: "Complete", detail: "Done. We hope it fits." },
  DECLINED: { label: "Declined", detail: "We weren't able to take this one on." },
  REFUNDED: { label: "Refunded", detail: "Your payment has been returned in full." },
};

export default async function OrderPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const order = await db.order.findUnique({
    where: { publicToken: token },
    include: { quote: { include: { upload: true } }, jobs: true },
  });
  if (!order) notFound();

  const status = STATUS_COPY[order.status] ?? {
    label: order.status,
    detail: "",
  };
  const recommendation = order.quote?.recommendation as unknown as Recommendation | undefined;
  const lines = (order.quote?.breakdown ?? []) as unknown as CostLine[];
  const job = order.jobs.at(-1);

  return (
    <div className="max-w-3xl space-y-8">
      <div>
        <p className="text-sm text-muted">Order {order.id.slice(-8).toUpperCase()}</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">{status.label}</h1>
        <p className="mt-2 text-muted">{status.detail}</p>
        {order.declineReason && (
          <p className="mt-3 rounded-md border border-bad/30 bg-bad/5 px-4 py-3 text-sm text-bad">
            {order.declineReason}
          </p>
        )}
        {job && job.state === "PRINTING" && (
          <p className="mt-3 text-sm text-muted tabular">
            {Math.round(job.progress * 100)}% through attempt {job.attempt}.
          </p>
        )}
      </div>

      {order.quote && (
        <section className="card">
          <h2 className="font-semibold">
            {["DECLINED", "REFUNDED"].includes(order.status)
              ? "What you asked for"
              : ["COMPLETED", "SHIPPED"].includes(order.status)
                ? "What we printed"
                : "What we\u2019re printing"}
          </h2>
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted">File</dt>
              <dd className="mt-0.5 truncate font-medium">{order.quote.upload.filename}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted">Material</dt>
              <dd className="mt-0.5 font-medium uppercase">{order.quote.materialId}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted">Quantity</dt>
              <dd className="tabular mt-0.5 font-medium">{order.quote.quantity}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted">Print time</dt>
              <dd className="tabular mt-0.5 font-medium">
                {formatDuration(order.quote.printMinutes)} each
              </dd>
            </div>
          </dl>

          {order.quote.overridden && (
            <p className="mt-4 rounded-md border border-warn/30 bg-warn/5 px-3 py-2 text-sm text-warn">
              You chose this material rather than the one we recommended. Our recommendation is
              below for the record.
            </p>
          )}
        </section>
      )}

      {recommendation && (
        <section className="card">
          <h2 className="font-semibold">
            {["DECLINED", "REFUNDED"].includes(order.status)
              ? "What we would have recommended"
              : "Why this material"}
          </h2>
          <div className="mt-3">
            <Rationale text={recommendation.rationale} />
          </div>
          {recommendation.orientation_advice && (
            <p className="mt-3 text-sm leading-relaxed text-muted">
              {recommendation.orientation_advice}
            </p>
          )}
        </section>
      )}

      {lines.length > 0 && (
        <section className="card">
          <h2 className="font-semibold">
            {["DECLINED", "REFUNDED"].includes(order.status) ? "What was quoted" : "What you paid"}
          </h2>
          <table className="mt-3 w-full text-sm">
            <tbody>
              {lines.map((line) => (
                <tr key={line.label}>
                  <th scope="row" className="w-40 py-1.5 text-left font-medium">
                    {line.label}
                  </th>
                  <td className="py-1.5 pr-4 text-muted">{line.detail}</td>
                  <td className="tabular py-1.5 text-right">
                    {formatMoney(Math.round(line.amount * 100), order.currency)}
                  </td>
                </tr>
              ))}
              <tr className="border-t border-rule">
                <th scope="row" className="py-2 text-left font-semibold">
                  Total
                </th>
                <td />
                <td className="tabular py-2 text-right font-semibold">
                  {formatMoney(order.amountCents, order.currency)}
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
