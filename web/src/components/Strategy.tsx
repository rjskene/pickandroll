import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  CAT_LABEL,
  type Cat,
  type MoveCategory,
  type MoveRef,
  type ProjectionSystem,
  type SeasonView,
  type StrategyMove,
  type StrategyPayload,
  type StrategyPoint,
  type StrategySource,
  type StrategyWeightKey,
} from "../api";
import {
  axisRange,
  axisTicks,
  dayLabel,
  defaultWeight,
  firstOrderLists,
  frontierMarks,
  gainLabel,
  gainTone,
  isSolving,
  milpLabel,
  oddsLabel,
  oddsTone,
  playersById,
  sourceText,
  strategySettingsChanged,
  strategyUnits,
  type FrontierMark,
} from "../season";

/** The weights' short names on the frontier and the tabs. */
const SHORT: Record<StrategyWeightKey, string> = { week: "this week", even: "even", natural: "natural", season: "season" };
const SOURCE_NAME: Record<StrategySource | "pending", string> = {
  search: "exact search",
  milp: "linear program",
  both: "both solvers",
  pending: "exact search, program running",
};

type MoveKey = Pick<MoveRef, "add" | "drop">;
type CatsByCat = Partial<Record<Cat, MoveCategory>>;

const cap = (x: string) => x.charAt(0).toUpperCase() + x.slice(1);

