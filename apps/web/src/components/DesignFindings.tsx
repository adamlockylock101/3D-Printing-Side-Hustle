import { bySeverity } from "@/lib/findings";
import type { DesignFinding, Severity } from "@/lib/types";

const HEADINGS: Record<Severity, string> = {
  must_fix: "Needs fixing",
  advise: "Worth changing",
  info: "For your information",
};

const TONE: Record<Severity, string> = {
  must_fix: "border-bad/30 bg-bad/5",
  advise: "border-warn/30 bg-warn/5",
  info: "border-rule bg-transparent",
};

const BAND_TONE = {
  adequate: "text-muted",
  marginal: "text-warn",
  weak: "text-bad",
} as const;

function formatValue(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(value < 1 ? 2 : 1);
}

function Measured({ finding }: { finding: DesignFinding }) {
  if (finding.measured === null || finding.threshold === null) return null;
  const unit = finding.unit ? ` ${finding.unit}` : "";
  return (
    <p className="tabular text-xs text-muted">
      Measured {formatValue(finding.measured)}
      {unit} &middot; limit {formatValue(finding.threshold)}
      {unit}
    </p>
  );
}

/**
 * The design checks, grouped by severity, each with what to change.
 *
 * `operator` shows the operator-only numbers (the interlayer safety factor). Customer pages never
 * set it, and the storefront strips those fields before they reach a browser in any case.
 */
export function DesignFindings({
  findings,
  operator = false,
}: {
  findings: DesignFinding[];
  operator?: boolean;
}) {
  const groups = bySeverity(findings);
  if (groups.length === 0) return null;

  return (
    <div className="space-y-4">
      {groups.map(([severity, group]) => (
        <section key={severity}>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
            {HEADINGS[severity]}
          </h3>
          <ul className="mt-2 space-y-2">
            {group.map((finding) => (
              <li
                key={`${finding.check}:${finding.message}`}
                className={`space-y-1.5 rounded-md border px-3 py-2 text-sm ${TONE[severity]}`}
              >
                <p className="font-medium">
                  {finding.message}
                  {finding.band && (
                    <span className={`ml-2 text-xs font-normal ${BAND_TONE[finding.band]}`}>
                      strength: {finding.band}
                    </span>
                  )}
                </p>
                <Measured finding={finding} />
                {finding.location && (
                  <p className="text-xs text-muted">Where: {finding.location.description}</p>
                )}
                <p className="text-muted">{finding.why}</p>
                {finding.fix !== "Nothing to change." && (
                  <p>
                    <span className="font-medium">What to change: </span>
                    {finding.fix}
                  </p>
                )}
                {operator && finding.operator_note && (
                  <p className="tabular rounded bg-rule/30 px-2 py-1 text-xs">
                    {finding.operator_note}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
