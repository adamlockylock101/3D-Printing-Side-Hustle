import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Materials-led 3D printing",
  description:
    "Upload your part, tell us what it has to survive, and get a material recommendation with " +
    "the engineering reasoning behind it — plus an instant quote.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-rule bg-white">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
            <Link href="/" className="font-semibold tracking-tight">
              Materials-led 3D printing
            </Link>
            <nav className="flex items-center gap-6 text-sm">
              <Link href="/materials" className="text-muted hover:text-ink">
                Materials
              </Link>
              <Link href="/quote" className="btn-primary">
                Get a quote
              </Link>
            </nav>
          </div>
        </header>

        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>

        <footer className="mt-16 border-t border-rule bg-white">
          <div className="mx-auto max-w-5xl px-6 py-8 text-sm text-muted">
            <p className="max-w-2xl">
              Printed parts are anisotropic: they typically reach 40&ndash;80% of the datasheet
              figure across layer lines. Our recommendations are engineering guidance for the use
              you describe, not a certification. We do not print firearm components, implantable
              or tissue-contacting medical parts, or safety-critical structural parts.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
