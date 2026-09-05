import { NextResponse } from "next/server";
import { worker, WorkerError } from "@/lib/worker";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(request: Request) {
  const form = await request.formData();
  const file = form.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "No file was uploaded." }, { status: 400 });
  }

  try {
    const result = await worker.analyse(file, file.name);
    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof WorkerError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("Analyse failed", error);
    return NextResponse.json({ error: "We could not read that file." }, { status: 500 });
  }
}
