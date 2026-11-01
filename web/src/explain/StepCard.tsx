// One step's card (#283): the figure beside the bullets (two levels, terms underlined) and the
// step's sources. The arrows that walk the steps sit in the screen's control bar; the Example
// button opens the step's worked example (#282).
import { Bullets } from "./Bullets";
import { FIGURES } from "./figures";
import { useOpenPop } from "./PopContext";
import type { Step, Track } from "./types";

interface Props {
  track: Track;
  step: Step;
  index: number;
}

export default function StepCard({ track, step, index }: Props) {
  const Figure = FIGURES[step.figure];
  const planned = track.labels.length;
  const openPop = useOpenPop();
  return (
    <section className={`ex-step${step.wide ? " wide" : ""}`} id={`ex-${track.id}-${step.id}`} aria-label={step.title}>
      <div className="ex-fig">
        <Figure />
      </div>
      <div className="ex-text">
        <div className="ex-head">
          <span className="ex-n">
            step {index + 1} of {planned} · {step.kicker}
          </span>
          {step.example && (
            <button className="ex-xbtn" onClick={() => openPop({ kind: "example", track: track.id, step: step.id })} title="A worked example: fictional players, made-up numbers (e)">
              Example <kbd>e</kbd>
            </button>
          )}
        </div>
        <h3>{step.title}</h3>
        <Bullets bullets={step.bullets} />
        <p className="ex-src">from {step.source.join(" · ")}</p>
      </div>
    </section>
  );
}
