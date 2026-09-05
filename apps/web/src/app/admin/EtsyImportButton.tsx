"use client";

import { useState, useTransition } from "react";
import { importEtsy } from "./actions";

export function EtsyImportButton() {
  const [message, setMessage] = useState<string | null>(null);
  const [pending, start] = useTransition();

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        className="btn-secondary"
        disabled={pending}
        onClick={() => start(async () => setMessage(await importEtsy()))}
      >
        {pending ? "Importing..." : "Import Etsy orders"}
      </button>
      {message && <span className="text-sm text-muted">{message}</span>}
    </div>
  );
}
