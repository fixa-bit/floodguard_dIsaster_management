import { useEffect, useMemo, useState } from "react";
import "../catchment-briefing.css";

export interface BriefingLine { label: string; text: string }

/** How long the briefing takes to type out, in ms: about as long as the catchment's outline takes to trace. */
const typingMs = 5600;

/**
 * The catchment briefing typed out while the tour draws the catchment's outline: one line at a
 * time, letter by letter, with a blinking cursor, finishing about as the outline closes. `startedAt`
 * (a timestamp) starts it; null clears it, fading out as the camera heads down to the station.
 */
export function CatchmentBriefing({ title, lines, startedAt }: { title: string; lines: BriefingLine[]; startedAt: number | null }) {
  const [shownLines, setShownLines] = useState({ title, lines });
  const [typed, setTyped] = useState(0);
  const total = useMemo(() => shownLines.title.length + shownLines.lines.reduce((sum, line) => sum + line.label.length + line.text.length, 0), [shownLines]);

  // A new catchment takes its own text; the old text stays while it fades out.
  useEffect(() => { if (startedAt !== null) setShownLines({ title, lines }); }, [startedAt, title, lines]);

  useEffect(() => {
    if (startedAt === null) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) { setTyped(Number.MAX_SAFE_INTEGER); return; }
    setTyped(0);
    let frame = 0;
    const step = () => {
      const t = Math.min(1, (Date.now() - startedAt) / typingMs);
      setTyped(Math.floor(t * total));
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [startedAt, total]);

  // Hand out the typed letters: the title first, then each line's label and text in turn.
  let left = typed;
  const take = (text: string) => { const part = text.slice(0, Math.max(0, left)); left -= text.length; return part; };
  const typedTitle = take(shownLines.title);
  const typedLines = shownLines.lines.map((line) => ({ label: take(line.label), text: take(line.text) }));
  const cursorAt = typedLines.findIndex((line, index) => line.label.length + line.text.length < shownLines.lines[index].label.length + shownLines.lines[index].text.length);

  return (
    <section className="catchment-briefing" data-shown={startedAt !== null || undefined} aria-live="polite" aria-label="Catchment briefing">
      <h3>{typedTitle}{typedTitle.length < shownLines.title.length && <i className="catchment-briefing__cursor" />}</h3>
      <dl>
        {typedLines.map((line, index) => (line.label || line.text) && (
          <div key={shownLines.lines[index].label}>
            <dt>{line.label}</dt>
            <dd>{line.text}{index === cursorAt && <i className="catchment-briefing__cursor" />}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
