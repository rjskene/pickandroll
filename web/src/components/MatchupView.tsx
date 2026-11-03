import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, CAT_LABEL, type Cat, type MatchupPayload, type MatchupPlayer, type MatchupTeamLines, type ProjectionSystem, type SeasonView } from "../api";
import {
  ageLabel,
  catValue,
  dayLabel,
  daysLeftLabel,
  gainLabel,
  leanTone,
  cellTitle,
  lineValue,
  MATCHUP_LINE_KEY,
  MATCHUP_LINE_VIEWS,
  matchupColumns,
  matchupExplainer,
  matchupLineView,
  matchupRecord,
  oddsGainLabel,
  oddsLabel,
  pctTitle,
  playerGames,
  playerLine,
  playersById,
  recordLabel,
  teamRows,
  type MatchupLineView,
} from "../season";
import Info from "./Info";

/** The per-game columns of the players' tables, in the league's order. */
const NINE: Cat[] = ["fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov"];

const WIN_TITLE =
  "The odds of winning more categories than I lose (a tie on categories counts half), each category's odds taken as independent of the others: a headline. Expected categories, the sum of the category odds, is the measure the moves use.";

/** The Matchup view (#116): this week's matchup as a scoreboard (the odds of winning it, Yahoo's
 * count so far and a diverging bar per category), then what each player of both teams adds to
 * it, from the move model's projection of the rest of the week. */
