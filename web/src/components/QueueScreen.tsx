import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LineupMode, type ProjectionSystem, type QueueEntry, type QueueLeague, type QueuePayload, type SeasonSummary } from "../api";
import { queueKeys } from "../keys";
import {
  addsThisWeek,
  bestLine,
  bestNamer,
  bidLabel,
  centralClock,
  dayLabel,
  gainLabel,
  notQueued,
  queueFlagWord,
  queueFloorLine,
  queueFoldLine,
  queueMoveText,
  queueNamer,
  queueOrder,
  queueStateText,
  roomNote,
  rosLabel,
  rosTone,
  setLine,
  setSummary,
  stripOrder,
  stripReason,
} from "../season";
import { useHotkeys } from "../useKeys";
import ExecuteTime from "./ExecuteTime";
import { Veto, type Strike } from "./QueueCard";
import { useNow } from "./YahooSync";

const SYSTEM: ProjectionSystem = "bbm";
const MODE_WORD: Record<LineupMode, string> = { off: "off", dry_run: "dry run", live: "live" };
const GAIN_TITLE = "the gain over the three weeks, on the judging horizon: expected categories, or points in a points league";
const SEASON_TITLE = "the move to the season's end in the scorer's units (fantasy points in a points league, the z-sum in a categories league), as the decision log values it; nothing ranks on it";

/** The Queue screen (#194) at /queue: every league's proposed moves today in one view. It reads
 * only: nothing on it solves, builds or executes. Its writes are the user's own, as on the Queue
 * card and the landing: the veto on an entry and the day's execute time. The private league's
 * recommended set is listed as suggestions to make by hand, from its best route. */
export default function QueueScreen({ onBack, onOpenLeague }: { onBack: () => void; onOpenLeague: (league: string) => void }) {
  const queryClient = useQueryClient();
  const q = useQuery({ queryKey: ["queue"], queryFn: () => api.queue(), refetchInterval: 60_000 });
  const seasons = useQuery({ queryKey: ["seasons"], queryFn: api.seasons, refetchInterval: 60_000 });
  const now = useNow(30_000);
  const strike = useMutation({
    mutationFn: ({ id, bid_only, undo }: { id: string; bid_only: boolean; undo: boolean }) => api.strike(id, { bid_only, undo }),
    onSuccess: (v) => {
      queryClient.setQueryData(["queue"], v);
      void queryClient.invalidateQueries({ queryKey: ["movesView"] });
    },
  });
  useHotkeys(queueKeys(onBack));
  const title = useMemo(() => {
    const names = new Map((seasons.data ?? []).map((s) => [s.league, s.name]));
    return (league: string) => names.get(league) ?? `league ${league}`;
  }, [seasons.data]);
  const priv = seasons.data?.find((s) => s.public === false);
  const p = q.data;
  return (
    <main className="shell">
      <header className="topbar season-top">
        <div className="wordmark">
          PICK<span>&amp;</span>ROLL
        </div>
        <span className="muted title">Queue · {p ? dayLabel(p.date) : "today"}</span>
        <span className="grow" />
        <ExecuteTime q={p} />
        <button className="link" onClick={onBack} title="back (Esc)">
          all leagues
        </button>
      </header>
      {q.error && <p className="error" style={{ padding: "0 24px" }}>{q.error.message}</p>}
      {!p && !q.error && (
        <p className="muted" style={{ padding: 24 }}>
          Reading the queue…
        </p>
      )}
      {p && (
        <div className="landing-grid qs">
          <div className="qs-head">
            <p className={p.stop ? "bad" : "muted"}>{queueFoldLine(p)}</p>
            <p className="dim small">
              {p.built.length ? `Built ${p.built.map(centralClock).join(", ")}` : "Not built today: the morning routine builds it from the day's solve"}. Nothing here solves, builds or
              executes; strike a move to veto it.
            </p>
          </div>
          {p.leagues.length > 0 && (
            <div className="qs-strip" aria-label="leagues">
              {stripOrder(p.leagues, title).map((row) => (
                <Chip key={row.league} row={row} p={p} title={title(row.league)} onOpen={() => onOpenLeague(row.league)} />
              ))}
            </div>
          )}
          <Today p={p} now={now} title={title} strike={strike} onOpenLeague={onOpenLeague} />
          <Left p={p} now={now} title={title} onOpenLeague={onOpenLeague} />
          {priv && <Suggestions s={priv} title={title(priv.league)} onOpen={() => onOpenLeague(priv.league)} />}
        </div>
      )}
    </main>
  );
}

