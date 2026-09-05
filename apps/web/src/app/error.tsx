"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="max-w-lg">
      <h1 className="text-2xl font-semibold tracking-tight">Something went wrong at our end</h1>
      <p className="mt-2 text-muted">
        Not your fault. Try again in a moment &mdash; if it keeps happening, email us and
        we&rsquo;ll sort it out by hand.
      </p>
      <button type="button" onClick={reset} className="btn-primary mt-6">
        Try again
      </button>
    </div>
  );
}
