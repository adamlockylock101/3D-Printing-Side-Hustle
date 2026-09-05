import Link from "next/link";

export default function NotFound() {
  return (
    <div className="max-w-lg">
      <h1 className="text-2xl font-semibold tracking-tight">We couldn&rsquo;t find that</h1>
      <p className="mt-2 text-muted">
        The link may have expired, or been mistyped. If you were looking for an order, check the
        link in your confirmation email.
      </p>
      <Link href="/" className="btn-primary mt-6">
        Back to the start
      </Link>
    </div>
  );
}
