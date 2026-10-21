import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AvailableRow, type RosterRow, type SeasonMatchup, type SeasonPlayer, type SeasonView } from "../api";
import {
  ageLabel,
  availabilityLabel,
  changeLabel,
  DEFAULT_AVAILABLE_SORT,
  filterAvailable,
  isRefreshing,
  isStale,
  NO_FILTER,
  pctLabel,
  POSITIONS,
  recordLabel,
  refreshNote,
  sortAvailable,
  statusTitle,
  statusTone,
  TEXT_KEYS,
  weekDates,
  weekLabel,
  type AvailableFilter,
  type AvailableSort,
  type AvailableSortKey,
  type PositionFilter,
} from "../season";
import { DRAWER_WIDTH } from "../draft";
import { useNow } from "./YahooSync";

/** A league in season (#92), in the draft view's shape: the available players where the board
 * stands, my roster and the league's week in the drawer. Phase 1 shows Yahoo's own columns;
 * the weekly projections and the waiver ranking add theirs (#93 onward). */
export default function SeasonScreen({ league, onBack }: { league: string; onBack: () => void }) {
  const queryClient = useQueryClient();
  const season = useQuery({
    queryKey: ["season", league],
    queryFn: () => api.season(league),
    refetchInterval: (q) => (isRefreshing(q.state.data) ? 1000 : 60_000),
  });
  const refresh = useMutation({
    mutationFn: () => api.refreshSeason(league),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["season", league] });
      void queryClient.invalidateQueries({ queryKey: ["seasons"] });
    },
  });
  const now = useNow(30_000);
  const s = season.data;
  const running = isRefreshing(s) || refresh.isPending;
  return (
    <main className="shell">
      <header className="topbar season-top">
        <div className="wordmark">
          PICK<span>&amp;</span>ROLL
        </div>
        <span className="muted title">
          {s?.name ?? `League ${league}`}
          {s?.name && !s.name.includes(league) ? ` · ${league}` : ""}
          {s && ` · ${s.scoring === "points" ? "H2H points" : "H2H categories"} · ${s.num_teams} teams`}
        </span>
        <span className="grow" />
        {s?.has_snapshot && (
          <>
            <span className="k" title={s.calendar_estimated ? "the week's dates are estimated: Yahoo's calendar was not read" : undefined}>
              {weekLabel(s)}
              {s.current_week && ` · ${weekDates(s.current_week)}`}
            </span>
            {s.my_team && <span className="pill" title={`${s.my_team.name}, my team`}>{recordLabel(s.my_team)}</span>}
            {s.opponent && <span>vs {s.opponent.name}</span>}
          </>
        )}
        {s && (
          <span className={running ? "accent" : isStale(s.updated_at, now) ? "bad" : "muted"} title={s.updated_at ?? undefined}>
            {refreshNote(s.refresh) || (s.has_snapshot ? `read ${ageLabel(s.updated_at, now)}` : "not read yet")}
          </span>
        )}
        {s?.public && (
          <button className="small" disabled={running} onClick={() => refresh.mutate()} title="Read the league's public Yahoo pages again (about 20 s)">
            {running ? "Refreshing…" : "Refresh"}
          </button>
        )}
        <button className="link" onClick={onBack}>
          all leagues
        </button>
      </header>
      {season.error && <p className="error" style={{ padding: "0 24px" }}>{season.error.message}</p>}
      {refresh.isError && <p className="error" style={{ padding: "0 24px" }}>{refresh.error.message}</p>}
      {s && !s.has_snapshot && (
        <p className="muted" style={{ padding: "12px 24px" }}>
          Nothing read for this league yet.{" "}
          {s.public ? "Refresh reads its public Yahoo pages." : "It is private: open its team, players and matchup pages in Chrome with the extension."}
        </p>
      )}
      {s?.has_snapshot && (
        <>
          <div className="main season">
            <div className="board-col">
              <Available rows={s.available} />
            </div>
            <aside className="drawer" style={{ width: DRAWER_WIDTH }}>
              <Card title="MY ROSTER" note={s.my_team?.name} style={{ flex: "11 1 0%" }}>
                <Roster rows={s.roster} />
              </Card>
              <Card title="THE LEAGUE" note={s.current_week ? `week ${s.current_week.number}` : undefined} style={{ flex: "9 1 0%" }}>
                <League s={s} />
              </Card>
            </aside>
          </div>
          <SeasonFooter s={s} now={now} />
        </>
      )}
    </main>
  );
}

function Card({ title, note, style, children }: { title: string; note?: string; style: CSSProperties; children: ReactNode }) {
  return (
    <section className="card" style={style} aria-label={title}>
      <header>
        <h2>{title}</h2>
        {note && <span className="dim">{note}</span>}
      </header>
      <div className="body">{children}</div>
    </section>
  );
}

function Status({ player }: { player: SeasonPlayer }) {
  const tone = statusTone(player);
  if (!tone) return null;
  return (
    <span className={`tag ${tone}`} title={statusTitle(player)}>
      {player.status}
    </span>
  );
}

