import { NextResponse } from "next/server";
import { z } from "zod";
import { worker, WorkerError } from "@/lib/worker";

export const runtime = "nodejs";
export const maxDuration = 60;

const Body = z.object({ text: z.string().max(8000) });

export async function POST(request: Request) {
  const parsed = Body.safeParse(await request.json());
  if (!parsed.success) {
    return NextResponse.json({ error: "Tell us a little about the part." }, { status: 400 });
  }

  try {
    return NextResponse.json(await worker.intake(parsed.data.text));
  } catch (error) {
    if (error instanceof WorkerError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("Intake failed", error);
    return NextResponse.json({ error: "We could not process that." }, { status: 500 });
  }
}
