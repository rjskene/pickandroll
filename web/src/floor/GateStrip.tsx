// The day's gates under the floor (#472): one lane an agent, the Central day from 04:30 to
// midnight, the now line; done steps as bars, a run in flight pulsing, gates still to come hollow,
// missed ones amber, the watchdog a plain tick, the execute times on the Mover's lane. Hover a
// mark for its gate. Drawn from the timeline the face already holds: no fetch of its own.
import { useLayoutEffect, useRef, useState } from "react";
import { AGENTS } from "./model";
import type { Agent } from "./model";
import { LANES, gateTip, tipCenter } from "./gates";
import type { DayGates, Gate } from "./gates";
import { dayLabel } from "./scene";

const HOURS = Array.from({ length: 19 }, (_, k) => 5 + k);

const hhmm = (t: number) =>
  new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(t));

export default function GateStrip({ day, onToday, onTerm }: { day: DayGates; onToday: (() => void) | null; onTerm: () => void }) {
  const [tip, setTip] = useState<{ g: Gate; lane: Agent | null; x: number; y: number; box: number } | null>(null);
  const tipEl = useRef<HTMLDivElement>(null);
  // The tip is centered on its left (translate -50%): place it from its measured width, before paint.
  useLayoutEffect(() => {
    const el = tipEl.current;
    if (el && tip) el.style.left = `${tipCenter(tip.box, el.offsetWidth, tip.x)}px`;
  }, [tip]);
  const span = day.to - day.from;
  const pct = (t: number) => `${(Math.max(0, Math.min(1, (t - day.from) / span)) * 100).toFixed(3)}%`;
  const wpct = (a: number, b: number) => `${(Math.max(0, Math.min(1, (b - day.from) / span) - Math.max(0, Math.min(1, (a - day.from) / span))) * 100).toFixed(3)}%`;
  const hover = (g: Gate, lane: Agent | null) => (e: React.MouseEvent) => {
    const box = (e.currentTarget as HTMLElement).closest(".gates")?.getBoundingClientRect();
    if (box) setTip({ g, lane, x: e.clientX - box.left, y: e.clientY - box.top, box: box.width });
  };
  const leave = () => setTip(null);
  // A hit target wider than the marks: the gate's span on the lane, from its time to its last bar.
  const hit = (g: Gate, a: Agent) => {
    const ends = g.bars.filter((b) => b.agent === a).flatMap((b) => [b.start, b.end]);
    const lo = Math.min(g.at, ...ends);
    const hi = Math.max(g.at, ...ends);
    return { left: pct(lo), width: wpct(lo, hi) };
  };
  const hourAt = (h: number) => day.from + (h * 60 - (4 * 60 + 30)) * 60_000;
  const plain = day.gates.filter((g) => g.state === "plain");
  const when = day.when === "past" ? "done and missed" : day.when === "future" ? "still to come" : "today";
  return (
    <div className="gates" onMouseLeave={leave}>
      <div className="gs-head">
        <button type="button" className="fl-term gs-title" onClick={onTerm} title="The day's gates in Explain's glossary">
          <b>{dayLabel(day.date)}</b>
        </button>
        <span className="muted">{when}</span>
        {onToday && (
          <button type="button" className="small" onClick={onToday}>
            Today
          </button>
        )}
        <span className="grow" />
        <span className="gs-key">
          <i className="k-ok" />
          done
          <i className="k-failed" />
          failed
          <i className="k-idle" />
          nothing to do
          <i className="k-run" />
          running
          <i className="k-todo" />
          still to come
          <i className="k-missed" />
          not run
        </span>
      </div>
      <div className="gs-body">
        <div className="gs-labels">
          {LANES.map((a) => (
            <span key={a} className={`c-${a}`}>
              <i />
              {AGENTS[a].label}
            </span>
          ))}
          <span className="gs-axis-k">CT</span>
        </div>
        <div className="gs-tracks">
          {HOURS.map((h) => (
            <i key={h} className="gs-hour" style={{ left: pct(hourAt(h)) }} />
          ))}
          {plain.map((g) => (
            <span key={g.key} className="gs-plain" style={{ left: pct(g.at) }} onMouseMove={hover(g, null)} aria-label={gateTip(g, null).join(". ")} />
          ))}
          {LANES.map((a) => (
            <div key={a} className={`gs-lane c-${a}`}>
              {day.bands
                .filter((b) => b.lanes.includes(a))
                .map((b) => (
                  <i key={b.key} className="gs-band" style={{ left: pct(b.start), width: wpct(b.start, b.end) }} title={b.label} />
                ))}
              {day.gates.map((g) =>
                !g.lanes.includes(a) ? null : (
                  <span key={g.key} className="gs-gate" onMouseMove={hover(g, a)}>
                    <i className="gs-hit" style={hit(g, a)} />
                    {g.bars
                      .filter((b) => b.agent === a)
                      .map((b, k) => (
                        <i key={k} className={`gs-bar ${b.state}`} style={{ left: pct(b.start), width: wpct(b.start, b.end) }} />
                      ))}
                    {g.kind === "execute" ? (
                      <span className={`gs-exec ${g.state}`} style={{ left: pct(g.at) }} aria-label={gateTip(g, a).join(". ")}>
                        <b>{g.count}</b>
                      </span>
                    ) : (g.state === "todo" || g.state === "missed" || (g.state === "running" && !g.bars.some((b) => b.agent === a))) && (
                      <span className={`gs-mark ${g.state}`} style={{ left: pct(g.at) }} aria-label={gateTip(g, a).join(". ")}>
                        {g.state === "missed" && a === g.lanes[0] && <em>not run</em>}
                      </span>
                    )}
                  </span>
                ),
              )}
            </div>
          ))}
          <div className="gs-axis">
            {HOURS.map((h) => (
              <span key={h} style={{ left: pct(hourAt(h)) }}>
                {String(h).padStart(2, "0")}
              </span>
            ))}
          </div>
          {day.now !== null && (
            <span className="gs-now" style={{ left: pct(day.now) }}>
              <b>{hhmm(day.now)}</b>
            </span>
          )}
        </div>
      </div>
      {tip && (
        <div ref={tipEl} className="gs-tip" style={{ top: tip.y }} role="tooltip">
          {gateTip(tip.g, tip.lane).map((l, k) => (
            <div key={k} className={k === 0 ? "t" : ""}>
              {l}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
