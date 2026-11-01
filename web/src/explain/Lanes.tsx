// The lane chart (#283): one row per lane, its segments as bars (hatched = blocked, green =
// open or running, amber = done), its marks, the marker at `t` with everything past it dimmed.
// On a phone the names sit over the bars and are drawn last, so the marker never crosses them.
import type { Lane } from "./lane";
import { laneState, laneWord } from "./lane";

export interface Tick {
  v: number;
  l: string;
}

interface Props {
  /** Unique on the page: the hatch pattern's id. */
  id: string;
  min: number;
  max: number;
  ticks: Tick[];
  lanes: Lane[];
  t: number;
  phone: boolean;
  label: string;
}

export default function Lanes({ id, min, max, ticks, lanes, t, phone, label }: Props) {
  const W = phone ? 360 : 960;
  const L = phone ? 0 : 236;
  const x0 = phone ? 8 : L + 4;
  const x1 = phone ? 352 : W - 84;
  const rowH = phone ? 34 : 30;
  const top = 44;
  const ya = 30;
  const H = top + lanes.length * rowH + 8;
  const x = (v: number) => x0 + ((v - min) * (x1 - x0)) / (max - min);
  const xm = x(t);
  const hatch = `${id}-hatch`;
  const hb = phone ? 12 : 14;
  return (
    <svg className="ex-lanes" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
      <defs>
        <pattern id={hatch} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" className="ex-hatch" />
        </pattern>
      </defs>
      <line x1={x0} y1={ya} x2={x1} y2={ya} className="ex-axis" />
      {ticks.map((k) => (
        <g key={k.v}>
          <line x1={x(k.v)} y1={ya - 5} x2={x(k.v)} y2={H - 6} className="ex-grid" />
          <text x={x(k.v)} y={ya - 10} textAnchor="middle" className="ex-tick">
            {k.l}
          </text>
        </g>
      ))}
      {lanes.map((ln, i) => {
        const y = top + i * rowH;
        const yb = phone ? y + 16 : y + 8;
        const ym = yb + hb / 2;
        const g = laneState(ln, t);
        return (
          <g key={ln.name}>
            <line x1={x0} y1={ym} x2={x1} y2={ym} className="ex-row" />
            {ln.segs.map((s, j) => {
              if (s.k === "idle" || s.k === "after") return null;
              const xa = x(s.a);
              const r = { x: xa, y: yb, width: Math.max(2, x(s.b) - xa), height: hb, rx: 2 };
              if (s.k === "block")
                return (
                  <g key={j}>
                    <rect {...r} className="ex-seg-block-bg" />
                    <rect {...r} fill={`url(#${hatch})`} className="ex-seg-block" />
                  </g>
                );
              return <rect key={j} {...r} className={`ex-seg-${s.k}`} />;
            })}
            {(ln.marks ?? []).map((m, j) => {
              const xx = x(m.at);
              const h2 = hb / 2 + 1;
              return m.k === "stop" ? (
                <line key={j} x1={xx} y1={yb - 3} x2={xx} y2={yb + hb + 3} className="ex-stop" />
              ) : (
                <path key={j} d={`M${xx} ${yb - 1}l5 ${h2}l-5 ${h2}l-5 -${h2}z`} className="ex-mark" />
              );
            })}
            {!phone && (
              <>
                <text x={L - 8} y={y + 13} textAnchor="end" className="ex-name">
                  {ln.name}
                </text>
                <text x={L - 8} y={y + 25} textAnchor="end" className="ex-sub">
                  {ln.sub ?? ""}
                </text>
                <text x={x1 + 8} y={yb + hb - 3} className={`ex-badge ex-k-${g.k}`}>
                  {laneWord(g)}
                </text>
              </>
            )}
          </g>
        );
      })}
      <rect x={xm} y={top - 2} width={Math.max(0, x1 - xm)} height={H - top} className="ex-dim" />
      <line x1={xm} y1={ya - 2} x2={xm} y2={H - 4} className="ex-marker" />
      <path d={`M${xm - 5} ${ya - 10}h10l-5 7z`} className="ex-marker-head" />
      {phone &&
        lanes.map((ln, i) => {
          const y = top + i * rowH;
          const g = laneState(ln, t);
          return (
            <g key={ln.name}>
              <text x={x0} y={y + 11} className="ex-name">
                {ln.name}
              </text>
              <text x={x1} y={y + 11} textAnchor="end" className={`ex-badge ex-k-${g.k}`}>
                {laneWord(g)}
              </text>
            </g>
          );
        })}
    </svg>
  );
}
