import { worker } from "@/lib/worker";

export const metadata = { title: "Materials" };
export const revalidate = 3600;

interface MaterialRow {
  id: string;
  name: string;
  process: string;
  tensile_mpa: number;
  elongation_pct: number;
  hdt_045_c: number;
  z_strength_ratio: number;
  uv_resistance: string;
  in_stock: boolean;
  notes: string;
}

export default async function MaterialsPage() {
  let rows: MaterialRow[] = [];
  let version = "";
  try {
    const data = await worker.materials();
    rows = data.materials as unknown as MaterialRow[];
    version = data.version;
  } catch {
    return (
      <p className="text-muted">
        Our materials data isn&rsquo;t loading right now. Please try again shortly.
      </p>
    );
  }

  const stocked = rows.filter((row) => row.in_stock);

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Materials we print</h1>
      <p className="mt-2 max-w-2xl text-muted">
        These are the materials we keep on the shelf. The engine that picks between them uses the
        full property table &mdash; including materials we don&rsquo;t stock, which it will
        recommend and flag when your part genuinely needs one.
      </p>

      <div className="mt-8 overflow-x-auto">
        <table className="w-full min-w-[46rem] text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-xs uppercase tracking-wide text-muted">
              <th className="py-2 pr-4 font-medium">Material</th>
              <th className="py-2 pr-4 font-medium">Tensile</th>
              <th className="py-2 pr-4 font-medium">Elongation</th>
              <th className="py-2 pr-4 font-medium">Heat (HDT)</th>
              <th className="py-2 pr-4 font-medium">Z strength</th>
              <th className="py-2 pr-4 font-medium">UV</th>
            </tr>
          </thead>
          <tbody>
            {stocked.map((row) => (
              <tr key={row.id} className="border-b border-rule align-top">
                <td className="py-3 pr-4">
                  <div className="font-medium">{row.name}</div>
                  <p className="mt-1 max-w-md text-muted">{row.notes}</p>
                </td>
                <td className="tabular py-3 pr-4">{row.tensile_mpa} MPa</td>
                <td className="tabular py-3 pr-4">{row.elongation_pct}%</td>
                <td className="tabular py-3 pr-4">{row.hdt_045_c} &deg;C</td>
                <td className="tabular py-3 pr-4">{Math.round(row.z_strength_ratio * 100)}%</td>
                <td className="py-3 pr-4 capitalize">{row.uv_resistance}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-8 max-w-2xl space-y-3 text-sm text-muted">
        <p>
          <strong className="text-ink">Z strength</strong> is how much of a material&rsquo;s
          in-plane strength survives across the layer lines. It is the number most services
          don&rsquo;t publish, and it is why orientation matters as much as material choice.
        </p>
        <p>
          Figures are typical published values for the grades we buy, and printed parts vary with
          orientation, settings and geometry. Property table version {version}.
        </p>
      </div>
    </div>
  );
}
