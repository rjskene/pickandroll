// The step rail (#282, the side-rail header the user picked): the track's lede, then one row per
// step down the left of the card, a number dot and a label, the current row lit, the past ones
// filled, a row still to come dimmed; a click opens the step. The daily rows carry their time of
// day; the draft's loop is a dashed bracket from the room back to survival. On a phone the rail
// is one row of chips under the app bar, scrolling sideways inside itself.
import { useEffect, useRef } from "react";
import type { CSSProperties } from "react";
import { railItems, railLoop, railTimed } from "./railModel";
import type { Track } from "./types";

interface Props {
  track: Track;
  step: number;
  onGo: (i: number) => void;
}

export default function Rail({ track, step, onGo }: Props) {
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
    <nav className={`ex-rail${timed ? " timed" : ""}${loop ? " looped" : ""}`} aria-label={`${track.title}: the steps`}>
      <p className="ex-rail-lede">{track.lede}</p>
      <ol ref={list} className="ex-rail-list" style={span}>
        {items.map((it) => (
          <li key={it.i} className={`ex-rail-item ${it.state}`}>
            <button
              onClick={it.can ? () => onGo(it.i) : undefined}
              disabled={!it.can}
              aria-current={it.state === "cur" ? "step" : undefined}
              title={it.can ? `${it.label}: step ${it.i + 1}` : `${it.label}: step ${it.i + 1}, still to come`}
            >
              <span className="ex-rail-dot">{it.i + 1}</span>
              {timed && <span className="ex-rail-time">{it.time ?? ""}</span>}
              <span className="ex-rail-lbl">{it.label}</span>
            </button>
          </li>
        ))}
        {loop && <li className="ex-rail-loop" aria-hidden title={loop.label} />}
      </ol>
      {loop && <p className="ex-rail-loop-lbl">↺ {loop.label}</p>}
    </nav>
  );
}
