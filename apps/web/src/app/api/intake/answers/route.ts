import { NextResponse } from "next/server";
import { worker, WorkerError } from "@/lib/worker";
import type { Requirements } from "@/lib/types";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const body = (await request.json()) as {
    requirements: Requirements;
    answers: Record<string, unknown>;
  };

  try {
    return NextResponse.json(await worker.answers(body.requirements, body.answers ?? {}));
  } catch (error) {
    if (error instanceof WorkerError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("Applying answers failed", error);
    return NextResponse.json({ error: "We could not process that." }, { status: 500 });
  }
}