/** A league's chip: its mode, its cap and where the cap is from, the adds left this week, what
 * it queued, and why it queued none. */
function Chip({ row, p, title, onOpen }: { row: QueueLeague; p: QueuePayload; title: string; onOpen: () => void }) {
  const mine = p.entries.filter((e) => e.league === row.league && e.queued);
  const struck = mine.filter((e) => e.struck).length;
  const adds = addsThisWeek(row, p.date);
  const why = stripReason(row, p.entries);
  const facts = [
    row.status === "private" ? "suggestions only" : MODE_WORD[row.mode],
    row.scoring === "points" ? "points" : null,
    row.cap != null ? `cap ${row.cap} (${row.cap_from === "the user" ? "yours" : "the knob's"})` : null,
    adds != null ? `${adds} add${adds === 1 ? "" : "s"} left this week` : null,
    row.status === "queued" ? `${mine.length - struck} queued${struck ? ` · ${struck} struck` : ""}` : null,
  ].filter(Boolean);
  return (
    <div className={`qs-chip ${row.status === "private" ? "private" : ""}`}>
      <button className="link" onClick={onOpen} title="open the league">
        {title}
      </button>
      <span className="qs-facts">
        {facts.map((f) => (
          <span key={f}>{f}</span>
        ))}
      </span>
      {why && <span className="dim">{why}</span>}
    </div>
  );
}

function LeagueCell({ league, title, onOpen }: { league: string; title: string; onOpen: (league: string) => void }) {
  return (
    <td>
      <button className="link" onClick={() => onOpen(league)} title="open the league">
        {title}
      </button>
    </td>
  );
}

