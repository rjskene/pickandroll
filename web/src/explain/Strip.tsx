// The progress strip (#283): the track's lede and one dot per step, done up to the current one;
// a dot past the written steps is still to come. A track may draw a loop under its dots (#284:
// the draft's pipeline is re-solved after every pick); the daily's hour line comes with #286.
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
  const xs = track.labels.map((_, i) => left + (i * (right - left)) / Math.max(1, n - 1));
  const loop = track.loop && track.loop.from < n && track.loop.to < n ? track.loop : undefined;
  const yy = y + (phone ? 30 : 36);
  const ah = `ex-strip-ah-${phone ? "p" : "d"}`;
  return (
    <svg className={phone ? "ex-only-phone" : "ex-only-desk"} viewBox={`0 0 ${W} ${phone ? 64 : 90}`} role="img" aria-label={`${track.title}: step ${step + 1} of ${n}`}>
      {xs.slice(0, -1).map((x, i) => (
        <line key={i} className={`ex-strip-line${i < step ? " done" : ""}`} x1={x} y1={y} x2={xs[i + 1]} y2={y} />
      ))}
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
              <text className={`ex-strip-lbl ${state}${loop ? " knock" : ""}`} x={x} y={y + r + 16} textAnchor="middle">
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