export default function MatchupView({
  league,
  s,
  system,
  setSystem,
  now,
}: {
  league: string;
  s: SeasonView;
  system: ProjectionSystem;
  setSystem: (x: ProjectionSystem) => void;
  now: number;
}) {
  const q = useQuery({
    queryKey: ["matchup", league, system, s.updated_at],
    queryFn: () => api.matchup(league, system),
    enabled: Boolean(s.my_team),
    // A new snapshot keeps the last scoreboard up while its own is projected; another system's
    // never stands in for this one's.
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[2] === system ? prev : undefined),
    refetchInterval: 60_000,
    retry: false,
  });
  const byId = useMemo(() => playersById(s), [s]);
  const [view, setView] = useState<MatchupLineView>(savedLine);
  useEffect(() => {
    try {
      localStorage.setItem(MATCHUP_LINE_KEY, view);
    } catch {
      // this browser keeps no line: Week total next time
    }
  }, [view]);
  if (!s.my_team) return <p className="muted">No team of mine in this league: the Matchup view needs my team id in its settings.</p>;
  if (q.error) return <p className="error">{q.error.message}</p>;
  const m = q.data;
  if (!m) return <p className="muted">Projecting the matchup…</p>;
  const team = (id: number) => s.teams.find((t) => t.team_id === id);
  const name = (id: number) => team(id)?.name ?? `Team ${id}`;
  const [mine, theirs] = m.teams;
  const points = s.scoring === "points";
  const w = s.week_projection;
  return (
    <div className="matchup-view">
      <div className="mu-hero">
        <div className="mu-side">
          <span className="k">Me</span>
          <span className="mu-team me">{name(mine)}</span>
          <span className="muted">{recordLabel(team(mine))}</span>
        </div>
        <div className="mu-mid">
          <span className="mu-huge" title={WIN_TITLE}>
            {oddsLabel(m.win)}
          </span>
          <span className="k">to win the matchup</span>
          <span className="mu-big">{matchupRecord(m, s.scoring)}</span>
          <span className="muted" title={m.so_far_at ? `the matchup page read ${ageLabel(m.so_far_at, now)}` : "the matchup page not read"}>
            {points ? "points so far" : "so far, as Yahoo counts it"} · {daysLeftLabel(m.days)}
            {!points && ` · ${m.expected.toFixed(1)} of ${m.cats.length} categories expected`}
          </span>
        </div>
        <div className="mu-side r">
          <span className="k">Them</span>
          <span className="mu-team them">{name(theirs)}</span>
          <span className="muted">{recordLabel(team(theirs))}</span>
          <select value={system} onChange={(e) => setSystem(e.target.value as ProjectionSystem)} aria-label="Projection" title={m.system.fallback ?? m.system.label}>
            {(["bbm", "yahoo"] as const).map((x) => (
              <option key={x} value={x}>
                {w.systems[x].label}
                {w.systems[x].players ? "" : " (none read)"}
              </option>
            ))}
          </select>
        </div>
      </div>
      {m.rosters_read.includes(false) && (
        <p className="banner">
          {m.rosters_read
            .map((read, i) => (read ? null : name(m.teams[i])))
            .filter(Boolean)
            .join(" and ")}
          : roster not read, so it projects as empty and the odds overstate the other side. {s.public ? "Refresh reads every team's page." : "Open the team's page in Chrome with the extension."}
        </p>
      )}
      <div className="mu-row head">
        <span className="k">Projected final · so far beneath</span>
        <span className="k c">the longer side wins the category · win likelihood</span>
        <span className="k r">Projected final · so far beneath</span>
      </div>
      {m.cats.map((c) => (
        <div className="mu-row" key={c.cat}>
          <div className="mu-vals">
            <span className="me">{catValue(c.cat, c.mine)}</span>
            <small>so far {catValue(c.cat, c.so_far[0]) || "—"}</small>
          </div>
          <div className="mu-cell" title={`${CAT_LABEL[c.cat]}: ${oddsLabel(c.p_win)} to win; spread of the difference ${catValue(c.cat, c.sd)}`}>
            <div className="mu-bar">
              <div className="l">
                <i style={{ width: `${c.p_win * 100}%` }} />
              </div>
              <div className="r">
                <i style={{ width: `${(1 - c.p_win) * 100}%` }} />
              </div>
            </div>
            <span className="mu-cat">{CAT_LABEL[c.cat]}</span>
            <span className={`mu-pill ${leanTone(c.p_win)}`}>{oddsLabel(c.p_win)}</span>
          </div>
          <div className="mu-vals r">
            <span className="them">{catValue(c.cat, c.theirs)}</span>
            <small>so far {catValue(c.cat, c.so_far[1]) || "—"}</small>
          </div>
        </div>
      ))}
      <div className="mu-lines">
        <span className="seg small" role="group" aria-label="Players' line">
          {MATCHUP_LINE_VIEWS.map((v) => (
            <button key={v.key} className={view === v.key ? "on" : undefined} aria-pressed={view === v.key} onClick={() => setView(v.key)} title={v.title}>
              {v.label}
            </button>
          ))}
        </span>
        {view !== "per_game" && view !== "rest" && m.unread.length > 0 && (
          <span className="muted">
            {m.unread.map((u) => `${dayLabel(u.day)}: not counted yet (matchup page read ${m.so_far_at ? ageLabel(m.so_far_at, now) : "never"}) · ${u.games[0]} and ${u.games[1]} games`).join("; ")}
          </span>
        )}
      </div>
      <Players
        title={`My players · ${name(mine)}`}
        note={m.from ? `what each adds to the ${oddsLabel(m.win)}: out from ${dayLabel(m.from)}, his starts refilled from the bench` : "the week has no day left: its score so far is its final"}
        rows={m.players.mine}
        team={m.team_lines.mine}
        view={view}
        m={m}
        mine
        points={points}
        player={(id) => byId.get(id)}
      />
      <Players
        title={`Their players · ${name(theirs)}`}
        note={`what each adds to ${name(theirs)}'s chances, the same way`}
        rows={m.players.theirs}
        team={m.team_lines.theirs}
        view={view}
        m={m}
        mine={false}
        points={points}
        player={(id) => byId.get(id)}
      />
    </div>
  );
}

function savedLine(): MatchupLineView {
  try {
    return matchupLineView(localStorage.getItem(MATCHUP_LINE_KEY));
  } catch {
    return "total";
  }
}

