import { Fragment } from "react";

/**
 * Renders the small Markdown subset the selection engine emits: paragraphs, bullet lists,
 * `**bold**` and `_italic_`. A full Markdown dependency would be more than this needs, and
 * rendering only what we generate keeps customer-facing output predictable.
 */

function inline(text: string, keyPrefix: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).filter(Boolean);
  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("_") && part.endsWith("_")) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }
    return <Fragment key={key}>{part}</Fragment>;
  });
}

export function Rationale({ text, className }: { text: string; className?: string }) {
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];

  const flushBullets = () => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`}>
        {bullets.map((item, index) => (
          <li key={index}>{inline(item, `li-${blocks.length}-${index}`)}</li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("- ")) {
      bullets.push(trimmed.slice(2));
      continue;
    }
    flushBullets();
    if (trimmed) {
      blocks.push(<p key={`p-${blocks.length}`}>{inline(trimmed, `p-${blocks.length}`)}</p>);
    }
  }
  flushBullets();

  return <div className={`prose-quote text-sm ${className ?? ""}`}>{blocks}</div>;
}