// ---------------------------------------------------------------- available
const COLUMNS: { key: AvailableSortKey; label: string; num?: boolean; title?: string }[] = [
  { key: "name", label: "Player" },
  { key: "nba_team", label: "Team" },
  { key: "positions", label: "Pos" },
  { key: "games_left", label: "GL", num: true, title: "games his NBA team plays in the rest of this week, from today (ESPN's schedule)" },
  { key: "availability", label: "Status", title: "a free agent, or on waivers until the day shown" },
  { key: "pct_rostered", label: "% Ros", num: true, title: "percent of Yahoo leagues that roster him" },
  { key: "pct_rostered_change", label: "+/−", num: true, title: "the day's change in percent rostered" },
  { key: "pct_started", label: "% Start", num: true, title: "percent of Yahoo leagues that start him" },
  { key: "adds", label: "Adds", num: true, title: "adds across Yahoo today" },
  { key: "drops", label: "Drops", num: true, title: "drops across Yahoo today" },
];

function Available({ rows }: { rows: AvailableRow[] }) {
  const [filter, setFilter] = useState<AvailableFilter>(NO_FILTER);
  const [sort, setSort] = useState<AvailableSort>(DEFAULT_AVAILABLE_SORT);
  const shown = useMemo(() => sortAvailable(filterAvailable(rows, filter), sort), [rows, filter, sort]);
  const set = (patch: Partial<AvailableFilter>) => setFilter((f) => ({ ...f, ...patch }));
  const click = (key: AvailableSortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: TEXT_KEYS.includes(key) ? "asc" : "desc" }));
  return (
    <section className="board season-board" aria-label="Available players">
      <header className="board-head">
        <h2>AVAILABLE</h2>
        <input type="search" placeholder="Player or team" value={filter.search} onChange={(e) => set({ search: e.target.value })} aria-label="Search players" />
        <select value={filter.position} onChange={(e) => set({ position: e.target.value as PositionFilter })} aria-label="Position">
          <option value="">all positions</option>
          {POSITIONS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select value={filter.availability} onChange={(e) => set({ availability: e.target.value as AvailableFilter["availability"] })} aria-label="Free agents or waivers">
          <option value="">free agents and waivers</option>
          <option value="FA">free agents</option>
          <option value="W">waivers</option>
        </select>
        <label className="inline muted" title="Hide players Yahoo lists as out (O, INJ, SUSP, NA, OFS)">
          <input type="checkbox" checked={filter.healthy} onChange={(e) => set({ healthy: e.target.checked })} /> hide out
        </label>
        <span className="grow" />
        <span className="muted">
          {shown.length === rows.length ? `the ${rows.length} most rostered available players` : `${shown.length} of the ${rows.length} most rostered available players`}
        </span>
      </header>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.key} className={`sortable${c.num ? " num" : ""}${sort.key === c.key ? " sorted" : ""}`} title={c.title} onClick={() => click(c.key)}>
                  {c.label}
                  {sort.key === c.key && <span className="arrow">{sort.dir === "asc" ? "▲" : "▼"}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.player.yahoo_id}>
                <td className="strong">
                  {r.player.name} <Status player={r.player} />
                </td>
                <td>{r.player.nba_team}</td>
                <td>{r.player.positions.join(", ")}</td>
                <td className="num">{r.games_left ?? ""}</td>
                <td className={r.availability === "W" ? "accent" : undefined}>{availabilityLabel(r)}</td>
                <td className="num">{pctLabel(r.pct_rostered)}</td>
                <td className={`num ${(r.pct_rostered_change ?? 0) > 0 ? "good" : (r.pct_rostered_change ?? 0) < 0 ? "bad" : ""}`}>{changeLabel(r.pct_rostered_change)}</td>
                <td className="num">{pctLabel(r.pct_started)}</td>
                <td className="num">{r.adds ?? ""}</td>
                <td className="num">{r.drops ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- drawer
function Roster({ rows }: { rows: RosterRow[] }) {
  if (!rows.length) return <p className="muted">No roster read for my team.</p>;
  return (
    <table className="season-table">
      <thead>
        <tr>
          <th>Slot</th>
          <th>Player</th>
          <th>Team</th>
          <th>Pos</th>
          <th className="num" title="games left this week, from today">
            GL
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.slot}-${r.player.yahoo_id}-${i}`} className={r.slot === "BN" || r.slot.startsWith("IL") ? "bench" : undefined}>
            <td className="dim">{r.slot}</td>
            <td className="strong">
              {r.player.name} <Status player={r.player} />
            </td>
            <td>{r.player.nba_team}</td>
            <td>{r.player.positions.join(", ")}</td>
            <td className="num">{r.games_left ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** My matchup's columns, mine first. */
function ordered(m: SeasonMatchup, mine: number | undefined): [number, number] {
  return m.teams[1] === mine ? [m.teams[1], m.teams[0]] : m.teams;
}

function League({ s }: { s: SeasonView }) {
  const mine = s.my_team?.team_id;
  const name = (id: number) => s.teams.find((t) => t.team_id === id)?.name ?? `Team ${id}`;
  const m = s.matchup;
  const points = s.scoring === "points";
  return (
    <>
      {m && <Matchup m={m} mine={mine} name={name} />}
      <div className="block">
        <span className="k">Standings</span>
        <table className="season-table">
          <thead>
            <tr>
              <th className="num">#</th>
              <th>Team</th>
              <th>W-L-T</th>
              {points && <th className="num">PF</th>}
              <th className="num" title="waiver priority">
                Wvr
              </th>
              {s.settings.uses_faab && (
                <th className="num" title="FAAB left">
                  $
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {s.teams.map((t) => (
              <tr key={t.team_id} className={t.team_id === mine ? "mine" : undefined}>
                <td className="num dim">{t.rank ?? ""}</td>
                <td>{t.name}</td>
                <td>{t.record ?? ""}</td>
                {points && <td className="num">{t.points_for ?? ""}</td>}
                <td className="num">{t.waiver_priority ?? ""}</td>
                {s.settings.uses_faab && <td className="num">{t.faab ?? ""}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {s.transactions.length > 0 && (
        <div className="block">
          <span className="k">Recent moves</span>
          <table className="season-table">
            <tbody>
              {s.transactions.slice(0, 12).map((t, i) => (
                <tr key={i} className={t.team_id === mine ? "mine" : undefined}>
                  <td className={t.kind === "add" ? "good" : t.kind === "drop" ? "bad" : "accent"}>{t.kind}</td>
                  <td>{t.player.name}</td>
                  <td className="dim">{t.team_name ?? ""}</td>
                  <td className="dim">{t.when ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

function Matchup({ m, mine, name }: { m: SeasonMatchup; mine: number | undefined; name: (id: number) => string }) {
  const [a, b] = ordered(m, mine);
  const flip = a !== m.teams[0];
  const pair = (v: [number, number]) => (flip ? [v[1], v[0]] : v);
  const totalsA = m.totals[String(a)] ?? {};
  const totalsB = m.totals[String(b)] ?? {};
  const cats = Object.keys(totalsA);
  // A categories matchup has only the score, which the heading carries; a points one adds
  // Yahoo's projections.
  const lines = Object.entries(m.lines).filter(([label]) => label !== "vs" || Object.keys(m.lines).length > 1);
  return (
    <div className="block">
      <span className="k">
        Week {m.week}: {name(a)} vs {name(b)}
        {m.score && ` · ${pair(m.score).join("–")}`}
      </span>
      {lines.length > 0 && (
        <table className="season-table">
          <tbody>
            {lines.map(([label, v]) => (
              <tr key={label}>
                <td className="dim">{label === "vs" ? "score" : label}</td>
                <td className="num">{pair(v)[0]}</td>
                <td className="num">{pair(v)[1]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {cats.length > 0 && (
        <table className="season-table">
          <thead>
            <tr>
              <th></th>
              {cats.map((c) => (
                <th key={c} className="num">
                  {c.replace(/\*$/, "")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="mine">
              <td>me</td>
              {cats.map((c) => (
                <td key={c} className="num">
                  {totalsA[c]}
                </td>
              ))}
            </tr>
            <tr>
              <td>them</td>
              {cats.map((c) => (
                <td key={c} className="num">
                  {totalsB[c] ?? ""}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

function SeasonFooter({ s, now }: { s: SeasonView; now: number }) {
  const set = s.settings;
  const waivers = [
    set.waiver_rule ? `${set.waiver_rule} waivers` : null,
    set.uses_faab ? "FAAB" : null,
    set.max_weekly_adds != null ? `${set.max_weekly_adds} adds a week` : null,
  ].filter(Boolean);
  return (
    <footer className="footer season-foot">
      <span>From {s.sources.length ? s.sources.map((x) => (x === "public" ? "Yahoo's public pages" : "the extension")).join(" and ") : "nothing yet"}</span>
      <span title={s.calendar_estimated ? "no week dates read from Yahoo: Monday-to-Sunday weeks assumed" : "the week dates read from the league's team page"}>
        {s.calendar_estimated == null ? "no calendar" : `${s.end_week ?? "?"} weeks${s.calendar_estimated ? " (estimated)" : ""}`}
      </span>
      <span title="the NBA schedule behind the games-left counts (ESPN)">{s.schedule.last ? `schedule to ${s.schedule.last}` : "no schedule"}</span>
      {waivers.length > 0 && <span>{waivers.join(" · ")}</span>}
      <span className="grow" />
      <span title={Object.entries(s.fetched).map(([k, f]) => `${k}: ${f.at} (${f.source})`).join("\n")}>Snapshot {ageLabel(s.updated_at, now)}</span>
      <span>League {s.league}</span>
    </footer>
  );
}
