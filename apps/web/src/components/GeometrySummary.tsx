import type { GeometryReport } from "@/lib/types";

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
  return (
    <div>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Size" value={`${x.toFixed(0)} x ${y.toFixed(0)} x ${z.toFixed(0)} mm`} />
        <Stat label="Volume" value={`${(geometry.volume_mm3 / 1000).toFixed(1)} cm3`} />
        <Stat
          label="Thinnest wall"
          value={geometry.min_wall_mm ? `${geometry.min_wall_mm.toFixed(2)} mm` : "not measured"}
        />
        <Stat label="Needs support" value={`${Math.round(geometry.overhang_fraction * 100)}%`} />
      </dl>

      {geometry.warnings.length > 0 && (
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
      )}
    </div>
  );
}
