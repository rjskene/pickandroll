import { useLayoutEffect, useRef } from "react";
import type { FlagConfig, FlagInputs, PlayerFlag } from "../api";
import { flagBreakdown, flagExplainer } from "../season";
import Info from "./Info";

/** The breakout flag's "i" (#113): what each signal reads and how it scores, the levels and the
 * signals today's inputs leave silent, every number from the API's config. */
export function FlagInfo({ cfg, silent, align = "left" }: { cfg: FlagConfig | undefined; silent?: FlagInputs["silent"]; align?: "left" | "right" }) {
  if (!cfg) return null;
  const x = flagExplainer(cfg, silent);
  return (
    <Info title="the breakout flag" align={align}>
      <span>Signs that an available player may outlast his projection, which lags a role change by days. Four signals:</span>
      {x.signals.map((sg) => (
        <span key={sg.key}>
          <b>{sg.name}</b>: {sg.text}
          {sg.silent && <span className="bad"> Silent today: {sg.silent}.</span>}
        </span>
      ))}
      <span>{x.levels}</span>
      <span className="dim">{x.caveat} Click a flagged player for his breakdown.</span>
    </Info>
  );
}

/** A player's flag under his row: the four signals as 0-to-1 bars with their evidence (a silent
 * one says why), the sum against the levels, and the move. */
export function FlagBreakdown({
  f,
  cfg,
  silent,
  onEvaluate,
}: {
  f: PlayerFlag;
  cfg: FlagConfig | undefined;
  silent?: FlagInputs["silent"];
  onEvaluate: () => void;
}) {
  const b = flagBreakdown(f, cfg, silent);
  const pct = (x: number) => `${Math.round(Math.min(1, Math.max(0, x)) * 100)}%`;
  // Under a wide table that scrolls sideways, it stays in view at the table's visible width.
  const ref = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    const wrap = ref.current?.closest(".table-wrap");
    if (ref.current && wrap) ref.current.style.maxWidth = `${Math.min(760, wrap.clientWidth - 4)}px`;
  }, []);
  return (
    <div className="flag-breakdown" ref={ref}>
      {b.signals.map((x) => (
        <div key={x.key} className={`fb-signal${x.score > 0 ? "" : " quiet"}`}>
          <span className="fb-name">{x.name}</span>
          <span className="fb-bar" role="meter" aria-label={`${x.name}, 0 to 1`} aria-valuemin={0} aria-valuemax={1} aria-valuenow={x.score}>
            <span style={{ width: pct(x.score) }} />
          </span>
          <span className="num">{x.score.toFixed(2)}</span>
          <span className={x.silent ? "bad" : x.score > 0 ? undefined : "dim"}>
            {x.reason ?? (x.silent ? `silent: ${x.silent}` : "nothing today")}
            {!x.counted && <span className="dim"> · not counted: it counts only beside another signal</span>}
          </span>
        </div>
      ))}
      <div className="fb-sum">
        <span className="fb-name">sum</span>
        <span className="fb-bar scale" role="meter" aria-label={`the sum, 0 to ${b.max}`} aria-valuemin={0} aria-valuemax={b.max} aria-valuenow={b.sum}>
          <span style={{ width: pct(b.sum / b.max) }} />
          {b.levels.map((l) => (
            <i key={l.level} className={l.reached ? "on" : undefined} style={{ left: pct(l.floor / b.max) }} title={`${l.level} from ${l.floor}`} />
          ))}
        </span>
        <span className="num">{b.sum.toFixed(2)}</span>
        <span>{b.line}</span>
        <span className="grow" />
        <button
          className="small"
          onClick={(e) => {
            e.stopPropagation();
            onEvaluate();
          }}
          title="Open his move in the Moves card"
        >
          evaluate move
        </button>
      </div>
    </div>
  );
}