/** The day's queued entries of every league together, in the order they execute. */
function Today({ p, now, title, strike, onOpenLeague }: { p: QueuePayload; now: number; title: (league: string) => string; strike: Strike; onOpenLeague: (league: string) => void }) {
  const rows = queueOrder(p.entries);
  const name = queueNamer(p);
  return (
    <section className="qs-section">
      <span className="k">Today's queue</span>
      {rows.length === 0 ? (
        <p className="dim small">{p.built.length ? "Nothing queued today." : "No queue built today."}</p>
      ) : (
        <div className="qs-scroll">
          <table className="qs-table">
            <thead>
              <tr>
                <th>League</th>
                <th>Move</th>
                <th className="num" title={GAIN_TITLE}>
                  Gain
                </th>
                <th className="num" title={SEASON_TITLE}>
                  Season
                </th>
                <th>Flag</th>
                <th>Bid</th>
                <th title="the time it executes, on the Central clock">Executes</th>
                <th>State</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className={e.struck ? "struck" : e.outcome ? "done" : undefined}>
                  <LeagueCell league={e.league} title={title(e.league)} onOpen={onOpenLeague} />
                  <td>{queueMoveText(e, name)}</td>
                  <td className="num good">{gainLabel(e.gain)}</td>
                  <td className={`num ${rosTone({ value: e.season }, e.scoring)}`}>{rosLabel({ value: e.season }, e.scoring)}</td>
                  <td>{queueFlagWord(e.flag)}</td>
                  <td title={e.bid.reason}>{bidLabel(e)}</td>
                  <td>{centralClock(e.executes_at)}</td>
                  <td className={e.struck ? "dim" : "muted"}>{queueStateText(e, now)}</td>
                  <td className="acts">
                    <Veto e={e} strike={strike} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {strike.error && <p className="error small">{strike.error.message}</p>}
    </section>
  );
}

/** The entries the build left out, folded: each with its gain and why. */
function Left({ p, now, title, onOpenLeague }: { p: QueuePayload; now: number; title: (league: string) => string; onOpenLeague: (league: string) => void }) {
  const rows = notQueued(p.entries);
  if (!rows.length) return null;
  const name = queueNamer(p);
  const byLeague = new Map(p.leagues.map((r) => [r.league, r]));
  return (
    <details className="qs-section">
      <summary className="k">Not queued ({rows.length})</summary>
      <div className="qs-scroll">
        <table className="qs-table">
          <thead>
            <tr>
              <th>League</th>
              <th>Move</th>
              <th className="num" title={GAIN_TITLE}>
                Gain
              </th>
              <th className="num" title={SEASON_TITLE}>
                Season
              </th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e: QueueEntry) => {
              const row = byLeague.get(e.league);
              return (
                <tr key={e.id}>
                  <LeagueCell league={e.league} title={title(e.league)} onOpen={onOpenLeague} />
                  <td>{queueMoveText(e, name)}</td>
                  <td className="num">{gainLabel(e.gain)}</td>
                  <td className={`num ${rosTone({ value: e.season }, e.scoring)}`}>{rosLabel({ value: e.season }, e.scoring)}</td>
                  <td className="muted" title={e.floor.below && row ? queueFloorLine(row) : undefined}>
                    {queueStateText(e, now)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** The private league's recommended set from its best route, as suggestions to make by hand: the
 * screen never solves it ("not solved yet" until the league page does). */
function Suggestions({ s, title, onOpen }: { s: SeasonSummary; title: string; onOpen: () => void }) {
  const look = useQuery({
    queryKey: ["best", s.league, SYSTEM, s.updated_at],
    queryFn: () => api.best(s.league, SYSTEM),
    refetchInterval: 60_000,
    enabled: s.has_snapshot && !s.error && !!s.my_team,
  });
  const best = look.data;
  const name = best?.status === "solved" ? bestNamer(best) : null;
  return (
    <section className="qs-sugg">
      <div className="row">
        <span className="k">Suggestions only</span>
        <span className="grow" />
        <button className="link" onClick={onOpen} title="open the league">
          {title}
        </button>
      </div>
      <span className="muted">The private league is never queued: make these by hand.</span>
      {!s.has_snapshot || s.error || !s.my_team ? (
        <span className="dim">not read yet</span>
      ) : look.error ? (
        <span className="bad">{look.error.message}</span>
      ) : !best ? (
        <span className="dim">looking for a solved move…</span>
      ) : best.status !== "solved" || !name ? (
        <span className="dim">not solved yet</span>
      ) : (
        <>
          <span className="muted">{setSummary(best)}</span>
          {best.set ? (
            best.set.length > 0 && (
              <div className="lt-lines">
                {best.set.map((m) => {
                  const line = setLine(m, name);
                  return (
                    <div key={`${m.add}-${m.drop}`} className="lt-line">
                      <span>{line.text}</span>
                      <span className="good">{gainLabel(m.gain)}</span>
                      <span className="muted" title={line.basis.title}>
                        {line.kind}
                      </span>
                    </div>
                  );
                })}
              </div>
            )
          ) : (
            best.move && (
              <div className="lt-lines">
                <div className="lt-line">
                  <span>{bestLine(best)}</span>
                  <span className="good">{gainLabel(best.move.gain)}</span>
                  <span className="dim">the best of them</span>
                </div>
              </div>
            )
          )}
          {best.room && <span className="muted">Room: {roomNote(best.room, name)}</span>}
        </>
      )}
    </section>
  );
}
