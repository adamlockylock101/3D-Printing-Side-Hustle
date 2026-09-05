import Link from "next/link";

const STEPS = [
  {
    title: "Upload your part",
    body: "STL, 3MF, OBJ or PLY. We check it for holes, thin walls, scale mistakes and whether it fits the build volume before you pay for anything.",
  },
  {
    title: "Tell us what it's for",
    body: "In your own words. What it attaches to, what it has to survive, how much load it takes. We ask a few follow-ups only where the answer would change the material.",
  },
  {
    title: "Get a material and a price",
    body: "A recommendation with the reasoning, two alternates with their trade-offs, what we ruled out and why, and how the part should be oriented on the plate.",
  },
];

const DIFFERENCES = [
  {
    heading: "The reasoning comes with it",
    body: "Every quote says which properties decided the material and what was ruled out. If you disagree, you can see exactly where we'd differ — and override it.",
  },
  {
    heading: "Orientation is half the strength",
    body: "An FDM part can be twice as strong depending on how it sits on the plate. We tell you which way your load should run relative to the layer lines. Most services don't mention it.",
  },
  {
    heading: "Priced honestly",
    body: "Material, machine time, labour and a failure allowance, itemised. Difficult geometry costs more because it fails more often, and we show you that rather than burying it.",
  },
];

export default function Home() {
  return (
    <div className="space-y-16">
      <section className="max-w-2xl">
        <h1 className="text-4xl font-semibold leading-tight tracking-tight">
          Tell us what the part has to survive.
          <br />
          We&rsquo;ll tell you what it should be made of.
        </h1>
        <p className="mt-5 text-lg leading-relaxed text-muted">
          A 3D printing service run by a materials engineer. Upload your model, describe how it
          will be used, and get a material recommendation with the engineering behind it &mdash;
          along with an instant, itemised price.
        </p>
        <div className="mt-7 flex flex-wrap items-center gap-3">
          <Link href="/quote" className="btn-primary px-6 py-3 text-base">
            Upload a part
          </Link>
          <Link href="/materials" className="btn-secondary px-6 py-3 text-base">
            Browse materials
          </Link>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">How it works</h2>
        <ol className="mt-5 grid gap-5 md:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="card">
              <span className="text-sm font-medium text-accent">Step {index + 1}</span>
              <h3 className="mt-1 font-semibold">{step.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
          What&rsquo;s different here
        </h2>
        <div className="mt-5 grid gap-5 md:grid-cols-3">
          {DIFFERENCES.map((item) => (
            <div key={item.heading} className="card">
              <h3 className="font-semibold">{item.heading}</h3>
              <p className="mt-2 text-sm leading-relaxed text-muted">{item.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="card bg-accentSoft">
        <h2 className="font-semibold">Not sure a printed part is the right answer?</h2>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed">
          Sometimes it isn&rsquo;t. If your part needs a tolerance tighter than about 0.15 mm, has
          to be certified, or has to hold a load where failure hurts someone, we&rsquo;ll say so
          rather than take the order. That answer is free.
        </p>
      </section>
    </div>
  );
}
