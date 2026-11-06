// One step's card (#283): the figure beside the bullets (two levels, terms underlined) and the
// step's sources. The "step n of N" kicker ("overview" on a track's overview) heads the figure panel, the title and the Example
// button (the step's worked example, #282) the text. The arrows that walk the steps sit in the
// screen's control bar. Either panel can show alone (#337), so each carries what the other would
// have given it: the figure a copy of the title and the button, the text a copy of the kicker,
// both hidden by CSS unless their panel is alone.
import { Bullets } from "./Bullets";
import { FIGURES } from "./figures";
import { stepCount } from "./nav";
import { useOpenPop } from "./PopContext";
import type { Step, Track } from "./types";

interface Props {
  track: Track;
  step: Step;
  index: number;
}

export default function StepCard({ track, step, index }: Props) {
  const Figure = FIGURES[step.figure];
  const openPop = useOpenPop();
  const kicker = `${step.intro ? "overview" : `step ${stepCount(track, index)}`} · ${step.kicker}`;
  const head = (
    <>
      <h3>{step.title}</h3>
      {step.example && (
        <button className="ex-xbtn" onClick={() => openPop({ kind: "example", track: track.id, step: step.id })} title="A worked example: fictional players, made-up numbers (e)">
          Example <kbd>e</kbd>
        </button>
      )}
    </>
  );
  return (
    <section className={`ex-step${step.wide ? " wide" : ""}`} id={`ex-${track.id}-${step.id}`} aria-label={step.title}>
      <div className="ex-fig">
        <span className="ex-n">{kicker}</span>
        <div className="ex-fig-head">{head}</div>
        <Figure />
      </div>
      <div className="ex-text">
        <span className="ex-n ex-text-n">{kicker}</span>
        <div className="ex-head">{head}</div>
        <Bullets bullets={step.bullets} />
        <p className="ex-src">from {step.source.join(" · ")}</p>
      </div>
    </section>
  );
}
