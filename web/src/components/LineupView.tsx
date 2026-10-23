import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type LineupDay, type LineupPayload, type ProjectionSystem, type SeasonView } from "../api";
import { shortName } from "../format";
import { benchPlaying, dayLabel, heldEligibleText, lineupAlertText, lineupGrid, lineupSummary, playersById, ruleText, weekdayLabel, type LineupCell } from "../season";

/** The Lineup view (#107): a week's recommended lineup against Yahoo's as read, days across and
 * the starting slots down. A starter Yahoo's lineup has on the bench is lit, Yahoo's starters to
 * sit and the bench players who play are listed under the slots, and the foot counts the games
 * each lineup starts and those Yahoo's loses. Then the held slots: who sits in each (a cleared
 * occupant flagged: he blocks every add) and who could go there. Nothing here sets a lineup. */
export default function LineupView({
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
  // Null: this week, until a week is picked.
  const [week, setWeek] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["lineup", league, system, week, s.updated_at],
    queryFn: () => api.lineup(league, system, week ?? undefined),
    enabled: Boolean(s.my_team),
    // A new snapshot keeps the last grid up while its own is made; another system's or week's
    // never stands in for this one's.
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[2] === system && prevQuery?.queryKey[3] === week ? prev : undefined),
    refetchInterval: 60_000,
    retry: false,
  });
  const byId = useMemo(() => playersById(s), [s]);
  if (!s.my_team) return <p className="muted">No team of mine in this league: the Lineup view needs my team id in its settings.</p>;
  if (q.error) return <p className="error">{q.error.message}</p>;
  const p = q.data;
  if (!p) return <p className="muted">Setting the lineups…</p>;
  const name = (id: number) => p.players[String(id)]?.name ?? byId.get(id)?.name ?? `player ${id}`;
  const weeks = p.weeks ?? [p.week];
  const w = s.week_projection;
  return (
    <div className="lineup-view">
      <div className="sv-head">
        <div className="sv-title">
          <span className="k">Lineup · week {p.week}</span>
          <span className="muted">
            {dayLabel(p.start)} – {dayLabel(p.end)}
          </span>
        </div>
        {weeks.length > 1 && (
          <div className="seg small" role="tablist" aria-label="Week">
            {weeks.map((n, i) => (
              <button key={n} role="tab" aria-selected={n === p.week} className={n === p.week ? "on" : undefined} onClick={() => setWeek(i === 0 ? null : n)}>
                {i === 0 ? "this week" : `week ${n}`}
              </button>
            ))}
          </div>
        )}
        <span className="grow" />
        <select value={system} onChange={(e) => setSystem(e.target.value as ProjectionSystem)} aria-label="Projection" title={p.system.fallback ?? p.system.label}>
          {(["bbm", "yahoo"] as const).map((x) => (
            <option key={x} value={x}>
              {w.systems[x].label}
              {w.systems[x].players ? "" : " (none read)"}
            </option>
          ))}
        </select>
      </div>
      <p className="muted lv-note">
        {ruleText(p.rule)} · {lineupSummary(p)}
      </p>
      {p.alerts.map((a, i) => (
        <p key={i} className={`lv-note ${a.kind === "cleared" ? "bad" : "accent"}`}>
          {lineupAlertText(a, name)}
        </p>
      ))}
      {p.needs.length > 0 && (
        <p className="muted lv-note">
          For the extension to read them, open in Chrome:{" "}
          {p.needs.map((url, i) => (
            <span key={url}>
              {i > 0 && ", "}
              <a href={url} target="_blank" rel="noreferrer">
                {needLabel(url)}
              </a>
            </span>
          ))}
        </p>
      )}
      <Grid p={p} name={name} />
      <Held p={p} name={name} />
      <p className="dim lv-note">
        Recommended: each day, the most games my players who play can start in the league&apos;s slots, the better player first where they compete. Two lineups
        that start the same players in other slots are the same. Nothing here changes a lineup in Yahoo.
      </p>
    </div>
  );
}

