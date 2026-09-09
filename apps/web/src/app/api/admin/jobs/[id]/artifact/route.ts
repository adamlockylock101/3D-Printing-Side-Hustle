import { NextResponse } from "next/server";
import { isOperator } from "@/lib/admin-auth";
import { db } from "@/lib/db";
import { record } from "@/lib/events";

export const runtime = "nodejs";
export const maxDuration = 300;

/**
 * Slice an approved job and hand back the .3mf.
 *
 * This is the phase 2 handoff: you download the plate and send it to the printer yourself.
 * When the shop agent lands (phase 3) it claims the job and fetches this same artifact, so the
 * flow either side of it does not change. See docs/agent-contract.md.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!(await isOperator())) {
    return NextResponse.json({ error: "Not authorised." }, { status: 401 });
  }
  const { id } = await params;

  const job = await db.job.findUnique({
    where: { id },
    include: { order: { include: { quote: { include: { upload: true } } } } },
  });
  if (!job?.order.quote) {
    return NextResponse.json({ error: "No such job, or it has no quote." }, { status: 404 });
  }

  const recommendation = job.order.quote.recommendation as { print_settings?: object } | null;

  const response = await fetch(`${process.env.WORKER_URL ?? "http://localhost:8000"}/slice`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      upload_id: job.order.quote.upload.uploadId,
      material_id: job.materialId,
      settings: recommendation?.print_settings ?? {},
      job_ref: job.id,
    }),
    cache: "no-store",
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    return NextResponse.json(
      { error: body?.detail ?? "Slicing failed." },
      { status: response.status },
    );
  }

  // The format follows the slicer, not this route: PrusaSlicer emits G-code, Bambu Studio and
  // Orca emit a 3mf project. Hardcoding either one hands the operator a file whose name lies
  // about its contents, which no printer will accept.
  const upstreamType = response.headers.get("content-type") ?? "application/octet-stream";
  const extension = upstreamType.includes("3mf") ? "3mf" : "gcode";
  const stem = job.order.quote.upload.filename.replace(/\.[^.]+$/, "");
  const filename = `${stem}-${job.materialId}.${extension}`;

  await record("job", job.id, "job.artifact_produced", {
    materialId: job.materialId,
    format: extension,
  });

  return new NextResponse(response.body, {
    headers: {
      "content-type": upstreamType,
      "content-disposition": `attachment; filename="${filename}"`,
    },
  });
}
