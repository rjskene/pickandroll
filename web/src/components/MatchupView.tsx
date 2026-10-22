import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, CAT_LABEL, type Cat, type MatchupPayload, type MatchupPlayer, type ProjectionSystem, type SeasonView } from "../api";
import { ageLabel, catValue, dayLabel, daysLeftLabel, gainLabel, leanTone, matchupRecord, oddsGainLabel, oddsLabel, playersById, recordLabel } from "../season";

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
      <Players
        title={`My players · ${name(mine)}`}
        note={`what each adds to the ${oddsLabel(m.win)}: out from ${dayLabel(m.from)}, his starts refilled from the bench`}
        rows={m.players.mine}
        m={m}
        mine
        points={points}
        player={(id) => byId.get(id)}
      />
      <Players
        title={`Their players · ${name(theirs)}`}
        note={`what each adds to ${name(theirs)}'s chances, the same way`}
        rows={m.players.theirs}
        m={m}
        mine={false}
        points={points}
        player={(id) => byId.get(id)}
      />
    </div>
  );
}

/** A team's players: games left, the per-game line, and the expected categories and matchup
 * odds each adds for his team. */
function Players({
  title,
  note,
  rows,
  m,
  mine,
  points,
  player,
}: {
  title: string;
  note: string;
  rows: MatchupPlayer[];
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
      <table className="season-table">
        <thead>
          <tr>
            <th>Player</th>
            <th>Slot</th>
            <th className="num" title={`games left from ${dayLabel(m.from)}`}>
              G
            </th>
            {cols.map((c) => (
              <th key={c} className="num" title={`${CAT_LABEL[c]} per game`}>
                {CAT_LABEL[c]}
              </th>
            ))}
            {!points && (
              <th className="num" title={`expected categories he adds: the week with him less the week without him from ${dayLabel(m.from)}`}>
                Cats
              </th>
            )}
            <th className="num" title="the matchup odds he adds, the same way">
              Matchup
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const p = player(r.player);
            return (
              <tr key={r.player} className={r.games === 0 ? "bench" : undefined}>
                <td>
                  <span className="strong">{p?.name ?? `player ${r.player}`}</span>
                  {p?.nba_team && <span className="dim"> {p.nba_team}</span>}
                </td>
                <td className="dim">{r.slot}</td>
                <td className="num" title={r.started !== r.games ? `${r.started} of them in a starting slot` : undefined}>
                  {r.games}
                </td>
                {cols.map((c) => (
                  <td key={c} className="num">
                    {catValue(c, r.per_game?.[c])}
                  </td>
                ))}
                {!points && <td className={`num ${tone(r.cats)}`}>{gainLabel(r.cats)}</td>}
                <td className={`num ${tone(r.matchup)}`}>{oddsGainLabel(r.matchup)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
