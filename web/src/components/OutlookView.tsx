import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, CAT_LABEL, type OutlookPayload, type OutlookWeek, type ProjectionSystem, type SeasonView } from "../api";
import { catValue, chipTone, dayLabel, daysLeftLabel, defaultWeek, gainLabel, leanTone, matchupRecord, oddsGainLabel, oddsLabel, outlookSummary, playersById, recordLabel } from "../season";

const CHIP_TITLE: Record<ReturnType<typeof chipTone>, string> = {
  good: "favoured: 60% or better to win",
  warn: "a toss-up: between 40% and 60%",
  bad: "an underdog: 40% or worse",
  field: "against the field: the pairs are not known, so the odds are the average over the other teams",
  unread: "no odds: no roster faced was read",
};

/** The Season view (#116, the outlook route): every week left of my season as a strip of chips (the opponent and
 * the odds of winning, coloured by the 60% and 40% lines, grey against the field), the summary
 * of the regular weeks above it, and the week a chip opens beneath: a smaller scoreboard and my
 * players that week. Next week opens first. Rosters are today's: nobody added or dropped. */
export default function OutlookView({
  league,
  s,
  system,
  setSystem,
}: {
  league: string;
  s: SeasonView;
  system: ProjectionSystem;
  setSystem: (x: ProjectionSystem) => void;
}) {
  const q = useQuery({
    queryKey: ["outlook", league, system, s.updated_at],
    queryFn: () => api.outlook(league, system),
    enabled: Boolean(s.my_team),
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[2] === system ? prev : undefined),
    refetchInterval: 60_000,
    retry: false,
  });
  const [open, setOpen] = useState<number | null>(null);
  const byId = useMemo(() => playersById(s), [s]);
  if (!s.my_team) return <p className="muted">No team of mine in this league: the Season view needs my team id in its settings.</p>;
  if (q.error) return <p className="error">{q.error.message}</p>;
  const o = q.data;
  if (!o) return <p className="muted">Projecting the season…</p>;
  const team = (id: number) => s.teams.find((t) => t.team_id === id);
  const name = (id: number) => team(id)?.name ?? `Team ${id}`;
  const shown = o.weeks.find((w) => w.week === (open ?? defaultWeek(o.weeks))) ?? null;
  const w = s.week_projection;
  return (
    <div className="season-view">
      <div className="sv-head">
        <div className="sv-title">
          <span className="k">Season · {name(o.team)}</span>
          <span className="sv-record">{o.record ?? "no record"}</span>
          <span className="muted">today</span>
        </div>
        <p className="sv-summary">{outlookSummary(o.summary).join(" · ")}</p>
        <select value={system} onChange={(e) => setSystem(e.target.value as ProjectionSystem)} aria-label="Projection" title={o.system.fallback ?? o.system.label}>
          {(["bbm", "yahoo"] as const).map((x) => (
            <option key={x} value={x}>
              {w.systems[x].label}
              {w.systems[x].players ? "" : " (none read)"}
            </option>
          ))}
        </select>
      </div>
      <div className="sv-strip" aria-label="Weeks left">
        {o.weeks.map((x, i) => {
          const tone = chipTone(x);
          const against = x.opponent != null ? name(x.opponent) : "field";
          return (
            <Fragment key={x.week}>
              {x.playoffs && !o.weeks[i - 1]?.playoffs && <span className="sv-split">Playoffs</span>}
              <button
                className={`sv-chip ${tone}`}
                aria-pressed={shown?.week === x.week}
                onClick={() => setOpen(x.week)}
                title={`Week ${x.week}, ${dayLabel(x.start)} – ${dayLabel(x.end)}: ${x.opponent != null ? `vs ${against}, ` : ""}${CHIP_TITLE[tone]}`}
              >
                <span className="wk">
                  W{x.week}
                  {x.this_week && <em> now</em>}
                </span>
                <span className="opp">{against}</span>
                <span className="odds">{x.win != null ? oddsLabel(x.win) : "—"}</span>
              </button>
            </Fragment>
          );
        })}
      </div>
      {o.first_playoff_week == null && <p className="muted note">The playoffs' first week is not known yet, so every week counts as a regular one.</p>}
      {shown && <WeekDetail w={shown} o={o} s={s} name={name} recordOf={(id) => recordLabel(team(id))} player={(id) => byId.get(id)} />}
    </div>
  );
}

/** One week: its odds against the opponent (or the field), a bar per category, and my players
 * that week with what each adds. */
