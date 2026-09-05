import { NextResponse } from "next/server";
import type Stripe from "stripe";
import { db } from "@/lib/db";
import { record } from "@/lib/events";
import { stripe } from "@/lib/stripe";

export const runtime = "nodejs";

/**
 * Payment confirmation is the moment an order enters the review queue.
 *
 * The signature check is not optional: without it anyone who finds this URL can mark orders
 * paid. Stripe needs the raw body to verify, so this route must not parse JSON first.
 */
export async function POST(request: Request) {
  const client = stripe();
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!client || !secret) {
    return NextResponse.json({ error: "Stripe is not configured." }, { status: 503 });
  }

  const signature = request.headers.get("stripe-signature");
  if (!signature) {
    return NextResponse.json({ error: "Missing signature." }, { status: 400 });
  }

  const raw = await request.text();
  let event: Stripe.Event;
  try {
    event = client.webhooks.constructEvent(raw, signature, secret);
  } catch (error) {
    console.error("Stripe signature verification failed", error);
    return NextResponse.json({ error: "Invalid signature." }, { status: 400 });
  }

  if (event.type === "checkout.session.completed") {
    const session = event.data.object as Stripe.Checkout.Session;
    const orderId = session.metadata?.orderId;
    if (orderId) {
      // Idempotent: Stripe retries, and a retry must not re-run the transition.
      const order = await db.order.findUnique({ where: { id: orderId } });
      if (order && order.status === "AWAITING_PAYMENT") {
        await db.order.update({
          where: { id: orderId },
          data: {
            status: "IN_REVIEW",
            stripePaymentIntentId:
              typeof session.payment_intent === "string" ? session.payment_intent : null,
            shippingAddress: (session.shipping_details ??
              session.customer_details ??
              null) as unknown as object,
          },
        });
        await record("order", orderId, "order.paid", {
          sessionId: session.id,
          amountTotal: session.amount_total,
        });
      }
    }
  }

  if (event.type === "checkout.session.expired") {
    const session = event.data.object as Stripe.Checkout.Session;
    const orderId = session.metadata?.orderId;
    if (orderId) {
      await record("order", orderId, "order.checkout_expired", { sessionId: session.id });
    }
  }

  return NextResponse.json({ received: true });
}
