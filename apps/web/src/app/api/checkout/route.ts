import { NextResponse } from "next/server";
import { z } from "zod";
import { db } from "@/lib/db";
import { record } from "@/lib/events";
import { formatDuration } from "@/lib/money";
import { siteUrl, stripe } from "@/lib/stripe";

export const runtime = "nodejs";

const Body = z.object({
  quoteId: z.string().min(1),
  email: z.string().email(),
  name: z.string().max(200).optional(),
  notes: z.string().max(2000).optional(),
});

export async function POST(request: Request) {
  const parsed = Body.safeParse(await request.json());
  if (!parsed.success) {
    return NextResponse.json({ error: "We need a valid email address." }, { status: 400 });
  }

  try {
    return await createOrder(parsed.data);
  } catch (error) {
    // Quoting degrades gracefully without a database; taking money must not. Fail clearly and
    // tell the customer their quote is still good, rather than leaking a stack trace.
    console.error("Checkout failed", error);
    return NextResponse.json(
      {
        error:
          "We can't take orders at the moment. Your quote is still valid — please try again " +
          "shortly, or email us and we'll pick it up by hand.",
      },
      { status: 503 },
    );
  }
}

async function createOrder({
  quoteId,
  email,
  name,
  notes,
}: z.infer<typeof Body>): Promise<NextResponse> {

  const quote = await db.quote.findUnique({ where: { id: quoteId }, include: { order: true } });
  if (!quote) {
    return NextResponse.json({ error: "That quote could not be found." }, { status: 404 });
  }
  if (quote.order) {
    return NextResponse.json({ error: "That quote has already been ordered." }, { status: 409 });
  }
  if (quote.expiresAt < new Date()) {
    return NextResponse.json(
      { error: "That quote has expired. Please request a fresh one — filament prices move." },
      { status: 410 },
    );
  }

  const customer = await db.customer.upsert({
    where: { email },
    update: name ? { name } : {},
    create: { email, name },
  });

  const order = await db.order.create({
    data: {
      quoteId: quote.id,
      customerId: customer.id,
      channel: "DIRECT",
      status: "AWAITING_PAYMENT",
      amountCents: quote.priceCents,
      currency: quote.currency,
      operatorNotes: notes,
    },
  });
  await record("order", order.id, "order.created", { quoteId: quote.id, channel: "DIRECT" });

  const client = stripe();
  if (!client) {
    // No Stripe keys configured: this is the phase 0 path, where you invoice by hand.
    await record("order", order.id, "order.manual_payment_required", {});
    return NextResponse.json({
      orderToken: order.publicToken,
      checkoutUrl: null,
      message:
        "Your order is recorded. We'll email a payment link shortly — online checkout isn't " +
        "switched on yet.",
    });
  }

  const session = await client.checkout.sessions.create({
    mode: "payment",
    customer_email: email,
    // Collect the delivery address here rather than in our own form: Stripe validates it and
    // we never handle it directly.
    shipping_address_collection: { allowed_countries: ["AU", "NZ"] },
    phone_number_collection: { enabled: true },
    line_items: [
      {
        quantity: 1,
        price_data: {
          currency: quote.currency.toLowerCase(),
          unit_amount: quote.priceCents,
          product_data: {
            name: `3D printing — ${quote.quantity} x ${quote.materialId.toUpperCase()}`,
            description: `${formatDuration(quote.printMinutes)} print time each, ${Math.round(
              quote.filamentGrams,
            )} g each.`,
          },
        },
      },
    ],
    success_url: `${siteUrl()}/orders/${order.publicToken}?paid=1`,
    cancel_url: `${siteUrl()}/quote?cancelled=1`,
    metadata: { orderId: order.id, quoteId: quote.id },
  });

  await db.order.update({
    where: { id: order.id },
    data: { stripeSessionId: session.id },
  });

  return NextResponse.json({ orderToken: order.publicToken, checkoutUrl: session.url });
}
