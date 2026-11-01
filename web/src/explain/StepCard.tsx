// One step's card (#283): the figure beside the bullets (two levels, terms underlined), the
// step's sources, and the pager.
import { Fragment } from "react";
import { FIGURES } from "./figures";
import { Term } from "./Glossary";
import { pieces } from "./text";
import type { Bullet, Step, Track } from "./types";

function Inline({ text }: { text: string }) {
  return (
    <>
      {pieces(text).map((p, i) =>
        p.kind === "term" ? (
          <Term key={i} id={p.id}>
            {p.text}
          </Term>
        ) : (
          <Fragment key={i}>{p.text}</Fragment>
        ),
      )}
    </>
  );
}

export function Bullets({ bullets }: { bullets: Bullet[] }) {
  return (
    <ul className="ex-bullets">
      {bullets.map((b, i) => (
        <li key={i}>
          <Inline text={b.text} />
          {b.sub && b.sub.length > 0 && (
            <ul>
              {b.sub.map((s, j) => (
                <li key={j}>
                  <Inline text={s} />
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ul>
  );
}

interface Props {
  track: Track;
  step: Step;
  index: number;
  /** Read-it-all: no pager. */
  all: boolean;
  onPrev: () => void;
  onNext: () => void;
  nextLabel: string;
  first: boolean;
}

export default function StepCard({ track, step, index, all, onPrev, onNext, nextLabel, first }: Props) {
  const Figure = FIGURES[step.figure];
  const planned = track.labels.length;
  const written = track.steps.length;
  return (
    <section className={`ex-step${step.wide ? " wide" : ""}`} id={`ex-${track.id}-${step.id}`} aria-label={step.title}>
      <div className="ex-fig">
        <Figure />
      </div>
      <div className="ex-text">
        <span className="ex-n">
          step {index + 1} of {planned} · {step.kicker}
        </span>
        <h3>{step.title}</h3>
        <Bullets bullets={step.bullets} />
        <p className="ex-src">from {step.source.join(" · ")}</p>
        {!all && (
          <div className="ex-pager">
            <button onClick={onPrev} disabled={first}>
              ← Prev
            </button>
            <button className="primary" onClick={onNext}>
              {nextLabel}
            </button>
            <span className="ex-count">
              {index + 1} of {planned}
              {written < planned ? ` · ${planned - written} to come` : ""}
            </span>
          </div>
        )}
      </div>
    </section>
  );
}
