"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { ADMIN_COOKIE, checkToken, isOperator } from "@/lib/admin-auth";
import { db } from "@/lib/db";
import { record } from "@/lib/events";
import { syncEtsyOrders } from "@/lib/etsy";

export async function signIn(_state: string | null, form: FormData): Promise<string | null> {
  const token = String(form.get("token") ?? "");
  if (!checkToken(token)) return "That token is not right.";
  const store = await cookies();
  store.set(ADMIN_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  revalidatePath("/admin");
  return null;
}

export async function signOut() {
  (await cookies()).delete(ADMIN_COOKIE);
  revalidatePath("/admin");
}

async function requireOperator() {
  if (!(await isOperator())) throw new Error("Not authorised.");
}

/**
 * Approve a job. This is the one mandatory human step in the whole pipeline, so it does the
 * things that only matter once someone has actually looked: it records who approved what, and
 * it creates the print job the shop agent will later claim.
 */
export async function approveOrder(orderId: string, form: FormData) {
  await requireOperator();
  const materialId = String(form.get("materialId") ?? "");
  const notes = String(form.get("notes") ?? "").trim();

  const order = await db.order.findUnique({ where: { id: orderId }, include: { quote: true } });
  if (!order) throw new Error("No such order.");
  if (!order.quote) throw new Error("That order has no quote attached yet.");

  const chosen = materialId || order.quote.materialId;
  const changed = chosen !== order.quote.materialId;

  await db.$transaction([
    db.order.update({
      where: { id: orderId },
      data: { status: "APPROVED", operatorNotes: notes || order.operatorNotes },
    }),
    db.job.create({
      data: { orderId, materialId: chosen, state: "QUEUED" },
    }),
  ]);

  await record("order", orderId, "order.approved", {
    materialId: chosen,
    changedFromQuote: changed,
    quotedMaterialId: order.quote.materialId,
    notes: notes || null,
  });
  revalidatePath("/admin");
  revalidatePath(`/admin/orders/${orderId}`);
}

export async function declineOrder(orderId: string, form: FormData) {
  await requireOperator();
  const reason = String(form.get("reason") ?? "").trim();
  if (!reason) throw new Error("Give the customer a reason.");

  await db.order.update({
    where: { id: orderId },
    data: { status: "DECLINED", declineReason: reason },
  });
  await record("order", orderId, "order.declined", { reason });
  revalidatePath("/admin");
  revalidatePath(`/admin/orders/${orderId}`);
}

export async function advanceOrder(orderId: string, status: string) {
  await requireOperator();
  await db.order.update({
    where: { id: orderId },
    // The enum is validated by Prisma; an unknown value throws rather than corrupting state.
    data: { status: status as never },
  });
  await record("order", orderId, "order.status_changed", { status });
  revalidatePath("/admin");
  revalidatePath(`/admin/orders/${orderId}`);
}

export async function importEtsy(): Promise<string> {
  await requireOperator();
  try {
    const result = await syncEtsyOrders();
    revalidatePath("/admin");
    return `Fetched ${result.fetched}, imported ${result.imported}, already had ${result.skipped}.`;
  } catch (error) {
    return error instanceof Error ? error.message : "Etsy import failed.";
  }
}
