import Link from "next/link";
import { isOperator } from "@/lib/admin-auth";
import { db } from "@/lib/db";
import { formatDuration, formatMoney } from "@/lib/money";
import type { Recommendation } from "@/lib/types";
import { EtsyImportButton } from "./EtsyImportButton";
import { SignInForm } from "./SignInForm";
import { signOut } from "./actions";

export const dynamic = "force-dynamic";
export const metadata = { title: "Review queue" };

// Everything that needs a decision, most urgent first. A green queue is an empty one.
const ACTIONABLE = ["IN_REVIEW", "AWAITING_FILES", "APPROVED", "PRINTING", "REPRINT_PENDING"] as const;

export default async function AdminPage() {
  if (!(await isOperator())) {
    return <SignInForm />;
  }

  const orders = await db.order.findMany({
    where: { status: { in: ACTIONABLE as unknown as never[] } },
    include: { customer: true, quote: { include: { upload: true } } },
    orderBy: [{ status: "asc" }, { createdAt: "asc" }],
    take: 100,
  });

  const counts = await db.order.groupBy({ by: ["status"], _count: true });
  const countFor = (status: string) =>
    counts.find((row) => row.status === status)?._count ?? 0;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Review queue</h1>
          <p className="mt-1 text-sm text-muted tabular">
            {countFor("IN_REVIEW")} waiting on you &middot; {countFor("APPROVED")} queued to print
            &middot; {countFor("PRINTING")} on the plate
          </p>
        </div>
        <div className="flex items-center gap-3">
          <EtsyImportButton />
          <form action={signOut}>
            <button type="submit" className="btn-secondary">
              Sign out
            </button>
          </form>
        </div>
      </div>

      {orders.length === 0 ? (
        <p className="card text-muted">Nothing waiting. The queue is clear.</p>
      ) : (
        <ul className="space-y-3">
          {orders.map((order) => {
            const recommendation = order.quote?.recommendation as unknown as
              | Recommendation
              | undefined;
            const geometry = order.quote?.upload.geometry as { warnings?: string[] } | undefined;
            const warnings = geometry?.warnings?.length ?? 0;
            const overrode = order.quote?.overridden ?? false;

            return (
              <li key={order.id}>
                <Link
                  href={`/admin/orders/${order.id}`}
                  className="card block transition-colors hover:border-accent"
                >
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">
                          {order.quote?.upload.filename ?? "No file yet"}
                        </span>
                        <span className="rounded bg-rule px-1.5 py-0.5 text-xs uppercase tracking-wide">
                          {order.status.replace(/_/g, " ")}
                        </span>
                        {order.channel === "ETSY" && (
                          <span className="rounded bg-accentSoft px-1.5 py-0.5 text-xs text-accent">
                            Etsy
                          </span>
                        )}
                        {warnings > 0 && (
                          <span className="rounded bg-warn/10 px-1.5 py-0.5 text-xs text-warn">
                            {warnings} geometry warning{warnings > 1 ? "s" : ""}
                          </span>
                        )}
                        {overrode && (
                          <span className="rounded bg-warn/10 px-1.5 py-0.5 text-xs text-warn">
                            customer overrode material
                          </span>
                        )}
                        {order.quote?.estimated && (
                          <span className="rounded bg-rule/60 px-1.5 py-0.5 text-xs text-muted">
                            estimated slice
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-muted">
                        {order.customer.email}
                        {order.quote && (
                          <>
                            {" "}
                            &middot; {order.quote.quantity} x{" "}
                            <span className="uppercase">{order.quote.materialId}</span> &middot;{" "}
                            {formatDuration(order.quote.printMinutes)} each
                          </>
                        )}
                      </p>
                      {recommendation && overrode && (
                        <p className="mt-1 text-sm text-warn">
                          We recommended {recommendation.primary.name}.
                        </p>
                      )}
                    </div>
                    <span className="tabular shrink-0 font-medium">
                      {formatMoney(order.amountCents, order.currency)}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
