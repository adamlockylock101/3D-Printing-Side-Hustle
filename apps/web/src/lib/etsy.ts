import { db } from "./db";
import { record } from "./events";

/**
 * Etsy order import.
 *
 * Etsy sells fixed-price listings, so an Etsy order arrives with money attached but no mesh and
 * no requirements. It lands in the same queue as a direct order, in AWAITING_FILES, and the
 * buyer gets pointed at the intake form. From the operator's side the two channels look
 * identical from that point on — see docs/decisions.md D3.
 *
 * Etsy API v3 needs both an app key and an OAuth token; the token expires and must be
 * refreshed, which is why this is a pull on a schedule rather than a webhook.
 */

const API = "https://openapi.etsy.com/v3/application";

interface EtsyTransaction {
  title: string;
  quantity: number;
}

interface EtsyReceipt {
  receipt_id: number;
  buyer_email: string;
  name: string;
  grandtotal: { amount: number; divisor: number; currency_code: string };
  status: string;
  message_from_buyer: string | null;
  transactions?: EtsyTransaction[];
}

export function etsyConfigured(): boolean {
  return Boolean(
    process.env.ETSY_API_KEY && process.env.ETSY_ACCESS_TOKEN && process.env.ETSY_SHOP_ID,
  );
}

async function fetchReceipts(): Promise<EtsyReceipt[]> {
  const response = await fetch(
    `${API}/shops/${process.env.ETSY_SHOP_ID}/receipts?was_paid=true&limit=50`,
    {
      headers: {
        "x-api-key": process.env.ETSY_API_KEY!,
        Authorization: `Bearer ${process.env.ETSY_ACCESS_TOKEN}`,
      },
      cache: "no-store",
    },
  );
  if (!response.ok) {
    throw new Error(`Etsy API returned ${response.status}: ${await response.text()}`);
  }
  const body = (await response.json()) as { results: EtsyReceipt[] };
  return body.results ?? [];
}

export interface SyncResult {
  fetched: number;
  imported: number;
  skipped: number;
}

export async function syncEtsyOrders(): Promise<SyncResult> {
  if (!etsyConfigured()) {
    throw new Error("Etsy is not configured. Set ETSY_API_KEY, ETSY_ACCESS_TOKEN and ETSY_SHOP_ID.");
  }

  const receipts = await fetchReceipts();
  let imported = 0;
  let skipped = 0;

  for (const receipt of receipts) {
    const etsyReceiptId = String(receipt.receipt_id);
    const existing = await db.order.findUnique({ where: { etsyReceiptId } });
    if (existing) {
      skipped += 1;
      continue;
    }

    const customer = await db.customer.upsert({
      where: { email: receipt.buyer_email },
      update: { name: receipt.name },
      create: { email: receipt.buyer_email, name: receipt.name },
    });

    const amountCents = Math.round(
      (receipt.grandtotal.amount / receipt.grandtotal.divisor) * 100,
    );

    const order = await db.order.create({
      data: {
        customerId: customer.id,
        channel: "ETSY",
        // No mesh and no requirements yet, so it cannot go into review.
        status: "AWAITING_FILES",
        etsyReceiptId,
        amountCents,
        currency: receipt.grandtotal.currency_code,
        operatorNotes: receipt.message_from_buyer ?? undefined,
      },
    });

    await record("order", order.id, "order.imported_from_etsy", {
      etsyReceiptId,
      amountCents,
      items: receipt.transactions?.map((t) => t.title) ?? [],
    });
    imported += 1;
  }

  return { fetched: receipts.length, imported, skipped };
}