/** The days across, the starting slots down. */
function Grid({ p, name }: { p: LineupPayload; name: (id: number) => string }) {
  const grid = lineupGrid(p);
  const info = (k: number) => {
    const x = p.players[String(k)];
    return x ? `${x.name} · ${x.nba_team ?? "no team"} · ${x.positions.join(", ")}${x.status ? ` · ${x.status}` : ""}` : name(k);
  };
  const cell = (c: LineupCell, j: number) => {
    if (c.player == null) return <td key={j} className="dim" title={c.source === "recommended" ? "nobody who plays that day fits this slot" : undefined}>{c.source ? "—" : ""}</td>;
    const title = `${info(c.player)}${c.start ? "\nYahoo's lineup has him on the bench: start him" : c.source === "yahoo" ? "\nYahoo's lineup as read" : ""}`;
    return (
      <td key={j} className={c.start ? "lv-start" : c.source === "yahoo" ? "dim" : undefined} title={title}>
        {shortName(name(c.player))}
      </td>
    );
  };
  return (
    <div className="lv-table">
      <table className="season-table lv-grid">
        <thead>
          <tr>
            <th>Slot</th>
            {p.days.map((d) => (
              <th key={d.date} className={d.past ? "dim" : d.date === p.first ? "first" : undefined} title={dayTitle(d, p.first)}>
                {weekdayLabel(d.date)}
                {!d.yahoo && <span className="dim"> ·</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.map((r, i) => (
            <tr key={i}>
              <td className="dim">{r.slot}</td>
              {r.cells.map(cell)}
            </tr>
          ))}
          <tr className="lv-sub">
            <td className="dim" title="Yahoo's starters to take out of the starting slots: no game, or a better player in his slot">
              Sit
            </td>
            {p.days.map((d) => (
              <td key={d.date} className="bad" title={d.sit.map(info).join("\n") || undefined}>
                {d.sit.map((k) => shortName(name(k))).join(", ")}
              </td>
            ))}
          </tr>
          <tr className="lv-sub">
            <td className="dim" title="bench players who play that day: the slots are full of players worth more, or none fits them">
              Bench
            </td>
            {p.days.map((d) => (
              <td key={d.date} className="dim" title={benchPlaying(d).map(info).join("\n") || undefined}>
                {benchPlaying(d)
                  .map((k) => shortName(name(k)))
                  .join(", ")}
              </td>
            ))}
          </tr>
        </tbody>
        <tfoot>
          <tr>
            <td className="dim" title="the games the recommended lineup starts">
              Games
            </td>
            {p.days.map((d) => (
              <td key={d.date} className="num">
                {d.games.recommended ?? ""}
              </td>
            ))}
          </tr>
          <tr>
            <td className="dim" title="the games Yahoo's lineup as read starts">
              Yahoo
            </td>
            {p.days.map((d) => (
              <td key={d.date} className={`num ${d.past ? "" : "dim"}`}>
                {d.games.yahoo ?? (d.past ? "" : "·")}
              </td>
            ))}
          </tr>
          <tr>
            <td className="dim" title="the games Yahoo's lineup as read loses against the recommended one">
              Lost
            </td>
            {p.days.map((d) => (
              <td key={d.date} className={`num ${d.lost ? "bad" : "dim"}`}>
                {d.lost == null ? "" : d.lost ? `−${d.lost}` : "0"}
              </td>
            ))}
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/** The held slots one by one, and who could go to one. */
function Held({ p, name }: { p: LineupPayload; name: (id: number) => string }) {
  const h = p.held;
  const status = (k: number) => p.players[String(k)]?.status;
  return (
    <div className="lv-held-block">
      <span className="k" title={h.lower_bound ? "the most any roster read fills: the league's settings page is not read yet" : "from the league's settings page"}>
        Held slots{h.lower_bound ? " · at least" : ""}
      </span>
      {h.slots.length === 0 ? (
        <p className="dim lv-note">The league has no held slot.</p>
      ) : (
        <table className="season-table lv-held">
          <tbody>
            {h.slots.map((x, i) => (
              <tr key={i}>
                <td className="dim">{x.slot}</td>
                <td className={x.cleared ? "bad" : x.player == null ? "dim" : undefined}>
                  {x.player == null ? "open" : `${name(x.player)}${status(x.player) ? ` (${status(x.player)})` : ""}`}
                </td>
                <td className={x.cleared ? "bad" : "dim"}>{x.cleared ? "status cleared: no add until he is activated" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {h.eligible.length > 0 ? (
        h.eligible.map((e) => (
          <p key={e.player} className="muted lv-note">
            {name(e.player)}
            {status(e.player) ? ` (${status(e.player)})` : ""}: {heldEligibleText(e.slots, h.open)}
          </p>
        ))
      ) : (
        <p className="dim lv-note">No active player of mine is eligible for a held slot.</p>
      )}
    </div>
  );
}

function dayTitle(d: LineupDay, first: string): string {
  const read = d.yahoo ? `Yahoo's lineup read from the ${d.yahoo.page}${d.yahoo.stale ? ", before today" : ""}` : "Yahoo's lineup not read for this day (·)";
  const when = d.past ? ", before the first day a change counts" : d.date === first ? ", the first day a change counts" : "";
  return `${dayLabel(d.date)}${when}: ${read}`;
}

/** "settings page", "Oct 24": a page the private league's lineup needs. */
function needLabel(url: string): string {
  const day = /[?&]date=(\d{4}-\d{2}-\d{2})/.exec(url)?.[1];
  return day ? dayLabel(day) : url.includes("/settings") ? "settings page" : url;
}
