import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type SeasonSummary } from "../api";
import { ageLabel, isRefreshing, isStale, recordLabel, refreshNote, weekLabel } from "../season";
import { useNow } from "./YahooSync";

/** The landing page's leagues in season (#92): one row per league folder with its name, the
 * week, my record, this week's opponent and how old its snapshot is, a Refresh that reads the
 * league's public pages again, and a button into its season view. A private league has no
 * public pages: the extension posts them from the user's Chrome (#98). */
export default function Seasons({ onOpen }: { onOpen: (league: string) => void }) {
  const queryClient = useQueryClient();
  const seasons = useQuery({
    queryKey: ["seasons"],
    queryFn: api.seasons,
    // Every second while a refresh runs, so its step shows; else once a minute for the ages.
    refetchInterval: (q) => (q.state.data?.some(isRefreshing) ? 1000 : 60_000),
  });
  const refresh = useMutation({
    mutationFn: (league: string) => api.refreshSeason(league),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["seasons"] }),
  });
  const now = useNow(30_000);
  if (!seasons.data?.length && !seasons.error) return null;
  // The leagues read at least once first, by name, so a refresh never moves a row.
  const title = (s: SeasonSummary) => s.name ?? s.league;
  const rows = [...(seasons.data ?? [])].sort((a, b) => Number(b.has_snapshot) - Number(a.has_snapshot) || title(a).localeCompare(title(b)));
  return (
    <section className="panel seasons" aria-label="Leagues">
      <div className="row">
        <h2>LEAGUES</h2>
        <span className="muted" style={{ fontSize: 11 }}>
          rosters, standings and the waiver pool from each league's Yahoo pages
        </span>
      </div>
      {seasons.error && <p className="error">{seasons.error.message}</p>}
      {rows.map((s) => (
        <SeasonRow key={s.league} s={s} now={now} onOpen={onOpen} onRefresh={() => refresh.mutate(s.league)} busy={refresh.isPending && refresh.variables === s.league} />
      ))}
      {refresh.isError && <p className="error">{refresh.error.message}</p>}
    </section>
  );
}

function SeasonRow({ s, now, onOpen, onRefresh, busy }: { s: SeasonSummary; now: number; onOpen: (league: string) => void; onRefresh: () => void; busy: boolean }) {
  const format = s.scoring === "points" ? "H2H points" : "H2H categories";
  if (s.error) {
    return (
      <div className="season-row">
        <div className="row">
          <strong>League {s.league}</strong>
          <span className="grow" />
        </div>
        <div className="facts bad">{s.error}</div>
      </div>
    );
  }
  const running = isRefreshing(s);
  const note = refreshNote(s.refresh);
  return (
    <div className="season-row">
      <div className="row">
        <strong>{s.name ?? `League ${s.league}`}</strong>
        <span className="dim">
          {s.name && !s.name.includes(s.league) ? `${s.league} · ` : ""}
          {format}
          {s.public ? "" : " · private"}
        </span>
        <span className="grow" />
        <span className="actions">
          {s.public && (
            <button className="small" disabled={running || busy} onClick={onRefresh} title="Read the league's public Yahoo pages again (about 20 s)">
              {running ? "Refreshing…" : "Refresh"}
            </button>
          )}
          <button className={`small${s.has_snapshot ? " primary" : ""}`} disabled={!s.has_snapshot} onClick={() => onOpen(s.league)} title={s.has_snapshot ? "Open the league's roster and waiver pool" : "Nothing read for this league yet"}>
            Open
          </button>
        </span>
      </div>
      <div className="facts">
        {s.has_snapshot && (
          <>
            <span>{weekLabel(s)}</span>
            {s.my_team?.record != null && <span title={`${s.my_team.name}, my team`}>{recordLabel(s.my_team)}</span>}
            {s.opponent && <span>vs {s.opponent.name}</span>}
          </>
        )}
        <span className={running ? "accent" : s.refresh?.status === "failed" ? "bad" : isStale(s.updated_at, now) ? "dim" : "muted"} title={s.updated_at ?? undefined}>
          {note || (s.has_snapshot ? `read ${ageLabel(s.updated_at, now)}` : s.public ? "not read yet" : "not read yet: open its pages in Chrome with the extension")}
        </span>
      </div>
    </div>
  );
}
