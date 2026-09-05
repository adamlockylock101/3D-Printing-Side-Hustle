import Stripe from "stripe";

let cached: Stripe | null = null;

/**
 * Returns null when Stripe is not configured, so the app runs (and quotes) without keys —
 * useful in phase 0 where quotes go out by email and payment is taken by hand.
 */
export function stripe(): Stripe | null {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) return null;
  cached ??= new Stripe(key, { apiVersion: "2024-12-18.acacia" });
  return cached;
}

export function siteUrl(): string {
  return process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
}
