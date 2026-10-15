import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { ScoreEntry } from "../../api";
import { signed } from "../../format";
import type { ScorePoint } from "./scoreTurns";

// Drawn in viewBox units and scaled to the drawer's width.
const W = 380;
const H = 150;
const M = { left: 30, right: 12, top: 12, bottom: 22 };

const MODE_NAME: Record<ScoreEntry["mode"], string> = { horizon: "horizon plan", roster: "roster fallback" };
const MODE_NOTE: Record<ScoreEntry["mode"], string> = {
  horizon: "horizon plan",
  roster: "roster fallback: the horizon plan could not be built",
};

/** Round tick values for the wins axis, about four lines whatever the spread, as labels. */
function ticks(lo: number, hi: number): { t: number; label: string }[] {
  const span = hi - lo;
  const step = span <= 0.6 ? 0.1 : span <= 1.5 ? 0.25 : span <= 3 ? 0.5 : 1;
  const digits = step === 0.25 ? 2 : step < 1 ? 1 : 0;
  const out = [];
  for (let i = Math.ceil(lo / step); i * step <= hi + 1e-9; i++) out.push({ t: i * step, label: (i * step).toFixed(digits) });
  return out;
}

const xLabel = (p: ScorePoint) => (p.kind === "pre" ? "pre" : p.kind === "final" ? "final" : p.kind === "now" ? "now" : `#${p.overall}`);

/** Expected categories won from before my first pick through each of my real turns: the
 * benchmark as a reference line, and the solves the single-roster fallback produced marked
 * hollow on a shaded band (that model's score is not comparable with the horizon plan's). */
