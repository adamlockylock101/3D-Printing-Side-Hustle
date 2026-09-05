import { NextResponse } from "next/server";
import { worker, WorkerError } from "@/lib/worker";

export const runtime = "nodejs";
export const revalidate = 300;

export async function GET() {
  try {
    return NextResponse.json(await worker.config());
  } catch (error) {
    const status = error instanceof WorkerError ? error.status : 500;
    return NextResponse.json({ error: "Configuration unavailable." }, { status });
  }
}
