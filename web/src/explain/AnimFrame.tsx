// An animated frame (#283): the toolbar (play, event steps, the clock's reading, a frame's own
// toggles as children), the lane chart, the range, the legend, the readout of every lane's
// state at the marker, and the caption.
import { useMemo } from "react";
import type { ReactNode } from "react";
import Lanes from "./Lanes";
import type { Tick } from "./Lanes";
import { laneEvents, laneState, laneWord } from "./lane";
import type { Lane } from "./lane";
import { useClock } from "./useClock";
import { usePhone } from "./usePhone";

interface Props {
  id: string;
  min: number;
  max: number;
  /** The range's step. */
  step: number;
  /** Axis units a second of play. */
  speed: number;
  lanes: Lane[];
  ticks: (phone: boolean) => Tick[];
  /** The clock's reading at `t`. */
  now: (t: number) => string;
  hint: string;
  rangeLabel: string;
  /** The chart's accessible name. */
  label: string;
  caption: string;
  children?: ReactNode;
}

export default function AnimFrame({ id, min, max, step, speed, lanes, ticks, now, hint, rangeLabel, label, caption, children }: Props) {
  const events = useMemo(() => laneEvents(lanes), [lanes]);
  const clock = useClock({ min, max, speed, events });
  const [ref, phone] = usePhone<HTMLDivElement>();
  return (
    <div className="ex-anim" ref={ref}>
      <div className="ex-ctl">
        <button className={`ex-play${clock.playing ? " on" : ""}`} onClick={clock.toggle} disabled={clock.reduced} aria-pressed={clock.playing}>
          {clock.playing ? "❚❚ pause" : "▶ play"}
        </button>
        <button onClick={clock.prev} title="previous event">
          ⇤ event
        </button>
        <button onClick={clock.next} title="next event">
          event ⇥
        </button>
        <span className="ex-now" aria-live="off">
          {now(clock.t)}
        </span>
        {children}
        <span className="ex-hint">{clock.reduced ? "reduced motion: the final frame is shown; drag the slider, or step from event to event" : hint}</span>
      </div>
      <Lanes id={id} min={min} max={max} ticks={ticks(phone)} lanes={lanes} t={clock.t} phone={phone} label={label} />
      <input type="range" min={min} max={max} step={step} value={clock.t} onChange={(e) => clock.set(Number(e.target.value))} aria-label={rangeLabel} />
      <div className="ex-legend">
        <span>
          <i className="l-open" />
          open: the window or the gate allows it
        </span>
        <span>
          <i className="l-run" />
          running
        </span>
        <span>
          <i className="l-block" />
          blocked, hatched
        </span>
        <span>
          <i className="l-done" />
          done
        </span>
        <span>
          <i className="l-stop" />
          hard stop
        </span>
        <span>
          <i className="l-dim" />
          still to come
        </span>
      </div>
      <ul className="ex-read">
        {lanes.map((ln) => {
          const g = laneState(ln, clock.t);
          return (
            <li key={ln.name}>
              <b className={`ex-k-${g.k}`}>{laneWord(g)}</b>
              <span>
                <span className="ex-who">{ln.name}</span> · {g.l}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="ex-cap">{caption}</p>
    </div>
  );
}
