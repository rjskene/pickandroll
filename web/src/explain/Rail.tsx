// The step rail (#282, the side-rail header the user picked): the track's lede, then one row per
// step down the left of the card, a number dot and a label, the current row lit, the past ones
// filled, a row still to come dimmed; a click opens the step. The daily rows carry their time of
// day; the draft's loop is a dashed bracket from the room back to survival. The chevron at the top
// (or `[`) folds it to a column of the dots, a row's label and time showing on hover or focus, and
// the card takes the room. On a phone the rail is one row of chips under the app bar, scrolling
// sideways inside itself, and the fold does not apply.
import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import { Chevron } from "../components/icons";
import { railItems, railLoop, railTimed } from "./railModel";
import type { Track } from "./types";

interface Props {
  track: Track;
  step: number;
  /** Open with its labels, or folded to the dots. */
  open: boolean;
  onGo: (i: number) => void;
  onToggle: () => void;
}

export default function Rail({ track, step, open, onGo, onToggle }: Props) {
  const items = railItems(track, step);
  const loop = railLoop(track);
  const timed = railTimed(track);
  const list = useRef<HTMLOListElement>(null);

  // A row of chips wider than the phone keeps the current chip in view.
  useEffect(() => {
    const el = list.current;
    if (!el || el.scrollWidth <= el.clientWidth + 1) return;
    const cur = el.querySelector<HTMLElement>(".ex-rail-item.cur");
    if (cur) el.scrollTo({ left: Math.max(0, cur.offsetLeft - (el.clientWidth - cur.offsetWidth) / 2) });
  }, [step, track.id]);

  const span = loop ? ({ "--from": loop.from, "--to": loop.to } as CSSProperties) : undefined;
  return (
    <nav className={`ex-rail${timed ? " timed" : ""}${loop ? " looped" : ""}${open ? "" : " folded"}`} aria-label={`${track.title}: the steps`}>
      <div className="ex-rail-top">
        <p className="ex-rail-lede">{track.lede}</p>
        <button
          className="icon ex-rail-fold"
          onClick={onToggle}
          aria-expanded={open}
          aria-label={open ? "Fold the step rail to its numbers" : "Open the step rail"}
          title={open ? "Fold the rail to its numbers ([)" : "Open the rail ([)"}
        >
          <Chevron dir={open ? "left" : "right"} />
        </button>
      </div>
      <ol ref={list} className="ex-rail-list" style={span}>
        {items.map((it) => (
          <li key={it.i} className={`ex-rail-item ${it.state}`}>
            <button
              onClick={it.can ? () => onGo(it.i) : undefined}
              disabled={!it.can}
              aria-current={it.state === "cur" ? "step" : undefined}
              title={open ? (it.can ? `${it.label}: step ${it.i + 1}` : `${it.label}: step ${it.i + 1}, still to come`) : undefined}
            >
              <span className="ex-rail-dot">{it.i + 1}</span>
              <span className="ex-rail-txt">
                {timed && <span className="ex-rail-time">{it.time ?? ""}</span>}
                <span className="ex-rail-lbl">{it.label}</span>
              </span>
            </button>
          </li>
        ))}
        {loop && <li className="ex-rail-loop" aria-hidden title={loop.label} />}
      </ol>
      {loop && <p className="ex-rail-loop-lbl">↺ {loop.label}</p>}
    </nav>
  );
}
