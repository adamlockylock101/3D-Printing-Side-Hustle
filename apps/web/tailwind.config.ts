import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#12151a",
        paper: "#fbfaf8",
        rule: "#e3e0da",
        muted: "#6b7280",
        accent: "#b4530a",
        accentSoft: "#fdf1e7",
        ok: "#15803d",
        warn: "#b45309",
        bad: "#b91c1c",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
