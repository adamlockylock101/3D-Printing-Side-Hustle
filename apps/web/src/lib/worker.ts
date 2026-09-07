import type {
  AnalyseResponse,
  AnswersResponse,
  IntakeResponse,
  PublicConfig,
  QuoteResponse,
  Recommendation,
  Requirements,
} from "./types";

const BASE = process.env.WORKER_URL ?? "http://localhost:8000";

export class WorkerError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "WorkerError";
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
      cache: "no-store",
    });
  } catch {
    // A worker that is down should read as "we can't quote right now", not as a stack trace.
    throw new WorkerError(
      "Our quoting service is not responding. Please try again in a moment.",
      503,
    );
  }

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new WorkerError(body?.detail ?? "That request could not be processed.", response.status);
  }
  return (await response.json()) as T;
}

export const worker = {
  async analyse(file: Blob, filename: string): Promise<AnalyseResponse> {
    const form = new FormData();
    form.append("file", file, filename);
    const response = await fetch(`${BASE}/analyse`, { method: "POST", body: form, cache: "no-store" });
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: string } | null;
      throw new WorkerError(body?.detail ?? "We could not read that file.", response.status);
    }
    return (await response.json()) as AnalyseResponse;
  },

  intake(text: string) {
    return call<IntakeResponse>("/intake", { method: "POST", body: JSON.stringify({ text }) });
  },

  answers(requirements: Requirements, answers: Record<string, unknown>) {
    return call<AnswersResponse>("/intake/answers", {
      method: "POST",
      body: JSON.stringify({ requirements, answers }),
    });
  },

  recommend(requirements: Requirements, geometry?: unknown) {
    return call<Recommendation>("/recommend", {
      method: "POST",
      body: JSON.stringify({ requirements, geometry }),
    });
  },

  quote(uploadId: string, requirements: Requirements, materialId?: string) {
    return call<QuoteResponse>("/quote", {
      method: "POST",
      body: JSON.stringify({ upload_id: uploadId, requirements, material_id: materialId ?? null }),
    });
  },

  config() {
    return call<PublicConfig>("/config");
  },

  materials() {
    return call<{ version: string; materials: Record<string, unknown>[] }>("/materials");
  },

  health() {
    return call<Record<string, unknown>>("/health");
  },
};
