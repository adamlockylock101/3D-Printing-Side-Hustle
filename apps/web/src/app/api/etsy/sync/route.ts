import { NextResponse } from "next/server";
import { isOperator } from "@/lib/admin-auth";
import { etsyConfigured, syncEtsyOrders } from "@/lib/etsy";

export const runtime = "nodejs";
export const maxDuration = 60;

/**
 * Pull paid Etsy receipts into the queue. Run on a schedule (Vercel Cron, or any cron hitting
 * this route with the operator cookie) — Etsy has no order webhook worth relying on.
 */
export async function POST() {
  if (!(await isOperator())) {
    return NextResponse.json({ error: "Not authorised." }, { status: 401 });
  }
  if (!etsyConfigured()) {
    return NextResponse.json(
      { error: "Etsy is not configured. Set ETSY_API_KEY, ETSY_ACCESS_TOKEN and ETSY_SHOP_ID." },
      { status: 503 },
    );
  }

  try {
    return NextResponse.json(await syncEtsyOrders());
  } catch (error) {
    console.error("Etsy sync failed", error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Etsy sync failed." },
      { status: 502 },
    );
  }
}
