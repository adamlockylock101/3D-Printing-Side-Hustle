"use client";

import { useActionState } from "react";
import { signIn } from "./actions";

export function SignInForm() {
  const [error, action, pending] = useActionState(signIn, null);
  return (
    <form action={action} className="card max-w-sm">
      <h1 className="text-lg font-semibold">Operator sign in</h1>
      <label className="label mt-4" htmlFor="token">
        Token
      </label>
      <input id="token" name="token" type="password" className="input mt-1" autoFocus />
      {error && <p className="mt-2 text-sm text-bad">{error}</p>}
      <button type="submit" className="btn-primary mt-4" disabled={pending}>
        {pending ? "Checking..." : "Sign in"}
      </button>
    </form>
  );
}
