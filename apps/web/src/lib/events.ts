import { db } from "./db";

/**
 * Append-only audit trail. Write one whenever something changes state or a decision is made.
 *
 * This is what answers "why did my part cost that" three weeks later, and it is the raw
 * material for the per-material failure rates that eventually replace the hard-coded risk
 * constants in the pricing model.
 */
export async function record(
  entity: string,
  entityId: string,
  type: string,
  payload: Record<string, unknown> = {},
) {
  try {
    await db.event.create({ data: { entity, entityId, type, payload: payload as object } });
  } catch (error) {
    // An audit write must never fail the operation it is describing.
    console.error("Failed to record event", { entity, entityId, type, error });
  }
}
