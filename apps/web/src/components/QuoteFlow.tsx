"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { GeometrySummary } from "./GeometrySummary";
import { MeshPreview } from "./MeshPreview";
import { QuoteBreakdown } from "./QuoteBreakdown";
import { RecommendationCard } from "./RecommendationCard";
import type {
  AnalyseResponse,
  FollowUp,
  IntakeResponse,
  QuoteResponse,
  Requirements,
} from "@/lib/types";

type Step = "upload" | "describe" | "questions" | "quote" | "checkout" | "done";

const STEP_LABELS: Record<Exclude<Step, "done">, string> = {
  upload: "Your part",
  describe: "What it's for",
  questions: "A few details",
  quote: "Material and price",
  checkout: "Order",
};

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await response.json()) as T & { error?: string };
  if (!response.ok) throw new Error(data.error ?? "Something went wrong.");
  return data;
}

export function QuoteFlow() {
  const [step, setStep] = useState<Step>("upload");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<AnalyseResponse | null>(null);

  const [description, setDescription] = useState("");
  const [intake, setIntake] = useState<IntakeResponse | null>(null);
  const [requirements, setRequirements] = useState<Requirements | null>(null);
  const [followUps, setFollowUps] = useState<FollowUp[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const [result, setResult] = useState<(QuoteResponse & { quoteId: string | null }) | null>(null);
  const [materialId, setMaterialId] = useState<string>("");

  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [orderToken, setOrderToken] = useState<string | null>(null);
  const [manualPaymentMessage, setManualPaymentMessage] = useState<string | null>(null);

  const fileInput = useRef<HTMLInputElement>(null);

  const run = useCallback(async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }, []);

  // --- step 1: upload -----------------------------------------------------------------

  const handleFile = (chosen: File | null) => {
    if (!chosen) return;
    setFile(chosen);
    void run(async () => {
      const form = new FormData();
      form.append("file", chosen);
      const response = await fetch("/api/analyse", { method: "POST", body: form });
      const data = (await response.json()) as AnalyseResponse & { error?: string };
      if (!response.ok) throw new Error(data.error ?? "We could not read that file.");
      setAnalysis(data);
      setStep("describe");
    });
  };

  // --- step 2: describe ---------------------------------------------------------------

  const submitDescription = () =>
    run(async () => {
      const data = await postJson<IntakeResponse>("/api/intake", { text: description });
      setIntake(data);
      if (!data.allowed) return; // declined; the message renders below
      setRequirements(data.requirements);
      setFollowUps(data.follow_ups);
      setStep(data.follow_ups.length ? "questions" : "quote");
      if (!data.follow_ups.length) await requestQuote(data.requirements);
    });

  // --- step 3: questions --------------------------------------------------------------

  const submitAnswers = () =>
    run(async () => {
      const data = await postJson<{ requirements: Requirements; follow_ups: FollowUp[] }>(
        "/api/intake/answers",
        { requirements, answers },
      );
      setRequirements(data.requirements);
      setAnswers({});
      // Answering can open up newly relevant questions (say, load details once a load exists),
      // so only move on when the list is genuinely empty.
      if (data.follow_ups.length && data.follow_ups.some((q) => !(q.field in answers))) {
        setFollowUps(data.follow_ups);
        return;
      }
      setFollowUps([]);
      setStep("quote");
      await requestQuote(data.requirements);
    });

  const skipQuestions = () =>
    run(async () => {
      setFollowUps([]);
      setStep("quote");
      await requestQuote(requirements!);
    });

  // --- step 4: quote ------------------------------------------------------------------

  const requestQuote = async (reqs: Requirements, overrideMaterialId?: string) => {
    if (!analysis) return;
    const data = await postJson<QuoteResponse & { quoteId: string | null }>("/api/quote", {
      uploadId: analysis.upload_id,
      filename: analysis.filename,
      bytes: file?.size ?? 0,
      requirements: reqs,
      materialId: overrideMaterialId,
    });
    setResult(data);
    setMaterialId(data.quote?.material_id ?? data.recommendation.primary.material_id);
  };

  const chooseMaterial = (chosen: string) => {
    if (chosen === materialId || !requirements) return;
    setMaterialId(chosen);
    void run(() => requestQuote(requirements, chosen));
  };

  // --- step 5: checkout ---------------------------------------------------------------

  const submitOrder = () =>
    run(async () => {
      if (!result?.quoteId) {
        throw new Error(
          "We couldn't save that quote. Please email us and we'll pick it up by hand.",
        );
      }
      const data = await postJson<{
        orderToken: string;
        checkoutUrl: string | null;
        message?: string;
      }>("/api/checkout", { quoteId: result.quoteId, email, name, notes });

      if (data.checkoutUrl) {
        window.location.href = data.checkoutUrl;
        return;
      }
      setOrderToken(data.orderToken);
      setManualPaymentMessage(data.message ?? null);
      setStep("done");
    });

  const steps = useMemo(() => Object.entries(STEP_LABELS) as [Exclude<Step, "done">, string][], []);
  const currentIndex = steps.findIndex(([key]) => key === step);

  return (
    <div className="space-y-8">
      <ol className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        {steps.map(([key, label], index) => (
          <li
            key={key}
            className={
              index === currentIndex
                ? "font-medium text-accent"
                : index < currentIndex
                  ? "text-ink"
                  : "text-muted"
            }
          >
            {index + 1}. {label}
          </li>
        ))}
      </ol>

      {error && (
        <p className="rounded-md border border-bad/30 bg-bad/5 px-4 py-3 text-sm text-bad">
          {error}
        </p>
      )}

      {/* ---------------------------------------------------------------- upload ------ */}
      {step === "upload" && (
        <section className="card">
          <h2 className="text-lg font-semibold">Upload your part</h2>
          <p className="mt-1 text-sm text-muted">
            STL, 3MF, OBJ or PLY, up to 200 MB. We&rsquo;ll check it and show you what we see
            before you commit to anything.
          </p>
          <div
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              handleFile(event.dataTransfer.files[0] ?? null);
            }}
            className="mt-5 rounded-lg border-2 border-dashed border-rule px-6 py-12 text-center"
          >
            <p className="text-sm text-muted">Drag a file here, or</p>
            <button
              type="button"
              className="btn-secondary mt-3"
              onClick={() => fileInput.current?.click()}
              disabled={busy}
            >
              {busy ? "Reading your model..." : "Choose a file"}
            </button>
            <input
              ref={fileInput}
              type="file"
              accept=".stl,.3mf,.obj,.ply,.off"
              className="hidden"
              onChange={(event) => handleFile(event.target.files?.[0] ?? null)}
            />
          </div>
        </section>
      )}

      {/* --------------------------------------------------------------- describe ----- */}
      {analysis && step !== "upload" && (
        <section className="card">
          <div className="flex items-start justify-between gap-6">
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-semibold">{analysis.filename}</h2>
              <div className="mt-4">
                <GeometrySummary geometry={analysis.geometry} />
              </div>
            </div>
            <MeshPreview file={file} className="hidden h-48 w-48 shrink-0 rounded-md bg-rule/20 sm:block" />
          </div>
        </section>
      )}

      {step === "describe" && (
        <section className="card">
          <h2 className="text-lg font-semibold">What&rsquo;s this part for?</h2>
          <p className="mt-1 text-sm text-muted">
            In your own words. What does it attach to, what does it have to survive, does anything
            push or pull on it? A couple of sentences is plenty &mdash; we&rsquo;ll ask about
            anything that would change the material.
          </p>
          <textarea
            className="input mt-4 min-h-32"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="e.g. It's a bracket that holds a 5 kg sign on an outside wall. It'll be in the sun all year and I need it to last."
          />
          <div className="mt-4 flex items-center gap-3">
            <button
              type="button"
              className="btn-primary"
              onClick={submitDescription}
              disabled={busy || description.trim().length < 3}
            >
              {busy ? "Reading..." : "Continue"}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() =>
                run(async () => {
                  const data = await postJson<IntakeResponse>("/api/intake", { text: "" });
                  setIntake(data);
                  setRequirements(data.requirements);
                  setFollowUps(data.follow_ups);
                  setStep("questions");
                })
              }
              disabled={busy}
            >
              I&rsquo;d rather answer questions
            </button>
          </div>

          {intake && !intake.allowed && (
            <p className="mt-4 rounded-md border border-bad/30 bg-bad/5 px-4 py-3 text-sm text-bad">
              {intake.declined_reason}
            </p>
          )}
        </section>
      )}

      {/* -------------------------------------------------------------- questions ----- */}
      {step === "questions" && (
        <section className="card">
          {intake?.summary && intake.extracted_by !== "heuristic" && (
            <div className="mb-6 rounded-md border border-rule bg-rule/20 px-4 py-3">
              <h3 className="text-sm font-semibold">Here&rsquo;s what we understood</h3>
              <p className="mt-1 text-sm">{intake.summary}</p>
              {intake.assumptions.length > 0 && (
                <>
                  <p className="mt-3 text-xs font-medium uppercase tracking-wide text-muted">
                    We assumed
                  </p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-muted">
                    {intake.assumptions.map((assumption) => (
                      <li key={assumption}>{assumption}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          <h2 className="text-lg font-semibold">A few details</h2>
          <p className="mt-1 text-sm text-muted">
            Only the ones that would change our answer. Skip any you&rsquo;re unsure about.
          </p>

          <div className="mt-6 space-y-6">
            {followUps.map((question) => (
              <fieldset key={question.field}>
                <legend className="label">{question.question}</legend>
                {question.help_text && (
                  <p className="mt-1 text-sm text-muted">{question.help_text}</p>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  {question.options.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      className={`chip ${
                        answers[question.field] === option.value ? "chip-selected" : ""
                      }`}
                      onClick={() =>
                        setAnswers((current) => ({ ...current, [question.field]: option.value }))
                      }
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </fieldset>
            ))}

            <fieldset>
              <legend className="label">How many do you need?</legend>
              <input
                type="number"
                min={1}
                className="input mt-2 w-32"
                value={answers["quantity"] ?? String(requirements?.quantity ?? 1)}
                onChange={(event) =>
                  setAnswers((current) => ({ ...current, quantity: event.target.value }))
                }
              />
            </fieldset>
          </div>

          <div className="mt-6 flex items-center gap-3">
            <button type="button" className="btn-primary" onClick={submitAnswers} disabled={busy}>
              {busy ? "Working it out..." : "See the recommendation"}
            </button>
            <button type="button" className="btn-secondary" onClick={skipQuestions} disabled={busy}>
              Skip the rest
            </button>
          </div>
        </section>
      )}

      {/* ------------------------------------------------------------------ quote ----- */}
      {step === "quote" && (
        <section className="card">
          {busy && !result && <p className="text-sm text-muted">Working out the material...</p>}

          {result?.recommendation.declined && (
            <div>
              <h2 className="text-lg font-semibold">We can&rsquo;t print this one</h2>
              <p className="mt-2 text-sm leading-relaxed">
                {result.recommendation.declined_reason}
              </p>
              <p className="mt-3 text-sm text-muted">
                If any of the requirements can flex, adjust your answers and we&rsquo;ll look
                again. We&rsquo;d rather turn the job down than sell you a part that fails.
              </p>
              <button
                type="button"
                className="btn-secondary mt-4"
                onClick={() => setStep("questions")}
              >
                Change my answers
              </button>
            </div>
          )}

          {result && !result.recommendation.declined && result.quote && (
            <div className="space-y-8">
              <div>
                <h2 className="text-lg font-semibold">Our recommendation</h2>
                <div className="mt-4">
                  <RecommendationCard
                    recommendation={result.recommendation}
                    selectedMaterialId={materialId}
                    onSelectMaterial={chooseMaterial}
                  />
                </div>
              </div>

              {result.overridden && result.override_acknowledgement && (
                <p className="rounded-md border border-warn/30 bg-warn/5 px-4 py-3 text-sm text-warn">
                  {result.override_acknowledgement}
                </p>
              )}

              <div className="border-t border-rule pt-6">
                <h2 className="text-lg font-semibold">Your price</h2>
                <div className="mt-4">
                  <QuoteBreakdown quote={result.quote} />
                </div>
              </div>

              <button type="button" className="btn-primary" onClick={() => setStep("checkout")}>
                Continue to order
              </button>
            </div>
          )}
        </section>
      )}

      {/* --------------------------------------------------------------- checkout ----- */}
      {step === "checkout" && result?.quote && (
        <section className="card">
          <h2 className="text-lg font-semibold">Where should we send it?</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                type="email"
                required
                className="input mt-1"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="name">
                Name
              </label>
              <input
                id="name"
                className="input mt-1"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
          </div>
          <div className="mt-4">
            <label className="label" htmlFor="notes">
              Anything else we should know? <span className="font-normal text-muted">(optional)</span>
            </label>
            <textarea
              id="notes"
              className="input mt-1 min-h-20"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Colour preference, deadline, which way is up..."
            />
          </div>

          <p className="mt-4 text-sm text-muted">
            You&rsquo;ll pay {result.quote.currency}{" "}
            {result.quote.total_price.toFixed(2)} now. We review every job by hand before it goes
            to the printer &mdash; if anything looks wrong, we&rsquo;ll email you before we start,
            and refund in full if we can&rsquo;t do it.
          </p>

          <button
            type="button"
            className="btn-primary mt-5"
            onClick={submitOrder}
            disabled={busy || !email.includes("@")}
          >
            {busy ? "Setting up payment..." : "Place order"}
          </button>
        </section>
      )}

      {/* ------------------------------------------------------------------- done ----- */}
      {step === "done" && orderToken && (
        <section className="card">
          <h2 className="text-lg font-semibold">Order received</h2>
          <p className="mt-2 text-sm">{manualPaymentMessage ?? "We'll be in touch shortly."}</p>
          <a className="btn-primary mt-4" href={`/orders/${orderToken}`}>
            Track this order
          </a>
        </section>
      )}
    </div>
  );
}
