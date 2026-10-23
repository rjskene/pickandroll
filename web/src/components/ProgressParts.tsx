import type { ReactNode } from "react";
import type { ProgressPayload, ProgressSentence } from "../api";
import { changeWhat, KNOB_TITLE, POOLED, recordedRange, shownRange, stepRange } from "../progress";
import { gainLabel } from "../season";
import type { Marker } from "./ProgressChart";

// The pieces the Progress screen's views share (#129): the scope and week range at the head of
// each view, the headline tiles, the sentences and the knob changes as marks on a chart.

export const signed1 = (x: number) => gainLabel(x, 1);

export function weekDates(w: { start: string; end: string }): string {
  const d = (s: string) => new Date(`${s}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" }).toLowerCase();
  return `${d(w.start)} – ${d(w.end)}`;
}

/** The knob changes that started in the weeks shown, each a mark that opens its sheet. */
export function knobMarkers(p: ProgressPayload, from: number, to: number, onChange: (id: string) => void): Marker[] {
  return p.knobs.changes
    .filter((c) => c.week != null && c.week >= from && c.week <= to)
    .map((c) => ({ week: c.week!, id: c.id, title: `${c.id} · ${changeWhat(c, KNOB_TITLE)}`, onOpen: () => onChange(c.id) }));
}

/** The weeks a view shows for a scope, and how its steppers move them. */
export function viewRange(p: ProgressPayload, scope: string, range: [number, number] | null, setRange: (r: [number, number] | null) => void) {
  const bounds = recordedRange(p, scope);
  const [from, to] = shownRange(bounds, range);
  const step = (end: 0 | 1, delta: number) => {
    if (bounds) setRange(stepRange([from, to], bounds, end, delta));
  };
  return { bounds, from, to, step };
}

/** A view's head: its title, the scope (the public leagues pooled, or a league, the private one
 * among them), the view's own controls, and the week range stepped with ‹ ›. */
export function ScopeHead({
  p,
  title,
  scope,
  onScope,
  bounds,
  from,
  to,
  setRange,
  onStep,
  children,
}: {
  p: ProgressPayload;
  title: string;
  scope: string;
  onScope: (scope: string) => void;
  bounds: [number, number] | null;
  from: number;
  to: number;
  setRange: (r: [number, number] | null) => void;
  onStep: (end: 0 | 1, delta: number) => void;
  children?: ReactNode;
}) {
  const recorded = p.leagues.filter((l) => l.weeks.length > 0);
  return (
    <div className="sv-head">
      <span className="k">{title}</span>
      <span className="seg small" role="group" aria-label="Scope">
        <button className={scope === POOLED ? "on" : undefined} aria-pressed={scope === POOLED} onClick={() => onScope(POOLED)} title="the public leagues pooled; the private league stays apart">
          All public · pooled
        </button>
        {recorded.map((l) => (
          <button key={l.league} className={scope === l.league ? "on" : undefined} aria-pressed={scope === l.league} onClick={() => onScope(l.league)}>
            {l.league}
            {l.public ? "" : " · private"}
          </button>
        ))}
      </span>
      {children}
      {bounds && (
        <span className="pg-range" aria-label="Weeks shown">
          <span className="dim">weeks</span>
          <button className="small" disabled={from <= bounds[0]} onClick={() => onStep(0, -1)} aria-label="Start a week earlier">
            ‹
          </button>
          <b>{from}</b>
          <button className="small" disabled={from >= to} onClick={() => onStep(0, 1)} aria-label="Start a week later">
            ›
          </button>
          <span className="dim">to</span>
          <button className="small" disabled={to <= from} onClick={() => onStep(1, -1)} aria-label="End a week earlier">
            ‹
          </button>
          <b>{to}</b>
          <button className="small" disabled={to >= bounds[1]} onClick={() => onStep(1, 1)} aria-label="End a week later">
            ›
          </button>
          {(from !== bounds[0] || to !== bounds[1]) && (
            <button className="link" onClick={() => setRange(null)}>
              all
            </button>
          )}
        </span>
      )}
    </div>
  );
}

/** Nothing scored for the scope yet. */
export function NothingScored({ scope }: { scope: string }) {
  return (
    <p className="muted pg-empty">
      {scope === POOLED ? "No public league" : `League ${scope}`} has a scored week yet. The Monday recorder scores each week once it ends, against the odds the decision log held for it;
      the weeks show here from the first one scored.
    </p>
  );
}

export function Tile({ k, v, title, children }: { k: string; v: string; title: string; children: ReactNode }) {
  return (
    <div className="pg-tile" title={title}>
      <span className="k">{k}</span>
      <span className="v">{v}</span>
      <span className="muted">{children}</span>
    </div>
  );
}

const TONE_MARK: Record<ProgressSentence["tone"], string> = { good: "▲", bad: "▼", neutral: "·" };

export function Sentences({ say }: { say: ProgressSentence[] }) {
  return (
    <ul className="pg-say" aria-label="What the numbers say">
      {say.map((s, i) => (
        <li key={i}>
          <span className={`mark ${s.tone}`} aria-label={s.tone === "neutral" ? undefined : s.tone === "good" ? "better" : "worse"}>
            {TONE_MARK[s.tone]}
          </span>
          {s.text}
        </li>
      ))}
    </ul>
  );
}
