import { formatDuration } from "@/lib/money";
import type { Quote } from "@/lib/types";

export function QuoteBreakdown({ quote }: { quote: Quote }) {
  const money = (value: number) =>
    new Intl.NumberFormat("en-AU", { style: "currency", currency: quote.currency }).format(value);

  return (
    <div>
      <div className="flex items-baseline justify-between border-b border-rule pb-4">
        <div>
          <p className="text-sm text-muted">
            {quote.quantity} x {quote.material_name}
          </p>
          <p className="text-3xl font-semibold tabular">{money(quote.total_price)}</p>
          {quote.quantity > 1 && (
            <p className="text-sm text-muted tabular">{money(quote.unit_price)} each</p>
          )}
        </div>
        <div className="text-right text-sm text-muted tabular">
          <p>{formatDuration(quote.print_minutes_each)} print time each</p>
          <p>{quote.filament_g_each.toFixed(0)} g of material each</p>
        </div>
      </div>

      <table className="mt-4 w-full text-sm">
        <tbody>
          {quote.lines.map((line) => (
            <tr key={line.label} className="align-top">
              <th scope="row" className="w-40 py-2 pr-4 text-left font-medium">
                {line.label}
              </th>
              <td className="py-2 pr-4 text-muted">{line.detail}</td>
              <td className="tabular w-24 py-2 text-right">{money(line.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="mt-4 space-y-2 text-sm">
        {quote.estimated && (
          <p className="rounded-md border border-rule bg-rule/20 px-3 py-2 text-muted">
            Print time and material mass are estimated from the geometry. We confirm them against
            a real slice before the job goes to the printer, and we&rsquo;ll tell you if anything
            moves.
          </p>
        )}
        {quote.minimum_applied && (
          <p className="text-muted">
            Our minimum order applies here &mdash; handling a single small part costs about the
            same however short the print is.
          </p>
        )}
        {quote.requires_manual_review && (
          <p className="rounded-md border border-warn/30 bg-warn/5 px-3 py-2 text-warn">
            {quote.manual_review_reason} We&rsquo;ll confirm the price by email before charging
            you anything.
          </p>
        )}
        <p className="text-muted">
          This quote holds for {Math.round(quote.expires_hours / 24)} days.
        </p>
      </div>
    </div>
  );
}
