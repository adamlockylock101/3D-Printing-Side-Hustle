import type { GeometryReport } from "@/lib/types";
import { DesignFindings } from "./DesignFindings";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="tabular mt-0.5 font-medium">{value}</dd>
    </div>
  );
}

export function GeometrySummary({ geometry }: { geometry: GeometryReport }) {
  const [x, y, z] = geometry.bbox_mm;
  // Once a quote has chosen the orientation, support is measured the way it will print.
  const support =
    geometry.orientation?.candidates.find((c) => c.face_down === geometry.orientation?.face_down)
      ?.support_fraction ?? geometry.overhang_fraction;

  return (
    <div>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Size" value={`${x.toFixed(0)} x ${y.toFixed(0)} x ${z.toFixed(0)} mm`} />
        <Stat label="Volume" value={`${(geometry.volume_mm3 / 1000).toFixed(1)} cm3`} />
        <Stat
          label="Thinnest wall"
          value={geometry.min_wall_mm ? `${geometry.min_wall_mm.toFixed(2)} mm` : "not measured"}
        />
        <Stat label="Needs support" value={`${Math.round(support * 100)}%`} />
      </dl>

      {geometry.findings ? (
        <div className="mt-4">
          <DesignFindings findings={geometry.findings} />
        </div>
      ) : (
        // Geometry stored before the design checks existed carries only the flat warnings.
        geometry.warnings.length > 0 && (
          <ul className="mt-4 space-y-2">
            {geometry.warnings.map((warning) => (
              <li
                key={warning}
                className="rounded-md border border-warn/30 bg-warn/5 px-3 py-2 text-sm text-warn"
              >
                {warning}
              </li>
            ))}
          </ul>
        )
      )}
    </div>
  );
}
