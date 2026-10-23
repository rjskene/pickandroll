import { Fragment } from "react";
import type { ProgressPayload } from "../api";
import { pct } from "../format";
import { POOLED, recordLabel, scopeWeeks, UNITS } from "../progress";
import { ordinal, unitsLabel } from "../season";
import { NothingScored, ScopeHead, signed1, viewRange, weekDates } from "./ProgressParts";

/** The Table view (#129): every league by week, the newest first, each week under a row of the
 * public leagues' sum: the result against its odds, the categories, the moves, the place. */
export function TableView({
  p,
  scope,
  onScope,
  range,
  setRange,
}: {
  p: ProgressPayload;
  scope: string;
  onScope: (scope: string) => void;
  range: [number, number] | null;
  setRange: (r: [number, number] | null) => void;
}) {
  const { bounds, from, to, step } = viewRange(p, scope, range, setRange);
  const pooled = scope === POOLED;
  const leagues = (pooled ? [...p.leagues.filter((l) => l.public), ...p.leagues.filter((l) => !l.public)] : p.leagues.filter((l) => l.league === scope)).filter((l) => l.weeks.length > 0);
  const sums = new Map(scopeWeeks(p, POOLED, from, to).map((w) => [w.week, w]));
  const weeks = bounds ? Array.from({ length: to - from + 1 }, (_, i) => to - i) : [];
  return (
    <div className="season-view progress-view">
      <ScopeHead p={p} title="Every league by week" scope={scope} onScope={onScope} bounds={bounds} from={from} to={to} setRange={setRange} onStep={step} />
      {!bounds ? (
        <NothingScored scope={scope} />
      ) : (
        <div className="pg-scroll">
          <table className="season-table pg-table">
            <thead>
              <tr>
                <th>League</th>
                <th>Result</th>
                <th className="num" title="the odds of winning the matchup, as the decision log held them at the week's start">
                  Odds
                </th>
                <th className="num" title="the result less its odds: a win at 70% is +0.3">
                  Δ
                </th>
                <th className="num" title="categories won, a tie as half, against those expected; categories leagues only">
                  Cats
                </th>
                <th className="num" title="moves made in the week">
                  Moves
                </th>
                <th className="num" title="the week's moves' realized value, in the league's units: fantasy points, or category value">
                  Realized
                </th>
                <th className="num" title="the place after the week">
                  Stand
                </th>
              </tr>
            </thead>
            <tbody>
              {weeks.map((n) => {
                const sum = sums.get(n);
                const cal = p.weeks.find((w) => w.week === n);
                return (
                  <Fragment key={n}>
                    <tr className="pg-wk">
                      <td colSpan={8}>
                        <b>WK {n}</b>
                        {cal && <span className="dim"> · {weekDates(cal)}</span>}
                        {pooled && sum && sum.projected > 0 && (
                          <span className="muted">
                            {" "}
                            · public {recordLabel(sum.record)} · {sum.expected.toFixed(1)} expected ·{" "}
                            <span className={Math.abs(sum.won - sum.expected) < 0.05 ? "dim" : sum.won > sum.expected ? "good" : "bad"}>{signed1(sum.won - sum.expected)}</span>
                          </span>
                        )}
                        {p.knobs.changes
                          .filter((c) => c.week === n)
                          .map((c) => (
                            <span key={c.id} className="accent">
                              {" "}
                              · {c.id} started
                            </span>
                          ))}
                      </td>
                    </tr>
                    {leagues.map((l) => {
                      const w = l.weeks.find((x) => x.week === n);
                      if (!w) return null;
                      const gap = w.won != null && w.expected != null ? w.won - w.expected : null;
                      const s = l.scoring ?? "categories";
                      return (
                        <tr key={l.league} className={scope === l.league ? "mine" : undefined}>
                          <td>
                            <button className="link" onClick={() => onScope(l.league)} title="choose this league: the League card shows it">
                              {l.league}
                            </button>
                            {!l.public && <span className="dim small"> · private</span>}
                          </td>
                          <td>{w.outcome ?? "—"}</td>
                          <td className="num">{w.expected == null ? "" : pct(w.expected)}</td>
                          <td className={`num ${gap == null || Math.abs(gap) < 0.05 ? "dim" : gap > 0 ? "good" : "bad"}`}>{gap == null ? "" : signed1(gap)}</td>
                          <td className="num">{w.categories != null ? `${w.categories}${w.expected_categories != null ? ` / ${w.expected_categories.toFixed(1)}` : ""}` : ""}</td>
                          <td className="num">{w.moves.made || ""}</td>
                          <td className="num" title={UNITS[s]}>
                            {w.moves.realized == null ? "" : unitsLabel(w.moves.realized, s)}
                          </td>
                          <td className="num">{w.rank == null ? "" : `${ordinal(w.rank)}${w.teams ? ` of ${w.teams}` : ""}`}</td>
                        </tr>
                      );
                    })}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
