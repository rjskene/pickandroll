// The progress strip (#283): the track's lede and one dot per step, done up to the current one;
// a dot past the written steps is still to come. The per-track drawings (the draft's pipeline
// with its re-solve loop, the daily's hour line) come with their tracks.
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
  return (
    <svg className={phone ? "ex-only-phone" : "ex-only-desk"} viewBox={`0 0 ${W} ${phone ? 64 : 90}`} role="img" aria-label={`${track.title}: step ${step + 1} of ${n}`}>
      {xs.slice(0, -1).map((x, i) => (
        <line key={i} className={`ex-strip-line${i < step ? " done" : ""}`} x1={x} y1={y} x2={xs[i + 1]} y2={y} />
      ))}
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
              <text className={`ex-strip-lbl ${state}`} x={x} y={y + r + 16} textAnchor="middle">
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