/** The G column's title in ``view``. */
function gamesTitle(view: MatchupLineView, from: string | null): string {
  if (view === "so_far") return "games counted so far (— when the box scores could not place them)";
  if (view === "total") return "games counted so far plus games left";
  return from ? `games left from ${dayLabel(from)}` : "games left: none, the week is over";
}

/** A team's players: their games and line in ``view`` (#304), the team's lines under them, and
 * the expected categories and matchup odds each adds for his team. */
function Players({
  title,
  note,
  rows,
  team,
  view,
  m,
  mine,
  points,
  player,
}: {
  title: string;
  note: string;
  rows: MatchupPlayer[];
  team: MatchupTeamLines;
  view: MatchupLineView;
  m: MatchupPayload;
  mine: boolean;
  points: boolean;
  player: (id: number) => { name: string; nba_team: string | null } | undefined;
}) {
  // What helps my team reads green; what helps theirs, red.
  const tone = (x: number) => (x === 0 ? "dim" : x > 0 === mine ? "good" : "bad");
  const cols: Cat[] = points ? [...NINE, "fpts"] : NINE;
  return (
    <div className="mu-players">
      <div className="k">
        {title} <span className="muted note">{note}</span>
      </div>
      <div className="mu-table">
        <table className="season-table">
          <thead>
            <tr>
              <th>Player</th>
              <th>Slot</th>
              <th className="num" title={gamesTitle(view, m.from)}>
                G
              </th>
              {cols.map((c) => (
                <th key={c} className="num" title={`${CAT_LABEL[c]} ${MATCHUP_LINE_VIEWS.find((v) => v.key === view)?.label.toLowerCase()}`}>
                  {CAT_LABEL[c]}
                </th>
              ))}
              {matchupColumns(points, m.from).map((c) => (
                <th key={c.key} className="num" title={c.title}>
                  {c.label}
                  <MatchupInfo points={points} column={c.label} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const p = player(r.player);
              const line = playerLine(r, view);
              const g = playerGames(r, view);
              const why = r.so_far.why;
              return (
                <tr key={r.player} className={r.games === 0 && view !== "so_far" ? "bench" : undefined}>
                  <td>
                    <span className="strong">{p?.name ?? `player ${r.player}`}</span>
                    {p?.nba_team && <span className="dim"> {p.nba_team}</span>}
                  </td>
                  <td className="dim">{r.slot}</td>
                  <td className="num" title={view === "so_far" ? (why ?? undefined) : r.started !== r.games ? `${r.started} of the ${r.games} left in a starting slot` : undefined}>
                    {g ?? "—"}
                  </td>
                  {cols.map((c) => (
                    <td key={c} className="num" title={cellTitle(c, line, view, why)}>
                      {view === "per_game" ? catValue(c, line?.[c]) : lineValue(c, line?.[c], view)}
                    </td>
                  ))}
                  {!points && <td className={`num ${tone(r.cats)}`}>{gainLabel(r.cats)}</td>}
                  <td className={`num ${tone(r.matchup)}`}>{oddsGainLabel(r.matchup)}</td>
                </tr>
              );
            })}
          </tbody>
          {view !== "per_game" && (
            <tfoot>
              {teamRows(team, view).map((t) => (
                <tr key={t.label} className="mu-team-line">
                  <td colSpan={2} title={t.title}>
                    {t.label}
                  </td>
                  <td className="num">{t.line.games ?? "—"}</td>
                  {cols.map((c) => (
                    <td key={c} className="num" title={pctTitle(c, t.line, view, null)}>
                      {lineValue(c, t.line[c], view)}
                    </td>
                  ))}
                  {!points && <td />}
                  <td />
                </tr>
              ))}
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

/** The "i" on the Cats and Matchup headers (#226): what both columns mean, in the Flag column's
 * explainer portal. */
function MatchupInfo({ points, column }: { points: boolean; column: string }) {
  return (
    <Info title={`the ${column} column`} align="right" name={`what ${column} means`} wide>
      {matchupExplainer(points).map((p) => (
        <span key={p.lead}>
          <b>{p.lead}</b> {p.text}
        </span>
      ))}
    </Info>
  );
}
