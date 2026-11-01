// The progress strip (#283): the track's lede and one dot per step, done up to the current one;
// a dot past the written steps is still to come. A track may draw a loop under its dots (#284:
// the draft's pipeline is re-solved after every pick), or sit its dots on an hour line (#286:
// the day, each routine at its hour, the current one lit).
import { hourAnchor, hourTicks, hourXs, labelRows } from "./hours";
import { Arrow } from "./svg";
import type { Track } from "./types";

interface Props {
  track: Track;
  step: number;
  onGo: (i: number) => void;
}

function Dots({ track, step, onGo, phone }: Props & { phone: boolean }) {
  const W = phone ? 360 : 960;
  const n = track.labels.length;
  const written = track.steps.length;
  const left = 30;
  const right = W - 30;
  const y = phone ? 22 : 30;
  const r = phone ? 11 : 13;
  const hours = track.hours && track.hours.length === n ? track.hours : undefined;
  const xs = hours ? hourXs(hours, left, right, 2 * r + 10) : track.labels.map((_, i) => left + (i * (right - left)) / Math.max(1, n - 1));
  const loop = !hours && track.loop && track.loop.from < n && track.loop.to < n ? track.loop : undefined;
  const anchors = xs.map((x) => (hours ? hourAnchor(x, left, right) : "middle"));
  const rows = hours && !phone ? labelRows(xs, track.labels, anchors, 6, 6) : xs.map(() => 0);
  const H = phone ? 64 : hours ? 104 : 90;
  const yy = y + (phone ? 30 : 36);
  const ah = `ex-strip-ah-${phone ? "p" : "d"}`;
  const xMon = left + (6 / 24) * (right - left);
  return (
    <svg className={phone ? "ex-only-phone" : "ex-only-desk"} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${track.title}: step ${step + 1} of ${n}`}>
      {hours ? (
        <>
          <line className="ex-strip-line" x1={left} y1={y} x2={right} y2={y} />
          <line className="ex-strip-line done" x1={left} y1={y} x2={xs[step]} y2={y} />
          {hourTicks(left, right).map((k) => (
            <g key={k.h}>
              <line className="ex-strip-tick" x1={k.x} y1={y - 5} x2={k.x} y2={y + 5} />
              {!phone && (
                <text className="ex-strip-hour" x={k.x} y={y + 62} textAnchor="middle">
                  {String(k.h).padStart(2, "0")}
                </text>
              )}
            </g>
          ))}
          <line className="ex-strip-tick mon" x1={xMon} y1={y - 12} x2={xMon} y2={y + 12} />
          {!phone && (
            <text className="ex-strip-hour" x={xMon} y={y - 16} textAnchor="middle">
              Mon 06:00 recorder
            </text>
          )}
        </>
      ) : (
        xs.slice(0, -1).map((x, i) => <line key={i} className={`ex-strip-line${i < step ? " done" : ""}`} x1={x} y1={y} x2={xs[i + 1]} y2={y} />)
      )}
      {loop && (
        <>
          <Arrow id={ah} accent />
          <path className="ex-strip-loop" d={`M${xs[loop.from]} ${y + r - 1}V${yy}H${xs[loop.to]}V${y + r - 1}`} markerEnd={`url(#${ah})`}>
            <title>{loop.label}</title>
          </path>
          {!phone && (
            <text className="ex-strip-loop-lbl" x={(xs[loop.from] + xs[loop.to]) / 2} y={yy + 13} textAnchor="middle">
              {loop.label}
            </text>
          )}
        </>
      )}
      {xs.map((x, i) => {
        const state = i === step ? "cur" : i < step ? "done" : i >= written ? "soon" : "";
        const can = i < written;
        return (
          <g key={i} className={`ex-strip-node${can ? " can" : ""}`} onClick={can ? () => onGo(i) : undefined}>
            <title>{can ? `${track.labels[i]}: step ${i + 1}` : `${track.labels[i]}: step ${i + 1}, still to come`}</title>
            <circle className={`ex-strip-dot ${state}`} cx={x} cy={y} r={r} />
            <text className={`ex-strip-num ${state}`} x={x} y={y + 4} textAnchor="middle">
              {i + 1}
            </text>
            {(!phone || i === step) && (
              <text
                className={`ex-strip-lbl ${state}${loop ? " knock" : ""}${hours ? " hour" : ""}`}
                x={x}
                y={y + r + 16 + rows[i] * 12}
                textAnchor={anchors[i]}
              >
                {track.labels[i]}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

export default function Strip(props: Props) {
  const { track } = props;
  return (
    <div className="ex-strip">
      <p className="ex-lede">
        <b>{track.title}</b>: {track.lede}
      </p>
      <Dots {...props} phone={false} />
      <Dots {...props} phone />
    </div>
  );
}