function WeekDetail({
  w,
  o,
  s,
  name,
  recordOf,
  player,
}: {
  w: OutlookWeek;
  o: OutlookPayload;
  s: SeasonView;
  name: (id: number) => string;
  recordOf: (id: number) => string;
  player: (id: number) => { name: string; nba_team: string | null } | undefined;
}) {
  const points = s.scoring === "points";
  const against = w.opponent != null ? name(w.opponent) : w.field ? `the field (${w.field} teams)` : "the field";
  const tone = (x: number) => (x === 0 ? "dim" : x > 0 ? "good" : "bad");
  return (
    <div className="sv-week">
      <div className="sv-week-head">
        <div className="mu-side">
          <span className="k">
            Week {w.week} · {dayLabel(w.start)} – {dayLabel(w.end)}
            {w.playoffs && " · playoffs"}
          </span>
          <span className="sv-vs">
            vs <span className="them">{against}</span>
          </span>
          {w.opponent != null && <span className="muted">{recordOf(w.opponent)}</span>}
        </div>
        <div className="mu-mid">
          <span className="sv-big">{w.win != null ? oddsLabel(w.win) : "—"}</span>
          <span className="k">to win the week</span>
        </div>
        <div className="mu-side r">
          {w.score && <span className="mu-big">{matchupRecord(w, s.scoring)}</span>}
          <span className="muted">{w.this_week ? daysLeftLabel(w.days) : `${w.days} days from ${dayLabel(w.from)}`}</span>
          <span className="muted">
            {w.games} games, {w.started} started
            {!points && w.expected != null && ` · ${w.expected.toFixed(1)} of ${w.cats.length} categories expected`}
          </span>
        </div>
      </div>
      {!w.rosters_read && <p className="banner">No roster faced was read, so the week has no odds. {s.public ? "Refresh reads every team's page." : "Open the team pages in Chrome with the extension."}</p>}
      {!w.scheduled && <p className="banner">The NBA schedule does not cover every day of this week yet: its games count only the days read.</p>}
      {w.opponent == null && (
        <p className="muted note">
          {w.playoffs
            ? "Playoff pairs are not known: the week is played against the field, the average over every other team."
            : s.public
              ? "This week's pairs were not read: the next refresh reads them."
              : "This week's pairs were not read: the Monday recorder lists the page to open in Chrome."}
        </p>
      )}
      {w.rosters_read &&
        w.cats.map((c) => (
          <div className="mu-row small" key={c.cat}>
            <div className="mu-vals">
              <span className="me">{catValue(c.cat, c.mine)}</span>
            </div>
            <div className="mu-cell" title={`${CAT_LABEL[c.cat]}: ${c.p_win != null ? oddsLabel(c.p_win) : "—"} to win`}>
              <div className="mu-bar">
                <div className="l">
                  <i style={{ width: `${(c.p_win ?? 0.5) * 100}%` }} />
                </div>
                <div className="r">
                  <i style={{ width: `${(1 - (c.p_win ?? 0.5)) * 100}%` }} />
                </div>
              </div>
              <span className="mu-cat">{CAT_LABEL[c.cat]}</span>
              <span className={`mu-pill ${c.p_win != null ? leanTone(c.p_win) : ""}`}>{c.p_win != null ? oddsLabel(c.p_win) : "—"}</span>
            </div>
            <div className="mu-vals r">
              <span className="them">{catValue(c.cat, c.theirs)}</span>
            </div>
          </div>
        ))}
      <div className="mu-players">
        <div className="k">
          My players, week {w.week} <span className="muted note">what each adds to the {w.win != null ? oddsLabel(w.win) : "week"}: out from {dayLabel(w.from)}, his starts refilled from the bench</span>
        </div>
        <table className="season-table">
          <thead>
            <tr>
              <th>Player</th>
              <th>Slot</th>
              <th className="num" title={`games from ${dayLabel(w.from)}`}>
                G
              </th>
              {!points && (
                <th className="num" title="expected categories he adds: the week with him less the week without him">
                  Cats
                </th>
              )}
              <th className="num" title="the odds of winning the week he adds, the same way">
                Matchup
              </th>
            </tr>
          </thead>
          <tbody>
            {w.players.map((r) => {
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
                  {!points && <td className={`num ${tone(r.cats)}`}>{gainLabel(r.cats)}</td>}
                  <td className={`num ${tone(r.matchup)}`}>{oddsGainLabel(r.matchup)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted note">{o.system.label}; today's rosters, nobody added or dropped.</p>
    </div>
  );
}
