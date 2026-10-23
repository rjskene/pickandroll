import { useCallback, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { axisRange, axisTicks } from "../season";

/** A line by its job: the actual (solid, the accent), the expected (dashed, muted), or the
 * other half of a comparison (solid, muted). */
export interface Series {
  key: string;
  label: string;
  tone: "actual" | "expected" | "other";
  values: (number | null)[];
}

/** A knob change on the time axis; its label opens its sheet when it has one. */
export interface Marker {
  week: number;
  id: string;
  title: string;
  onOpen?: () => void;
}

/** One y value per week over a run of weeks, hand-drawn as the Strategy card's frontier: the
 * series sharing one axis (never a second), the knob changes as marks on the time axis, a
 * reference line, a crosshair and a tip by week, and a legend once two series share it. Drawn
 * at the width of its box, so its text keeps its size from a phone to a wide window. */
export default function ProgressChart({
  weeks,
  series,
  markers = [],
  reference,
  invert = false,
  integer = false,
  fmt,
  tickFmt = fmt,
  tip,
  label,
  markerKey,
  width = 640,
  height = 210,
}: {
  weeks: number[];
  series: Series[];
  markers?: Marker[];
  /** A dashed line across the plot, with its label at the right. */
  reference?: { value: number; label: string };
  /** Lower is better (a place): the axis runs down from the top. */
  invert?: boolean;
  /** Whole ticks only. */
  integer?: boolean;
  fmt: (v: number) => string;
  /** The axis's ticks, when they read otherwise than the values. */
  tickFmt?: (v: number) => string;
  tip: (i: number) => ReactNode;
  label: string;
  /** What the legend calls the knob marks; none without marks. */
  markerKey?: string;
  width?: number;
  height?: number;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [active, setActive] = useState<number | null>(null);
  const [fit, setFit] = useState<number | null>(null);
  const watcher = useRef<ResizeObserver | null>(null);
  const box = useCallback((el: HTMLDivElement | null) => {
    watcher.current?.disconnect();
    watcher.current = null;
    if (!el || typeof ResizeObserver === "undefined") return;
    watcher.current = new ResizeObserver(([e]) => setFit(Math.max(300, Math.round(e.contentRect.width))));
    watcher.current.observe(el);
  }, []);
  const W = fit ?? width;
  const H = height;
  const M = { left: 38, right: 44, top: 14, bottom: markers.length ? 40 : 24 };
  const values = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  if (!weeks.length || !values.length) return null;

  const all = reference ? [...values, reference.value] : values;
  let [lo, hi] = invert || integer ? [Math.min(...all) - 0.5, Math.max(...all) + 0.5] : axisRange(all);
  if (hi - lo < 1e-9) [lo, hi] = [lo - 1, hi + 1];
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const last = weeks.length - 1;
  const step = last ? plotW / last : 0;
  const x = (i: number) => (last ? M.left + i * step : M.left + plotW / 2);
  const y = (v: number) => M.top + (invert ? (v - lo) / (hi - lo) : 1 - (v - lo) / (hi - lo)) * plotH;
  const ticks = axisTicks(lo, hi).filter((t) => !integer || Number.isInteger(t));
  const every = step >= 34 || !last ? 1 : Math.ceil(34 / step);

  const path = (vs: (number | null)[]) => {
    let d = "";
    let pen = false;
    vs.forEach((v, i) => {
      if (v == null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };

  const nearest = (clientX: number) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box || box.width === 0) return null;
    if (!last) return 0;
    const vx = ((clientX - box.left) / box.width) * W;
    return Math.max(0, Math.min(last, Math.round((vx - M.left) / step)));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    e.stopPropagation();
    const at = active ?? (e.key === "ArrowLeft" ? last + 1 : -1);
    setActive(Math.max(0, Math.min(last, at + (e.key === "ArrowLeft" ? -1 : 1))));
  };

  // The readout sits beside its week: left or right of it near the edges, else centred.
  const leftPct = active === null ? 0 : (x(active) / W) * 100;
  const tx = leftPct > 60 ? "calc(-100% - 12px)" : leftPct < 25 ? "12px" : "-50%";
  const ends = series
    .map((s) => ({ s, v: [...s.values].reverse().find((v) => v != null) ?? null, i: last - [...s.values].reverse().findIndex((v) => v != null) }))
    .filter((e): e is { s: Series; v: number; i: number } => e.v != null);
  // Two end labels too close to read apart: the lower one goes under its line.
  const below = ends.length === 2 && Math.abs(y(ends[0].v) - y(ends[1].v)) < 12 ? (y(ends[0].v) > y(ends[1].v) ? 0 : 1) : -1;
  const at = (week: number) => weeks.indexOf(week);
  return (
    <div className="score-chart progress-chart" ref={box}>
      <svg
        ref={svg}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`${label}: ${weeks.map((w, i) => `week ${w} ${series.map((s) => `${s.label} ${s.values[i] == null ? "none" : fmt(s.values[i]!)}`).join(", ")}`).join("; ")}`}
        tabIndex={0}
        onPointerMove={(e: PointerEvent<SVGSVGElement>) => setActive(nearest(e.clientX))}
        onPointerLeave={() => setActive(null)}
        onFocus={() => setActive((a) => a ?? last)}
        onBlur={() => setActive(null)}
        onKeyDown={onKey}
      >
        {ticks.map((t) => (
          <g key={`y${t}`}>
            <line className="grid" x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} />
            <text className="tick" x={M.left - 6} y={y(t)} dy="0.32em" textAnchor="end">
              {tickFmt(t)}
            </text>
          </g>
        ))}
        {reference && (
          <g>
            <line className="ref" x1={M.left} x2={W - M.right} y1={y(reference.value)} y2={y(reference.value)} />
            <text className="ref-label" x={M.left + 4} y={y(reference.value) - 4}>
              {reference.label}
            </text>
          </g>
        )}
        {markers
          .filter((m) => at(m.week) >= 0)
          .map((m) => (
            <g
              key={m.id}
              className={m.onOpen ? "knob-mark open" : "knob-mark"}
              role={m.onOpen ? "button" : undefined}
              tabIndex={m.onOpen ? 0 : undefined}
              aria-label={m.onOpen ? `${m.title}: open its sheet` : m.title}
              onClick={m.onOpen}
              onKeyDown={(e) => {
                if (m.onOpen && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  m.onOpen();
                }
              }}
            >
              <title>{m.onOpen ? `${m.title} · click for its sheet` : m.title}</title>
              <line x1={x(at(m.week))} x2={x(at(m.week))} y1={M.top} y2={M.top + plotH} />
              <rect className="hit" x={x(at(m.week)) - 24} y={H - 22} width={48} height={20} />
              <text x={x(at(m.week))} y={H - 8} textAnchor="middle">
                {m.id}
              </text>
            </g>
          ))}
        {active !== null && <line className="crosshair" x1={x(active)} x2={x(active)} y1={M.top} y2={M.top + plotH} />}
        {series.map((s) => (
          <path key={s.key} className={`line ${s.tone}`} d={path(s.values)} />
        ))}
        {series.map((s) =>
          s.values.map((v, i) =>
            v == null || (i !== active && (s.tone !== "actual" || (last > 12 && i !== last))) ? null : (
              <circle key={`${s.key}-${i}`} className={`dot ${s.tone} ${i === active ? "on" : ""}`} cx={x(i)} cy={y(v)} r={4} />
            ),
          ),
        )}
        {ends.map((e, k) => (
          <text key={`end-${e.s.key}`} className={`end-label ${e.s.tone}`} x={x(e.i) + 7} y={y(e.v)} dy={k === below ? "1em" : "0.32em"}>
            {fmt(e.v)}
          </text>
        ))}
        {weeks.map((w, i) =>
          i === 0 || i === last || (i % every === 0 && last - i >= every) ? (
            <text key={`x${w}`} className="tick" x={x(i)} y={M.top + plotH + 14} textAnchor={!last ? "middle" : i === 0 ? "start" : i === last ? "end" : "middle"}>
              wk {w}
            </text>
          ) : null,
        )}
      </svg>
      {active !== null && (
        <div className="tip" role="status" style={{ left: `${leftPct}%`, top: "8px", transform: `translateX(${tx})` }}>
          {tip(active)}
        </div>
      )}
      {(series.length > 1 || (markers.length > 0 && markerKey)) && (
        <div className="key dim">
          {series.length > 1 &&
            series.map((s) => (
              <span key={s.key}>
                <i className={`line-key ${s.tone}`} /> {s.label}
              </span>
            ))}
          {markers.length > 0 && markerKey && (
            <span>
              <i className="mark-key" /> {markerKey}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
