import { NextResponse } from "next/server";
import { z } from "zod";
import { db } from "@/lib/db";
import { record } from "@/lib/events";
import { toCents } from "@/lib/money";
import { worker, WorkerError } from "@/lib/worker";
import type { Requirements } from "@/lib/types";

export const runtime = "nodejs";
export const maxDuration = 120;

const Body = z.object({
  uploadId: z.string().min(1),
  filename: z.string().default("part.stl"),
  bytes: z.number().int().nonnegative().default(0),
  requirements: z.record(z.unknown()),
  materialId: z.string().optional(),
});

export async function POST(request: Request) {
  const parsed = Body.safeParse(await request.json());
  if (!parsed.success) {
    return NextResponse.json({ error: "That quote request was incomplete." }, { status: 400 });
  }
  const { uploadId, filename, bytes, materialId } = parsed.data;
  const requirements = parsed.data.requirements as unknown as Requirements;

  let result;
  try {
    result = await worker.quote(uploadId, requirements, materialId);
  } catch (error) {
    if (error instanceof WorkerError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("Quote failed", error);
    return NextResponse.json({ error: "We could not price that part." }, { status: 500 });
  }

  // A declined recommendation is a real answer, not an error — return it with no quote.
  if (!result.quote || result.recommendation.declined) {
    return NextResponse.json({ ...result, quoteId: null });
  }

  // Persistence is best-effort so a database outage degrades to "quote shown, can't check out"
  // rather than taking the whole quoting flow down.
  let quoteId: string | null = null;
  try {
    const upload = await db.upload.create({
      data: {
        filename,
        uploadId,
        bytes,
        geometry: result.geometry as unknown as object,
      },
    });

    const quote = await db.quote.create({
      data: {
        uploadId: upload.id,
        requirements: requirements as unknown as object,
        recommendation: result.recommendation as unknown as object,
        materialTableVersion: result.recommendation.table_version,
        materialId: result.quote.material_id,
        overridden: result.overridden,
        quantity: result.quote.quantity,
        printMinutes: result.quote.print_minutes_each,
        filamentGrams: result.quote.filament_g_each,
        priceCents: toCents(result.quote.total_price),
        currency: result.quote.currency,
        estimated: result.quote.estimated,
        breakdown: result.quote.lines as unknown as object,
        expiresAt: new Date(Date.now() + result.quote.expires_hours * 3600 * 1000),
      },
    });
    quoteId = quote.id;

    await record("quote", quote.id, "quote.created", {
      materialId: result.quote.material_id,
      recommended: result.recommendation.primary.material_id,
      overridden: result.overridden,
      priceCents: toCents(result.quote.total_price),
      estimated: result.quote.estimated,
      tableVersion: result.recommendation.table_version,
      requiresManualReview: result.quote.requires_manual_review,
    });
  } catch (error) {
    console.error("Could not persist quote", error);
  }

  return NextResponse.json({ ...result, quoteId });
}
