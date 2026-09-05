import { cookies } from "next/headers";
import { timingSafeEqual } from "crypto";

export const ADMIN_COOKIE = "printshop_admin";

/**
 * A single shared secret, which is proportionate while there is exactly one operator.
 * Swap this for real auth before anyone else gets a login — see docs/open-questions.md.
 */
export function checkToken(candidate: string | undefined | null): boolean {
  const expected = process.env.ADMIN_TOKEN;
  if (!expected || !candidate) return false;
  const a = Buffer.from(candidate);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

export async function isOperator(): Promise<boolean> {
  const store = await cookies();
  return checkToken(store.get(ADMIN_COOKIE)?.value);
}

export function checkAgentToken(header: string | null): boolean {
  const expected = process.env.AGENT_TOKEN;
  if (!expected || !header) return false;
  const token = header.replace(/^Bearer\s+/i, "");
  const a = Buffer.from(token);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}
