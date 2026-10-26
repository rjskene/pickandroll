import { useLayoutEffect, useRef } from "react";
import type { FlagConfig, FlagInputs, FlagLevel, PlayerFlag } from "../api";
import { FLAG_SHORT, FLAG_TONE, flagBreakdown, flagLegend, flagMeter, flagScore, flagTag, flagTitle } from "../season";
import Info from "./Info";

const pct = (x: number) => `${Math.round(Math.min(1, Math.max(0, x)) * 1000) / 10}%`;

/** A level as the table draws it: its name in its tone. */
export function LevelTag({ level, title }: { level: FlagLevel; title?: string }) {
  return (
    <span className={`tag ${FLAG_TONE[level]}`} title={title}>
      {FLAG_SHORT[level]}
    </span>
  );
}

/** The score against the level floors (#186): a thin bar filling the score's share of the most
 * the signals add up to, ticked at each floor, a reached tick brighter and thicker. */
export function FlagMeter({ score, cfg, tone }: { score: number; cfg: FlagConfig | undefined; tone: string }) {
  const m = flagMeter(score, cfg);
  return (
    <span className={`flag-meter ${tone}`} role="meter" aria-label={`the flag's score, 0 to ${m.max}`} aria-valuemin={0} aria-valuemax={m.max} aria-valuenow={score}>
      <span style={{ width: pct(m.fill) }} />
      {m.ticks.map((t) => (
        <i key={t.level} className={t.reached ? "on" : undefined} style={{ left: pct(t.at) }} />
      ))}
    </span>
  );
}

/** A breakout flag's tag (#186): its level and score, "ADD 1.7", in the level's tone with the
 * score in the text colour, over its meter; the evidence on hover. A player under watch shows a
 * dimmed "UNDER 0.6" only with ``watch`` on; opportunity alone shows nothing. */
export function FlagTag({ f, cfg, watch = false }: { f: PlayerFlag | undefined; cfg: FlagConfig | undefined; watch?: boolean }) {
  const t = flagTag(f, watch);
  if (!t || !f) return null;
  const tone = t.level ? FLAG_TONE[t.level] : "under";
  return (
    <span className="flag-tag" title={flagTitle(f, cfg)}>
      <span className={`tag ${tone}`}>
        {t.label} <span className="score">{t.score}</span>
      </span>
      <FlagMeter score={f.score} cfg={cfg} tone={tone} />
    </span>
  );
}

/** The breakout flag's legend behind an "i" (#113, #185): the levels lowest first, each as the
 * table draws it with its floor and what it recommends; each signal's rule and what it reads, a
 * silent one saying why; the opportunity-only rule and what the flags were read from today.
 * Every number from the API's config. ``label`` shows a short text beside the "i" (the Flags
 * card's "how flags work"); ``name`` names a bare one. */
export function FlagInfo({
  cfg,
  inputs,
  now,
  align = "left",
  label,
  name,
}: {
  cfg: FlagConfig | undefined;
  inputs: FlagInputs | undefined;
  now: number;
  align?: "left" | "right";
  label?: string;
  name?: string;
}) {
  if (!cfg) return null;
  const x = flagLegend(cfg, inputs, now);
  return (
    <Info title="the breakout flag" align={align} label={label} name={name} wide>
      <span>Signs that an available player may outlast his projection, which lags a role change by days. The flag never adds anyone.</span>
      <table className="flag-legend">
        <tbody>
          {x.levels.map((l) => (
            <tr key={l.level}>
              <td>
                <LevelTag level={l.level} />
              </td>
              <td>
                <b>{l.level}</b>
              </td>
              <td className="num">from {l.floor}</td>
              <td>{l.means}</td>
            </tr>
          ))}
          <tr className="dim">
            <td>
              <span className="tag under">under</span>
            </td>
            <td>under watch</td>
            <td className="num">below {x.under.below}</td>
            <td>{x.under.means}</td>
          </tr>
        </tbody>
      </table>
      {x.sample && (
        <span className="flag-sample">
          <span className="flag-tag">
            <span className={`tag ${FLAG_TONE[x.sample.level]}`}>
              {FLAG_SHORT[x.sample.level]} <span className="score">{flagScore(x.sample.score)}</span>
            </span>
            <FlagMeter score={x.sample.score} cfg={cfg} tone={FLAG_TONE[x.sample.level]} />
          </span>
          <span className="dim">
            The tag reads the level and the score, over a meter of the score up to {cfg.max} ticked at each floor; a tick the score reaches is brighter and thicker.
          </span>
        </span>
      )}
      <span className="dim">{x.scale} Four signals:</span>
      {x.signals.map((sg) => (
        <span key={sg.key}>
          <b>{sg.name}</b>: {sg.rule} <span className="dim">Reads {sg.reads}.</span>
          {sg.silent && <span className="bad"> Silent today: {sg.silent}.</span>}
        </span>
      ))}
      {x.alone && <span>{x.alone}</span>}
      <span className="dim">Read today: {x.read}.</span>
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
