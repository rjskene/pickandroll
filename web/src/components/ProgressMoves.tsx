import { Fragment, useState } from "react";
import { CAT_LABEL, type Cat, type MatchKind, type ProgressMove, type ProgressPayload, type Scoring } from "../api";
import { pct } from "../format";
import {
  entryTime,
  HORIZON_SHORT,
  KNOB_SHORT,
  knobValue,
  MATCH_SHORT,
  MATCH_TITLE,
  MATCH_TONE,
  matchCounts,
  moveCats,
  moveFigures,
  moveKey,
  movesTotals,
  movesTrend,
  POOLED,
  scopeMoves,
  scopeSentences,
  UNITS,
  UNITS_SHORT,
  type MatchFilter,
} from "../progress";
import { dayLabel, gainLabel, MATCH_WORDS, ordinal, realizedTitle, unitsLabel } from "../season";
import ProgressChart from "./ProgressChart";
import { knobMarkers, NothingScored, ScopeHead, Sentences, Tile, viewRange } from "./ProgressParts";

// The Moves view and the Move card (#129): every move made over the weeks shown, its value
// projected at decision time against its realized value on the horizon it was recommended for,
// in its league's units, by how it matched the solve before it.

const MATCHES: MatchKind[] = ["as_recommended", "differently", "not_recommended", "no_entry"];
const SET_WORDS: Record<string, string> = { week: "the week's set", three: "the three weeks' set", plan: "the streaming plan" };

const nameOf = (m: ProgressMove, side: "add" | "drop") => {
  const id = m[side];
  return id == null ? null : (m.names[side] ?? `player ${id}`);
};
const catName = (cat: string) => CAT_LABEL[cat as Cat] ?? cat.toUpperCase();
const madeAt = (m: ProgressMove) => (m.at ? m.at.slice(0, 16).replace("T", " ") : m.day);
const digits = (s: Scoring) => (s === "points" ? 1 : 2);