function toggled(list: number[], id: number): number[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

function LockIcon({ open }: { open: boolean }) {
  return (
    <svg width="10" height="11" viewBox="0 0 10 11" aria-hidden="true">
      <rect x="1" y="5" width="8" height="6" rx="1" fill="currentColor" />
      <path d={open ? "M3 5V3a2 2 0 0 1 4 0" : "M3 5V3a2 2 0 0 1 4 0v2"} fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

/** The Strategy card (#110): this week against the rest of the season. Solve runs the exact
 * search and the linear program at each weight of the two; the frontier plots each weight's
 * recommended set by what it gains this week and over the rest of the season, and a weight's tab
 * shows the set, which solver it came from, the categories before and after, and the program's
 * first-order ranking. Nothing solves on load, and nothing here acts in Yahoo. */
export default function Strategy({ league, s, system, onPick }: { league: string; s: SeasonView; system: ProjectionSystem; onPick: (m: MoveKey) => void }) {
  const queryClient = useQueryClient();
  const key = ["strategy", league, system, s.updated_at];
  const q = useQuery({
    queryKey: key,
    queryFn: () => api.strategy(league, system),
    enabled: Boolean(s.my_team),
    refetchInterval: (query) => (isSolving(query.state.data) ? 1000 : false),
    retry: false,
  });
  const d = q.data;
  // Null: the shown run's own locks and switch, until the panel changes them.
  const [chosenLock, setLock] = useState<number[] | null>(null);
  const [chosenOnly, setOnly] = useState<boolean | null>(null);
  const [chosen, setChosen] = useState<StrategyWeightKey | null>(null);
  const lock = chosenLock ?? d?.settings?.keep ?? [];
  const programOnly = chosenOnly ?? d?.settings?.program_only ?? false;
  const solve = useMutation({
    mutationFn: () => api.solveStrategy(league, system, { lock, program_only: programOnly }),
    onSuccess: (x) => queryClient.setQueryData(key, x),
  });
  const byId = useMemo(() => playersById(s), [s]);
  const name = (id: number | null) => (id == null ? "an open spot" : (byId.get(id)?.name ?? `player ${id}`));
  if (!s.my_team) return <p className="muted">The strategy needs my team: none is set for this league.</p>;
  if (q.error) return <p className="error">{q.error.message}</p>;
  if (!d) return <p className="muted">Reading the strategy…</p>;
  const solving = isSolving(d) || solve.isPending;
  const points = d.points ?? [];
  const at = points.find((p) => p.key === chosen) ?? points.find((p) => p.key === defaultWeight(points));
  const changed = d.status !== "not_solved" && strategySettingsChanged(d.settings, lock, programOnly);
  const units = strategyUnits(s.scoring);
  const toggleLock = (id: number) => setLock(toggled(lock, id));
  return (
    <>
      <div className="block strategy-go">
        <button className="small" disabled={solving} onClick={() => solve.mutate()} title="Run the exact search and the linear program at each weight, about 10-30 s">
          {solving ? "Solving…" : d.status === "not_solved" ? "Solve" : "Re-solve"}
        </button>
        <label className="muted small" title="Option B: the linear program's set whenever it solves to the gap, the search's only when it hits the time limit or finds no set">
          <input type="checkbox" checked={programOnly} onChange={(e) => setOnly(e.target.checked)} /> linear program alone
        </label>
        <span className="grow" />
        <RunState d={d} />
      </div>
      {solve.error && <p className="error">{solve.error.message}</p>}
      {changed && !solving && <p className="accent small">The locks or the switch changed since this run: Re-solve for their answer.</p>}
      {lock.length > 0 && (
        <p className="muted small">
          Locked:{" "}
          {lock.map((id, i) => (
            <span key={id}>
              {i > 0 && ", "}
              {name(id)}{" "}
              <button className="link" onClick={() => toggleLock(id)} title={`Unlock ${name(id)}: the solvers may drop him again`}>
                ×
              </button>
            </span>
          ))}
        </p>
      )}
      {d.status === "not_solved" ? (
        <p className="muted">
          Not solved yet. Solve weighs this week against the rest of the season: the recommended set at four weights, from this week alone to the rest of the
          season alone, each from the exact search and the linear program.
        </p>
      ) : (
        <>
          {points.some((p) => p.gain) && <Frontier marks={frontierMarks(points)} selected={at?.key ?? null} onSelect={setChosen} units={units} />}
          {points.length > 1 && (
            <div className="seg strategy-tabs" role="tablist" aria-label="Weight">
              {points.map((p) => (
                <button key={p.key} role="tab" aria-selected={p.key === at?.key} className={p.key === at?.key ? "on" : undefined} onClick={() => setChosen(p.key)} title={`${p.label}: λ ${p.lambda}`}>
                  {SHORT[p.key]}
                </button>
              ))}
            </div>
          )}
          {at && <Point p={at} d={d} s={s} name={name} units={units} lock={lock} onLock={toggleLock} onPick={onPick} />}
        </>
      )}
      <p className="dim small">
        {cap(d.horizons?.season.label ?? "rest of season")}: their average week times the {d.weeks_left ?? "remaining"} weeks left. Recommended, not
        proven best: each set is the better of two solvers on its weight&apos;s own value. Nothing here acts in Yahoo.
      </p>
    </>
  );
}

function RunState({ d }: { d: StrategyPayload }) {
  if (d.status === "solving") return <span className="accent small">{d.step ?? "solving"}…</span>;
  if (d.status === "failed") return <span className="bad small" title={d.error ?? undefined}>failed{d.step ? ` while ${d.step}` : ""}</span>;
  if (d.status === "cancelled") return <span className="muted small">replaced by a newer run</span>;
  if (d.status === "solved" && d.timing) return <span className="dim small">{d.timing.done != null ? `solved in ${d.timing.done.toFixed(1)} s` : "solved"}</span>;
  return null;
}

function Point({
  p,
  d,
  s,
  name,
  units,
  lock,
  onLock,
  onPick,
}: {
  p: StrategyPoint;
  d: StrategyPayload;
  s: SeasonView;
  name: (id: number | null) => string;
  units: { week: string; season: string };
  lock: number[];
  onLock: (id: number) => void;
  onPick: (m: MoveKey) => void;
}) {
  const limit = d.time_limit ?? 10;
  const min = d.min_gain ?? 0;
  if (!p.gain || !p.moves) return <p className="muted small">{p.label}: waiting for the search.</p>;
  const g = p.gain;
  const fo = firstOrderLists(
    p.first_order,
    d.pool ?? [],
    s.roster.map((r) => r.player.yahoo_id),
    p.moves,
  );
  return (
    <>
      <div className="block">
        <span className="k" title={`λ ${p.lambda}: ${gainLabel(g.weighted)} on the weight's own value`}>
          {p.label} · {gainLabel(g.week)} {units.week} this week · {gainLabel(g.season)} {units.season} over the rest of the season
        </span>
        <p className="muted small">{sourceText(p, limit)}</p>
        {p.moves.length === 0 ? (
          <p className="muted small">No set gains more than {min} at this weight: hold.</p>
        ) : (
          <table className="season-table strategy-moves">
            <thead>
              <tr>
                <th>Add</th>
                <th>For</th>
                <th title="the day he plays from: a waiver claim's clear date, when its drop leaves too">From</th>
                <th className="num" title="what the move adds to the set this week">
                  +1wk
                </th>
                <th className="num" title="what the move adds to the set over the three weeks ahead">
                  +3wk
                </th>
                <th className="num" title="what the set gives up on the weight's value when the search runs again without this add">
                  w/o
                </th>
                <th className="num" title="what the set gives up on the weight's value when the search runs again keeping this drop">
                  keep
                </th>
              </tr>
            </thead>
            <tbody>
              {p.moves.map((x) => (
                <MoveRow key={x.add} x={x} name={name} min={min} locked={x.drop != null && lock.includes(x.drop)} onLock={onLock} onPick={onPick} />
              ))}
            </tbody>
          </table>
        )}
      </div>
      {p.cats && (
        <div className="block">
          <span className="k" title="this week: the odds of winning each category against the opponent; the three weeks: expected weeks won against the field">
            Categories before and after
          </span>
          <Cats cats={s.settings.cats} week={p.cats.week} three={p.cats.three} />
        </div>
      )}
      {(fo.adds.length > 0 || fo.mine.length > 0) && (
        <div className="block">
          <span className="k" title="each player's line at the linear program's solution, over every game he plays: a ranking of whom to look at next, not a price">
            First-order values at the program&apos;s solution
          </span>
          <div className="strategy-fo">
            <FirstOrder title="Next to look at" rows={fo.adds} name={name} />
            <FirstOrder title="Mine, lowest" rows={fo.mine} name={name} />
          </div>
        </div>
      )}
      <Debug p={p} d={d} limit={limit} />
    </>
  );
}

function MoveRow({
  x,
  name,
  min,
  locked,
  onLock,
  onPick,
}: {
  x: StrategyMove;
  name: (id: number | null) => string;
  min: number;
  locked: boolean;
  onLock: (id: number) => void;
  onPick: (m: MoveKey) => void;
}) {
  const instead = (ms: MoveRef[] | null | undefined) =>
    ms == null ? "" : ms.length ? `adds ${ms.map((m) => `${name(m.add)} for ${name(m.drop)}`).join(", ")}` : "makes no move";
  return (
    <tr className="pick" onClick={() => onPick(x)} title="Open the move's own breakdown">
      <td className="strong">{name(x.add)}</td>
      <td>
        {name(x.drop)}{" "}
        {x.drop != null && (
          <button
            className={`link lock-toggle ${locked ? "on" : ""}`}
            aria-pressed={locked}
            onClick={(e) => {
              e.stopPropagation();
              onLock(x.drop!);
            }}
            title={locked ? `${name(x.drop)} is locked: the next solve never drops him` : `Lock ${name(x.drop)}: the next solve never drops him`}
          >
            <LockIcon open={!locked} />
          </button>
        )}
      </td>
      <td className="dim">{dayLabel(x.from)}</td>
      <td className={`num ${gainTone(x.marginal?.week, min)}`}>{gainLabel(x.marginal?.week)}</td>
      <td className="num dim">{gainLabel(x.marginal?.three)}</td>
      <td className="num" title={x.instead_without ? `without ${name(x.add)} the search ${instead(x.instead_without)}` : "pricing…"}>
        {x.price_without?.toFixed(2) ?? ""}
      </td>
      <td className="num" title={x.instead_keep ? `keeping ${name(x.drop)} the search ${instead(x.instead_keep)}` : "no drop to keep"}>
        {x.price_keep == null ? "" : x.price_keep.toFixed(2)}
      </td>
    </tr>
  );
}

/** Each category this week (the odds against the opponent) and over the three weeks ahead
 * (expected weeks won against the field), before and after the set. */
function Cats({ cats, week, three }: { cats: Cat[]; week: { before: CatsByCat; after: CatsByCat }; three: { before: CatsByCat; after: CatsByCat } }) {
  return (
    <table className="season-table">
      <thead>
        <tr>
          <th></th>
          <th className="num" title="the odds of winning the category this week without the set">
            win
          </th>
          <th className="num" title="with the set">
            after
          </th>
          <th className="num" title="expected weeks won over the three weeks ahead without the set">
            3wk
          </th>
          <th className="num" title="with the set">
            after
          </th>
        </tr>
      </thead>
      <tbody>
        {cats.map((c) => {
          const wb = week.before[c]?.wins;
          const wa = week.after[c]?.wins;
          const tb = three.before[c]?.wins;
          const ta = three.after[c]?.wins;
          const diff = ta != null && tb != null ? ta - tb : null;
          return (
            <tr key={c}>
              <td>{CAT_LABEL[c]}</td>
              <td className={`num dim ${wb != null ? oddsTone(wb) : ""}`}>{wb != null ? oddsLabel(wb) : ""}</td>
              <td className={`num ${wa != null ? oddsTone(wa) : ""}`}>{wa != null ? oddsLabel(wa) : ""}</td>
              <td className="num dim">{tb?.toFixed(2) ?? ""}</td>
              <td className={`num ${diff == null ? "" : diff > 0.005 ? "good" : diff < -0.005 ? "bad" : ""}`}>{ta?.toFixed(2) ?? ""}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function FirstOrder({ title, rows, name }: { title: string; rows: [number, number][]; name: (id: number) => string }) {
  if (!rows.length) return null;
  return (
    <table className="season-table">
      <thead>
        <tr>
          <th>{title}</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([id, v]) => (
          <tr key={id}>
            <td>{name(id)}</td>
            <td className="num dim">{v.toFixed(2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** The solvers' own figures: seconds, the program's size and status. */
function Debug({ p, d, limit }: { p: StrategyPoint; d: StrategyPayload; limit: number }) {
  const sr = p.search;
  const m = p.milp;
  const parts = [
    sr && `search ${sr.seconds.toFixed(2)} s${sr.pricing != null ? ` + pricing ${sr.pricing.toFixed(1)} s` : ""}`,
    m &&
      `program ${milpLabel(m, limit)}${m.seconds != null ? ` in ${m.seconds.toFixed(2)} s` : ""}${
        m.size ? `, ${m.size.variables} variables (${m.size.binaries} binary), ${m.size.constraints} constraints` : ""
      }`,
    m?.gain && `its set ${gainLabel(m.gain.weighted)} on the weight`,
    d.pool && `pool ${d.pool.length}`,
    d.timing?.first != null && `first answer ${d.timing.first.toFixed(1)} s`,
  ].filter(Boolean);
  return <p className="dim small strategy-debug">{parts.join(" · ")}</p>;
}

// ---------------------------------------------------------------- the frontier
// Drawn in viewBox units and scaled to the card's width.
const W = 380;
const H = 180;
const M = { left: 38, right: 14, top: 18, bottom: 26 };
const R = 5;

/** The weights' recommended sets: this week's gain across, the rest of the season's up, each
 * mark filled by its source (hollow the search's, solid the program's, half both) and the
 * natural weight ringed. Hover reads a mark; a click opens its weight. */
function Frontier({
  marks,
  selected,
  onSelect,
  units,
}: {
  marks: FrontierMark[];
  selected: StrategyWeightKey | null;
  onSelect: (k: StrategyWeightKey) => void;
  units: { week: string; season: string };
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [active, setActive] = useState<number | null>(null);
  const [x0, x1] = axisRange(marks.map((m) => m.x));
  const [y0, y1] = axisRange(marks.map((m) => m.y));
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const x = (v: number) => M.left + ((v - x0) / (x1 - x0)) * plotW;
  const y = (v: number) => M.top + (1 - (v - y0) / (y1 - y0)) * plotH;
  const nearest = (e: { clientX: number; clientY: number }) => {
    const box = svg.current?.getBoundingClientRect();
    if (!box || box.width === 0) return null;
    const vx = ((e.clientX - box.left) / box.width) * W;
    const vy = ((e.clientY - box.top) / box.height) * H;
    let best: number | null = null;
    let dist = 24;
    marks.forEach((m, i) => {
      const r = Math.hypot(x(m.x) - vx, y(m.y) - vy);
      if (r < dist) [best, dist] = [i, r];
    });
    return best;
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === "Enter" && active !== null) return onSelect(marks[active].keys[0]);
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const step = e.key === "ArrowLeft" ? -1 : 1;
    setActive((a) => (a === null ? 0 : (a + step + marks.length) % marks.length));
  };
  const m = active === null ? null : marks[active];
  const leftPct = m ? (x(m.x) / W) * 100 : 0;
  const topPct = m ? (y(m.y) / H) * 100 : 0;
  const tx = leftPct > 60 ? "-100%" : leftPct < 25 ? "0%" : "-50%";
  const ty = topPct > 50 ? "calc(-100% - 12px)" : "12px";
  const sources = new Set(marks.map((k) => k.source));
  // Marks too close to label apart carry one label, on the first of them.
  const labels = marks.map((k) => k.keys.map((w) => SHORT[w]));
  marks.forEach((k, i) => {
    const j = marks.findIndex((o, oi) => oi < i && labels[oi].length > 0 && Math.hypot(x(o.x) - x(k.x), y(o.y) - y(k.y)) < 3 * R);
    if (j >= 0) [labels[j], labels[i]] = [[...labels[j], ...labels[i]], []];
  });
  return (
    <div className="score-chart frontier">
      <svg
        ref={svg}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Recommended sets: ${marks.map((k) => `${k.keys.map((w) => SHORT[w]).join(" and ")} ${gainLabel(k.x)} this week, ${gainLabel(k.y)} rest of season`).join("; ")}`}
        tabIndex={0}
        onPointerMove={(e) => setActive(nearest(e))}
        onPointerLeave={() => setActive(null)}
        onClick={(e) => {
          const i = nearest(e);
          if (i !== null) onSelect(marks[i].keys[0]);
        }}
        onFocus={() => setActive((a) => a ?? 0)}
        onBlur={() => setActive(null)}
        onKeyDown={onKey}
      >
        {axisTicks(y0, y1).map((t) => (
          <g key={`y${t}`}>
            <line className="grid" x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} />
            <text className="tick" x={M.left - 5} y={y(t)} dy="0.32em" textAnchor="end">
              {t}
            </text>
          </g>
        ))}
        {axisTicks(x0, x1).map((t) => (
          <text key={`x${t}`} className="tick" x={x(t)} y={H - M.bottom + 12} textAnchor="middle">
            {t}
          </text>
        ))}
        <line className="ref" x1={x(0)} x2={x(0)} y1={M.top} y2={M.top + plotH} />
        <line className="ref" x1={M.left} x2={W - M.right} y1={y(0)} y2={y(0)} />
        <text className="tick" x={M.left} y={M.top - 7}>
          rest of season, {units.season}
        </text>
        <text className="tick" x={W - M.right} y={H - 3} textAnchor="end">
          this week, {units.week}
        </text>
        {marks.map((k, i) => {
          const cx = x(k.x);
          const cy = y(k.y);
          const on = k.keys.includes(selected as StrategyWeightKey) || i === active;
          const right = cx > W - 90;
          const gap = R + (k.natural ? 9 : 6);
          return (
            <g key={k.keys.join("-")} className={`mark ${k.source} ${on ? "on" : ""}`}>
              {k.natural && <circle className="natural-ring" cx={cx} cy={cy} r={R + 4} />}
              <Glyph source={k.source} cx={cx} cy={cy} r={R} />
              {labels[i].length > 0 && (
                <text className="mark-label" x={right ? cx - gap : cx + gap} y={cy} dy="0.32em" textAnchor={right ? "end" : "start"}>
                  {labels[i].join(" · ")}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {m && (
        <div className="tip" role="status" style={{ left: `${leftPct}%`, top: `${topPct}%`, transform: `translate(${tx}, ${ty})` }}>
          <div className="v">{gainLabel(m.x)}</div>
          <div className="muted">
            {units.week} this week · {gainLabel(m.y)} {units.season} over the rest of the season
          </div>
          <div>{m.keys.map((w) => SHORT[w]).join(", ")}</div>
          <div className="dim">{SOURCE_NAME[m.source]}</div>
        </div>
      )}
      <div className="key dim">
        {(["search", "milp", "both", "pending"] as const)
          .filter((k) => sources.has(k))
          .map((k) => (
            <span key={k}>
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" className={`mark ${k}`}>
                <Glyph source={k} cx={6} cy={6} r={4} />
              </svg>
              {SOURCE_NAME[k]}
            </span>
          ))}
        {marks.some((k) => k.natural) && <span>ringed: every week alike</span>}
      </div>
    </div>
  );
}

/** A mark by its source: hollow the search's, solid the program's, half and half both. */
function Glyph({ source, cx, cy, r }: { source: StrategySource | "pending"; cx: number; cy: number; r: number }) {
  return (
    <>
      <circle className="glyph" cx={cx} cy={cy} r={r} />
      {source === "both" && <path className="half" d={`M${cx},${cy - r} A${r},${r} 0 0 0 ${cx},${cy + r} Z`} />}
    </>
  );
}