export default function ScoreChart({
  points,
  bench,
  named,
  opponents,
}: {
  points: ScorePoint[];
  bench: ScoreEntry | null;
  named: (h: ScoreEntry) => string;
  opponents: number;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [active, setActive] = useState<number | null>(null);
  if (points.length < 2) return null;

  const base = bench?.mode ?? "horizon";
  const values = [...points.map((p) => p.wins), ...(bench ? [bench.wins] : [])];
  const pad = Math.max(0.15, (Math.max(...values) - Math.min(...values)) * 0.12);
  const lo = Math.min(...values) - pad;
  const hi = Math.max(...values) + pad;
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const step = plotW / (points.length - 1);
  const x = (i: number) => M.left + i * step;
  const y = (v: number) => M.top + (1 - (v - lo) / (hi - lo)) * plotH;
  const other = (p: ScorePoint) => p.mode !== null && p.mode !== base;
  const anyOther = points.some(other);
  const every = step >= 26 ? 1 : 2;

  // Solid through the solves the draft has made; dashed into a provisional "now".
  const solid = points.filter((p) => p.kind !== "now");
  const line = solid.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.wins).toFixed(1)}`).join("");
  const last = points.length - 1;
  const provisional = points[last].kind === "now";

  const nearest = (clientX: number) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box || box.width === 0) return null;
    const vx = ((clientX - box.left) / box.width) * W;
    return Math.max(0, Math.min(last, Math.round((vx - M.left) / step)));
  };
  const onMove = (e: PointerEvent<SVGSVGElement>) => setActive(nearest(e.clientX));
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const at = active ?? (e.key === "ArrowLeft" ? last + 1 : -1);
    setActive(Math.max(0, Math.min(last, at + (e.key === "ArrowLeft" ? -1 : 1))));
  };

  const p = active === null ? null : points[active];
  // The readout sits beside its point: left or right of it near the edges, under it when the
  // point is in the top half of the plot, over it otherwise.
  const leftPct = active === null ? 0 : (x(active) / W) * 100;
  const topPct = p ? (y(p.wins) / H) * 100 : 0;
  const tx = leftPct > 60 ? "-100%" : leftPct < 25 ? "0%" : "-50%";
  const ty = topPct > 50 ? "calc(-100% - 10px)" : "10px";
  return (
    <div className="score-chart">
      <svg
        ref={svg}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Expected categories won: ${points.map((q) => `${xLabel(q)} ${q.wins.toFixed(2)}`).join(", ")}`}
        tabIndex={0}
        onPointerMove={onMove}
        onPointerLeave={() => setActive(null)}
        onFocus={() => setActive((a) => a ?? last)}
        onBlur={() => setActive(null)}
        onKeyDown={onKey}
      >
        {points.map((q, i) =>
          other(q) ? (
            <rect key={`band-${q.key}`} className="band" x={Math.max(M.left, x(i) - step / 2)} y={M.top} width={Math.min(x(i) + step / 2, W - M.right) - Math.max(M.left, x(i) - step / 2)} height={plotH} />
          ) : null,
        )}
        {ticks(lo, hi).map(({ t, label }) => (
          <g key={label}>
            <line className="grid" x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} />
            <text className="tick" x={M.left - 5} y={y(t)} dy="0.32em" textAnchor="end">
              {label}
            </text>
          </g>
        ))}
        {bench && (
          <g>
            <line className="ref" x1={M.left} x2={W - M.right} y1={y(bench.wins)} y2={y(bench.wins)} />
            <text className="ref-label" x={W - M.right} y={y(bench.wins) - 4} textAnchor="end">
              before pick 1 · {bench.wins.toFixed(2)}
            </text>
          </g>
        )}
        {active !== null && <line className="crosshair" x1={x(active)} x2={x(active)} y1={M.top} y2={M.top + plotH} />}
        <path className="line" d={line} />
        {provisional && (
          <path className="line provisional" d={`M${x(last - 1).toFixed(1)},${y(points[last - 1].wins).toFixed(1)}L${x(last).toFixed(1)},${y(points[last].wins).toFixed(1)}`} />
        )}
        {points.map((q, i) => (
          <circle
            key={q.key}
            className={`dot ${other(q) ? "hollow" : ""} ${i === active ? "on" : ""}`}
            cx={x(i)}
            cy={y(q.wins)}
            r={q.kind === "final" ? 5 : 4}
          />
        ))}
        <text className="end-label" x={x(last)} y={y(points[last].wins) - 9} textAnchor="end">
          {points[last].wins.toFixed(2)}
        </text>
        {points.map((q, i) =>
          i === 0 || i === last || (i % every === 0 && last - i >= every) ? (
            <text key={`x-${q.key}`} className="tick" x={x(i)} y={H - 6} textAnchor={i === 0 ? "start" : i === last ? "end" : "middle"}>
              {xLabel(q)}
            </text>
          ) : null,
        )}
      </svg>
      {p && (
        <div className="tip" role="status" style={{ left: `${leftPct}%`, top: `${topPct}%`, transform: `translate(${tx}, ${ty})` }}>
          <div className="v">{p.wins.toFixed(2)}</div>
          <div className="muted">
            {p.kind === "pre"
              ? `before pick 1 · ${p.entry?.on_the_clock ? "pick" : "board at"} #${p.overall}`
              : p.kind === "final"
                ? "final roster"
                : p.kind === "now"
                  ? `now · #${p.overall} on the clock`
                  : `pick #${p.overall}`}
          </div>
          {p.entry && named(p.entry) && <div>{p.kind === "turn" || (p.kind === "pre" && p.entry.on_the_clock) ? named(p.entry) : `top: ${named(p.entry)}`}</div>}
          {bench && p.kind !== "pre" && (
            <div className={p.wins - bench.wins < -0.005 ? "bad" : "good"}>{signed(p.wins - bench.wins)} vs before pick 1</div>
          )}
          <div className="dim">
            {p.value.toFixed(1)} z · {p.matchups} of {opponents} matchups
          </div>
          <div className="dim">{p.mode ? MODE_NOTE[p.mode] : "the drafted roster's own odds"}</div>
        </div>
      )}
      {anyOther && (
        <div className="key dim">
          <span>
            <i className="dot-key" /> {MODE_NAME[base]}
          </span>
          <span>
            <i className="dot-key hollow" />
            <i className="band-key" /> {MODE_NAME[base === "horizon" ? "roster" : "horizon"]}, not comparable with it
          </span>
        </div>
      )}
    </div>
  );
}
