import type { DesignFinding, GeometryReport, Severity } from "./types";

/**
 * Geometry with the operator-only detail removed.
 *
 * The numeric interlayer safety factor rests on provisional z-strength ratios, so it would read
 * as more precise than it is. Customers see the band and the fix; the stored copy keeps the
 * number for the operator. Everything that sends geometry to a browser goes through this.
 */
export function forCustomer<T extends { geometry: GeometryReport }>(response: T): T {
  const geometry = response.geometry;
  const findings = geometry.findings?.map((finding) => {
    const shown = { ...finding };
    delete shown.operator_note;
    return shown;
  });
  const orientation = geometry.orientation && {
    ...geometry.orientation,
    candidates: geometry.orientation.candidates.map((candidate) => {
      const shown = { ...candidate };
      delete shown.safety_factor;
      return shown;
    }),
  };
  return { ...response, geometry: { ...geometry, findings, orientation } };
}

export const SEVERITY_ORDER: Severity[] = ["must_fix", "advise", "info"];

export function bySeverity(findings: DesignFinding[]): [Severity, DesignFinding[]][] {
  const groups: [Severity, DesignFinding[]][] = SEVERITY_ORDER.map((severity) => [
    severity,
    findings.filter((f) => f.severity === severity),
  ]);
  return groups.filter(([, group]) => group.length > 0);
}
