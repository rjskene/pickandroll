// A card's bullets (#283), shared by the step cards and the popouts: key ideas with their
// sub-ideas, two levels, glossary terms underlined, and a Formula chip where the idea rests on
// one (#282).
import { Fragment } from "react";
import { FORMULAS } from "./formulas";
import { Term } from "./Glossary";
import { useOpenPop } from "./PopContext";
import { pieces } from "./text";
import type { Bullet } from "./types";

export function Inline({ text }: { text: string }) {
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

export function Bullets({ bullets, className = "ex-bullets" }: { bullets: Bullet[]; className?: string }) {
  const openPop = useOpenPop();
  return (
    <ul className={className}>
      {bullets.map((b, i) => (
        <li key={i}>
          <Inline text={b.text} />
          {b.formula && (
            <button className="ex-fx" onClick={() => b.formula && openPop({ kind: "formula", id: b.formula })} title={`The formula: ${FORMULAS[b.formula].name}, every variable, a worked sample`}>
              Formula
            </button>
          )}
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
