import { QuoteFlow } from "@/components/QuoteFlow";

export const metadata = { title: "Get a quote" };

export default function QuotePage() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Get a quote</h1>
      <p className="mt-2 max-w-2xl text-muted">
        Upload your part and tell us how it will be used. You&rsquo;ll see the material we
        recommend, why, and what it costs &mdash; before you commit to anything.
      </p>
      <div className="mt-8">
        <QuoteFlow />
      </div>
    </div>
  );
}