export function MovesView({
  p,
  scope,
  onScope,
  range,
  setRange,
  match,
  setMatch,
  chosen,
  onMove,
  onChange,
}: {
  p: ProgressPayload;
  scope: string;
  onScope: (scope: string) => void;
  range: [number, number] | null;
  setRange: (r: [number, number] | null) => void;
  match: MatchFilter;
  setMatch: (m: MatchFilter) => void;
  chosen: string | null;
  onMove: (key: string) => void;
  onChange: (id: string) => void;
}) {
  const [unit, setUnit] = useState<Scoring | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const { bounds, from, to, step } = viewRange(p, scope, range, setRange);
  const all = bounds ? scopeMoves(p, scope, from, to) : [];
  const moves = match === "all" ? all : all.filter((m) => m.match.kind === match);
  const counts = matchCounts(all);
  const totals = movesTotals(moves);
  const units = (["categories", "points"] as Scoring[]).filter((s) => totals.compared[s]);
  const shown = unit && units.includes(unit) ? unit : (units[0] ?? null);
  const complete = units.reduce((n, s) => n + totals.compared[s]!.moves, 0);
  const weeks = bounds ? Array.from({ length: to - from + 1 }, (_, i) => from + i) : [];
  const line = shown ? movesTrend(moves, weeks, shown) : [];
  const say = scopeSentences(p.sentences, scope).filter((s) => s.topic === "moves");
  const rows = [...moves].sort((a, b) => (b.at ?? b.day ?? "").localeCompare(a.at ?? a.day ?? "") || a.league.localeCompare(b.league));
  const pooled = scope === POOLED;
  const cols = pooled ? 11 : 10;
  return (
    <div className="season-view progress-view">
      <ScopeHead p={p} title={`Moves · ${all.length} made`} scope={scope} onScope={onScope} bounds={bounds} from={from} to={to} setRange={setRange} onStep={step}>
        {all.length > 0 && (
          <span className="seg small" role="group" aria-label="Match">
            <button className={match === "all" ? "on" : undefined} aria-pressed={match === "all"} onClick={() => setMatch("all")}>
              All · {all.length}
            </button>
            {MATCHES.filter((k) => counts[k] > 0).map((k) => (
              <button key={k} className={match === k ? "on" : undefined} aria-pressed={match === k} title={MATCH_TITLE[k]} onClick={() => setMatch(k)}>
                {MATCH_WORDS[k]} · {counts[k]}
              </button>
            ))}
          </span>
        )}
      </ScopeHead>
      {!bounds ? (
        <NothingScored scope={scope} />
      ) : !all.length ? (
        <p className="muted pg-empty">No move made over weeks {from} to {to}{pooled ? " in the public leagues" : ` in league ${scope}`}.</p>
      ) : (
        <>
          <div className="pg-tiles">
            <Tile k="projected" v={units.length ? units.map((s) => `${gainLabel(totals.compared[s]!.projected, digits(s))}${units.length > 1 ? ` ${UNITS_SHORT[s]}` : ""}`).join(" · ") : "—"} title="the moves' value as their solve projected it, on the horizon each was recommended for; the moves whose horizon is over">
              {units.length ? `${complete} move${complete === 1 ? "" : "s"} over a complete horizon` : "no move's horizon is over yet"}
            </Tile>
            <Tile
              k="realized"
              v={units.length ? units.map((s) => `${gainLabel(totals.compared[s]!.realized, digits(s))}${units.length > 1 ? ` ${UNITS_SHORT[s]}` : ""}`).join(" · ") : "—"}
              title="the added player's line from the move to the end of its horizon against the dropped player's over the same days, in the units the move was valued in"
            >
              {units.map((s) => {
                const c = totals.compared[s]!;
                return (
                  <span key={s} className="pg-unit">
                    {c.share == null ? "" : `${pct(c.share)} of projected · `}in {UNITS[s]}
                  </span>
                );
              })}
              {(totals.soFar > 0 || totals.unscored > 0) && (
                <span className="pg-unit dim">
                  {[totals.soFar ? `${totals.soFar} still inside their horizon` : null, totals.unscored ? `${totals.unscored} not valued` : null].filter(Boolean).join(" · ")}
                </span>
              )}
            </Tile>
            <Tile k="paid" v={`$${totals.paid}`} title="the FAAB bid on the moves that cleared waivers">
              FAAB · {totals.made - totals.bids} free, {totals.bids} bid
            </Tile>
          </div>
          {say.length > 0 && <Sentences say={say} />}
          {shown && (
            <>
              <div className="row pg-chart-head">
                <span className="k">Realized against projected, summed to each week</span>
                {units.length > 1 ? (
                  <span className="seg small" role="tablist" aria-label="Units">
                    {units.map((s) => (
                      <button key={s} role="tab" aria-selected={shown === s} className={shown === s ? "on" : undefined} onClick={() => setUnit(s)} title={`the moves of the ${s} leagues: their units never sum with the others'`}>
                        {UNITS[s]}
                      </button>
                    ))}
                  </span>
                ) : (
                  <span className="dim small">in {UNITS[shown]}</span>
                )}
              </div>
              <ProgressChart
                weeks={line.map((x) => x.week)}
                series={[
                  { key: "realized", label: "realized", tone: "actual", values: line.map((x) => x.realized) },
                  { key: "projected", label: "projected at decision time", tone: "expected", values: line.map((x) => x.projected) },
                ]}
                markers={knobMarkers(p, from, to, onChange)}
                markerKey="knob change · click for its sheet"
                fmt={(v) => gainLabel(v, digits(shown))}
                tickFmt={(v) => (Number.isInteger(v) ? String(v) : v.toFixed(digits(shown)))}
                label={`The moves' realized value against projected, summed to each week, in ${UNITS[shown]}`}
                tip={(i) => (
                  <>
                    <div className="muted">week {line[i].week} · summed to it</div>
                    <div className="v">{gainLabel(line[i].realized, digits(shown))} realized</div>
                    <div className="muted">{gainLabel(line[i].projected, digits(shown))} projected</div>
                  </>
                )}
              />
            </>
          )}
          <p className="dim small">A row opens the move in the panel; ▸ opens its categories. Each figure is in its league's units, on the horizon its set was recommended for.</p>
          <div className="pg-scroll">
            <table className="season-table pg-moves">
              <thead>
                <tr>
                  <th>Date</th>
                  {pooled && <th>League</th>}
                  <th>Add</th>
                  <th>For</th>
                  <th title="the horizon the move was recommended for and is judged on">Horizon</th>
                  <th className="num" title="the FAAB bid; blank for a free agent">
                    Bid
                  </th>
                  <th title="how the move compares with the solve logged before it">Match</th>
                  <th className="num" title="its value as its solve projected it, from the decision log">
                    Projected
                  </th>
                  <th className="num" title="the added player's line from the move to the end of the horizon against the dropped player's over the same days; so far while the horizon runs">
                    Realized
                  </th>
                  <th className="num" title="realized less projected, once the horizon is over">
                    Δ
                  </th>
                  <th aria-label="Categories" />
                </tr>
              </thead>
              <tbody>
                {rows.map((m) => {
                  const key = moveKey(m);
                  const f = moveFigures(m);
                  const k = m.match.kind;
                  const add = nameOf(m, "add");
                  const drop = nameOf(m, "drop");
                  const expanded = open === key;
                  return (
                    <Fragment key={key}>
                      <tr className={["pick", chosen === key ? "mine" : ""].filter(Boolean).join(" ")} onClick={() => onMove(key)} title={realizedTitle(m, m.scoring)}>
                        <td>{dayLabel(m.day)}</td>
                        {pooled && (
                          <td className="strong">
                            {m.league}
                            {!m.public && <div className="dim small">private</div>}
                          </td>
                        )}
                        <td>{add ?? <span className="dim">—</span>}</td>
                        <td className="muted" title={m.detail ?? undefined}>
                          {drop ?? (add ? "an open spot" : "")}
                        </td>
                        <td>{HORIZON_SHORT[f.horizon]}</td>
                        <td className="num">{m.bid == null ? "" : `$${m.bid}`}</td>
                        <td>
                          <span className={`tag ${MATCH_TONE[k]}`} title={MATCH_TITLE[k]}>
                            {MATCH_SHORT[k]}
                          </span>
                          {m.match.near && (
                            <span className="dim" title="within an hour of a solve: a time zone off by an hour could change the match">
                              {" "}
                              *
                            </span>
                          )}
                        </td>
                        <td className="num">{f.projected == null ? <span className="dim">—</span> : unitsLabel(f.projected, m.scoring)}</td>
                        <td className="num">
                          {f.realized == null ? (
                            <span className="dim">—</span>
                          ) : (
                            <>
                              {unitsLabel(f.realized, m.scoring)}
                              {!f.complete && (
                                <>
                                  {" "}
                                  <span className="tag tie">so far</span>
                                </>
                              )}
                            </>
                          )}
                        </td>
                        <td className={`num ${f.delta == null ? "dim" : f.delta >= 0 ? "good" : "bad"}`}>{f.delta == null ? "—" : unitsLabel(f.delta, m.scoring)}</td>
                        <td>
                          <button
                            className="link"
                            aria-expanded={expanded}
                            aria-label={`${expanded ? "Fold" : "Open"} the categories`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setOpen(expanded ? null : key);
                            }}
                          >
                            {expanded ? "▾" : "▸"}
                          </button>
                        </td>
                      </tr>
                      {expanded && (
                        <tr className="breakdown">
                          <td colSpan={cols}>
                            <MoveCatBars m={m} onOpen={() => onMove(key)} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

/** A move's value by category on its horizon: a bar for the realized, a tick for the projected,
 * on one scale around zero. */
function MoveCatBars({ m, onOpen }: { m: ProgressMove; onOpen: () => void }) {
  const c = moveCats(m);
  const f = moveFigures(m);
  const d = digits(m.scoring ?? "categories");
  if (!c.rows.length) {
    return (
      <div className="flag-breakdown">
        <span className="dim">No value by category: the solve before it logged none (entries before #129 keep none), or a player is not matched to the box scores yet.</span>
      </div>
    );
  }
  const values = c.rows.flatMap((r) => [r.projected, r.realized]).filter((v): v is number => v != null);
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const at = (v: number) => ((v - lo) / (hi - lo || 1)) * 100;
  const zero = at(0);
  return (
    <div className="flag-breakdown pg-cats">
      {c.rows.map((r) => (
        <div key={r.cat} className="pg-cat">
          <span className="fb-name">{catName(r.cat)}</span>
          <div className="fb-bar pg-bar">
            {lo < 0 && <b style={{ left: `${zero}%` }} />}
            {r.realized != null && <span className={r.realized < 0 ? "neg" : undefined} style={{ left: `${Math.min(zero, at(r.realized))}%`, width: `${Math.abs(at(r.realized) - zero)}%` }} />}
            {r.projected != null && <i style={{ left: `${at(r.projected)}%` }} />}
          </div>
          <span className="num muted">{gainLabel(r.projected, d)}</span>
          <span className="num">{gainLabel(r.realized, d)}</span>
        </div>
      ))}
      <div className="pg-cat sum">
        <span className="fb-name">sum</span>
        <span className="dim small">bar realized · tick projected</span>
        <span className="num muted">{gainLabel(f.projected, d)}</span>
        <span className="num">
          <b>{gainLabel(f.realized, d)}</b>
        </span>
        <span className="muted">
          {!f.complete ? "so far: the horizon still runs · " : c.both ? `${c.above} of ${c.both} above projection · ` : ""}
          <button className="link" onClick={onOpen}>
            open in the panel
          </button>
        </span>
      </div>
    </div>
  );
}

/** The Move card: the move chosen in the table. */
export function MoveCard({ p, m }: { p: ProgressPayload; m: ProgressMove | null }) {
  if (!m) {
    return <p className="muted small">Pick a move in the table: its value projected against realized, the knobs in force when it was solved, how it matched the solve, and its week's odds.</p>;
  }
  const f = moveFigures(m);
  const s = m.scoring ?? "categories";
  const add = nameOf(m, "add");
  const drop = nameOf(m, "drop");
  const k = m.match.kind;
  const knobs = Object.entries(m.knobs ?? {}).filter(([, v]) => v != null);
  const logged = entryTime(m.match.entry);
  const week = p.leagues.find((l) => l.league === m.league)?.weeks.find((w) => w.week === m.week);
  const odds = m.projected?.odds;
  const set = m.projected?.set;
  const oddsLine = (side: "before" | "after") => {
    const o = odds?.[side];
    if (!o) return null;
    return [o.matchup != null ? `${pct(o.matchup)} to win` : null, o.expected != null ? `${o.expected.toFixed(1)} categories expected` : null].filter(Boolean).join(", ");
  };
  return (
    <>
      <div className="hero">
        <div className="pg-names">
          <span className="name">{add ?? drop}</span>
          {add && (
            <>
              <span className="muted">for</span>
              <span className="name other">{drop ?? "an open spot"}</span>
            </>
          )}
          {!add && <span className="muted">dropped</span>}
        </div>
        <div className="stats">
          <div className="stat">
            <span className="k">projected</span>
            <span className="v">{f.projected == null ? "—" : unitsLabel(f.projected, s)}</span>
          </div>
          <div className="stat">
            <span className="k">realized{f.realized != null && !f.complete ? " so far" : ""}</span>
            <span className="v accent">{f.realized == null ? "—" : unitsLabel(f.realized, s)}</span>
          </div>
          <div className="stat">
            <span className="k">horizon</span>
            <span className="v">{HORIZON_SHORT[f.horizon]}</span>
          </div>
          {m.bid != null && (
            <div className="stat">
              <span className="k">bid</span>
              <span className="v">${m.bid}</span>
            </div>
          )}
        </div>
        <div className="muted small">
          <span className={`tag ${MATCH_TONE[k]}`}>{MATCH_WORDS[k]}</span> {MATCH_TITLE[k]}
          {set ? `, ${SET_WORDS[set] ?? "the strategy's set"}` : ""}.
        </div>
        <div className="dim small">
          {[logged ? `solved ${logged}` : null, `made ${madeAt(m)}`, m.detail, `league ${m.league}${m.public ? "" : " · private"}`].filter(Boolean).join(" · ")}
          {m.match.near ? " · within an hour of a solve: a time zone off by an hour could change the match" : ""}
        </div>
      </div>
      <div className="block">
        <span className="k">Knobs then</span>
        <p className="small">{knobs.length ? knobs.map(([name, v]) => `${KNOB_SHORT[name as keyof typeof KNOB_SHORT] ?? name} ${knobValue(v)}`).join(" · ") : <span className="dim">not logged with its solve</span>}</p>
      </div>
      <div className="block">
        <span className="k">The matchup it was for · week {m.week}</span>
        <p className="small">
          {week?.outcome
            ? `${week.outcome === "W" ? "Won" : week.outcome === "L" ? "Lost" : "Tied"}${s === "categories" && week.categories != null ? `, ${week.categories} categories${week.expected_categories != null ? ` against ${week.expected_categories.toFixed(1)} expected` : ""}` : ""}${week.expected != null ? ` · ${pct(week.expected)} to win at the week's start` : ""}${week.rank != null ? ` · ${ordinal(week.rank)} after it` : ""}.`
            : "Not scored yet."}
        </p>
        <p className="small">
          {odds && (odds.before || odds.after) ? (
            <>
              With its set: before {oddsLine("before") ?? "not logged"}; after {oddsLine("after") ?? "not logged"}.
            </>
          ) : (
            <span className="dim">No odds logged with its set: only a move made as recommended carries them, from the entries of #129 on.</span>
          )}
        </p>
      </div>
      <div className="block">
        <span className="k">Realized</span>
        <p className="small dim">{realizedTitle(m, s) || "not valued yet"}</p>
      </div>
    </>
  );
}
