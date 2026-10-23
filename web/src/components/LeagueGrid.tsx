import { useEffect, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type BestMove, type ProjectionSystem, type SeasonSummary, type StatusPayload } from "../api";
import {
  addsLeft,
  addsNote,
  ageLabel,
  bestLine,
  flagCounts,
  gainLabel,
  gridOrder,
  isRefreshing,
  isStale,
  placeLabel,
  refreshNote,
  scoreLabel,
  type GridOrder,
} from "../season";
import { StatusDot, StatusSheet, useSeasonStatus } from "./StatusLight";

/** The grid's moves come from the league page's default projection, so a solve there shows here. */
const SYSTEM: ProjectionSystem = "bbm";
const ORDER_KEY = "pickandroll.landing.order";

function savedOrder(): GridOrder {
  try {
    return localStorage.getItem(ORDER_KEY) === "name" ? "name" : "gain";
  } catch {
    return "gain";
  }
}

/** The leagues in season as a grid (#108, variant A): one card per league with this week's
 * score, the opponent, my place, the adds left, the flags, the best recommended move with its
 * gain and any read error. The best move is only ever read from the moves already solved today:
 * loading the grid solves nothing, a league without an answer says so, and its button solves it. */
export default function LeagueGrid({ onOpen }: { onOpen: (league: string) => void }) {
  const queryClient = useQueryClient();
  const seasons = useQuery({
    queryKey: ["seasons"],
    queryFn: api.seasons,
    // Every second while a refresh runs, so its step shows; else once a minute for the ages.
    refetchInterval: (q) => (q.state.data?.some(isRefreshing) ? 1000 : 60_000),
  });
  const [order, setOrderState] = useState<GridOrder>(savedOrder);
  const setOrder = (o: GridOrder) => {
    setOrderState(o);
    try {
      localStorage.setItem(ORDER_KEY, o);
    } catch {
      // The order is a convenience: it resets without storage.
    }
  };
  const list = seasons.data ?? [];
  const movable = list.filter((s) => s.has_snapshot && !s.error && s.my_team);
  // One look per league, each card filling in as its answer lands; a new snapshot looks again.
  const looks = useQueries({
    queries: movable.map((s) => ({
      queryKey: ["best", s.league, SYSTEM, s.updated_at],
      queryFn: () => api.best(s.league, SYSTEM),
      refetchInterval: 60_000,
    })),
  });
  const best = new Map<string, BestMove | undefined>(movable.map((s, i) => [s.league, looks[i].data]));
  const lookError = new Map(movable.map((s, i) => [s.league, looks[i].error]));
  const [solving, setSolving] = useState<Set<string>>(new Set());
  const solve = useMutation({
    mutationFn: (s: SeasonSummary) => api.solveBest(s.league, SYSTEM),
    onMutate: (s) => setSolving((x) => new Set(x).add(s.league)),
    onSuccess: (b, s) => queryClient.setQueryData(["best", s.league, SYSTEM, s.updated_at], b),
    onSettled: (_b, _e, s) =>
      setSolving((x) => {
        const next = new Set(x);
        next.delete(s.league);
        return next;
      }),
  });
  const refresh = useMutation({
    mutationFn: (league: string) => api.refreshSeason(league),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ["seasons"] }),
  });
  // Each card's freshness light (#153) and the league whose sheet is open; a new read moves it.
  const status = useSeasonStatus();
  const [sheetFor, setSheetFor] = useState<string | null>(null);
  const reads = list.map((s) => s.updated_at).join();
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ["status"] });
  }, [queryClient, reads]);
  const open = list.find((s) => s.league === sheetFor);
  const now = Date.now();
  if (!list.length && !seasons.error) return seasons.isPending ? <p className="muted">Reading the leagues…</p> : null;
  return (
    <section className="league-grid" aria-label="Leagues">
      <div className="lg-head">
        <h2>LEAGUES</h2>
        <span className="muted">this week's score, place and the best move in each · click a card for its league page</span>
        <span className="grow" />
        <label className="inline muted">
          sorted by
          <select value={order} onChange={(e) => setOrder(e.target.value as GridOrder)} aria-label="Sort the leagues">
            <option value="gain">most to gain</option>
            <option value="name">name</option>
          </select>
        </label>
      </div>
      {seasons.error && <p className="error">{seasons.error.message}</p>}
      <div className="grid">
        {gridOrder(list, best, order).map((s) => (
          <LeagueCard
            key={s.league}
            s={s}
            now={now}
            best={best.get(s.league)}
            lookError={lookError.get(s.league) ?? null}
            solving={solving.has(s.league)}
            solveError={solve.isError && solve.variables?.league === s.league ? solve.error.message : null}
            onOpen={() => onOpen(s.league)}
            onSolve={() => solve.mutate(s)}
            onRefresh={() => refresh.mutate(s.league)}
            refreshing={refresh.isPending && refresh.variables === s.league}
            status={status.data}
            onStatus={() => setSheetFor(s.league)}
          />
        ))}
      </div>
      {refresh.isError && <p className="error">{refresh.error.message}</p>}
      {open && status.data && (
        <StatusSheet
          p={status.data}
          league={open.league}
          onClose={() => setSheetFor(null)}
          refresh={
            open.public
              ? {
                  run: () => refresh.mutate(open.league),
                  running: isRefreshing(open) || (refresh.isPending && refresh.variables === open.league),
                  title: "Read the league's public Yahoo pages again (about 20 s)",
                }
              : undefined
          }
        />
      )}
    </section>
  );
}

function LeagueCard({
  s,
  now,
  best,
  lookError,
  solving,
  solveError,
  onOpen,
  onSolve,
  onRefresh,
  refreshing,
  status,
  onStatus,
}: {
  s: SeasonSummary;
  now: number;
  best: BestMove | undefined;
  lookError: Error | null;
  solving: boolean;
  solveError: string | null;
  onOpen: () => void;
  onSolve: () => void;
  onRefresh: () => void;
  refreshing: boolean;
  status: StatusPayload | undefined;
  onStatus: () => void;
}) {
  const format = s.scoring === "points" ? "H2H points" : "H2H categories";
  const title = s.name ?? `League ${s.league}`;
  if (s.error || !s.has_snapshot) {
    return (
      <div className="lcard unread">
        <div className="top">
          <span className="name">{title}</span>
          <span className="meta">
            {format}
            {s.public === false ? " · private" : ""}
          </span>
        </div>
        {s.error ? (
          <span className="bad">{s.error}</span>
        ) : (
          <span className="dim">{s.public ? "not read yet" : "not read yet: open its pages in Chrome with the extension"}</span>
        )}
        <div className="facts">
          <StatusDot p={status} league={s.league} onOpen={onStatus} />
          {s.public && !s.error && (
            <button className="link" disabled={isRefreshing(s) || refreshing} onClick={onRefresh}>
              {isRefreshing(s) ? refreshNote(s.refresh) : "read it now"}
            </button>
          )}
        </div>
      </div>
    );
  }
  const running = isRefreshing(s) || refreshing;
  const failed = s.refresh?.status === "failed";
  const readNote = refreshNote(s.refresh) || `read ${ageLabel(s.updated_at, now)}`;
  // A click anywhere on the card opens its league page; its own buttons do not.
  const stop = (f: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation();
    f();
  };
  return (
    <div
      className="lcard"
      role="link"
      tabIndex={0}
      aria-label={`${title}: open its league page`}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" && e.target === e.currentTarget) onOpen();
      }}
    >
      <div className="top">
        <span className="name">{title}</span>
        <span className={s.flags?.["must-add"] || s.flags?.add ? "accent" : "dim"} title={s.flags_error ?? "the waiver pool's breakout flags, by level"}>
          {s.flags_error ? "flags did not read" : flagCounts(s.flags)}
        </span>
      </div>
      <div className="score">
        <span className="big" title={s.scoring === "points" ? "this week's points so far, mine first" : "categories won so far this week, mine first"}>
          {scoreLabel(s)}
        </span>
        <span className="muted">
          {s.opponent ? `vs ${s.opponent.name}` : "no opponent read"}
          {s.week != null ? ` · week ${s.week}` : ""}
        </span>
      </div>
      <div className="facts">
        <span className="meta">
          {format}
          {s.public ? "" : " · private"}
        </span>
        {s.my_team && <span>{s.my_team.name}</span>}
        <span>{placeLabel(s)}</span>
        {s.adds && <span title={addsNote(s.adds)}>{addsLeft(s.adds)}</span>}
        <StatusDot p={status} league={s.league} onOpen={onStatus} />
        <span className={failed ? "bad" : running ? "accent" : isStale(s.updated_at, now) ? "dim" : "muted"} title={s.refresh?.error ?? s.updated_at ?? undefined}>
          {readNote}
        </span>
        {s.public && !running && (
          <button className="link" onClick={stop(onRefresh)} title="Read the league's public Yahoo pages again (about 20 s)">
            refresh
          </button>
        )}
      </div>
      <BestRow s={s} best={best} lookError={lookError} solving={solving} solveError={solveError} onSolve={stop(onSolve)} />
    </div>
  );
}

function BestRow({
  s,
  best,
  lookError,
  solving,
  solveError,
  onSolve,
}: {
  s: SeasonSummary;
  best: BestMove | undefined;
  lookError: Error | null;
  solving: boolean;
  solveError: string | null;
  onSolve: (e: React.MouseEvent) => void;
}) {
  if (!s.my_team) return null;
  const error = solveError ?? lookError?.message;
  if (solving) return <div className="move dim">solving the moves… (a few seconds)</div>;
  if (error) return <div className="move bad">{error}</div>;
  if (!best) return <div className="move dim">looking for a solved move…</div>;
  if (best.status === "not_solved") {
    return (
      <div className="move dim">
        <span>not solved yet</span>
        <span className="grow" />
        <button className="small" onClick={onSolve} title="Solve today's moves for this league (a few seconds)">
          Solve
        </button>
      </div>
    );
  }
  const unit = s.scoring === "points" ? "matchups won" : "categories won";
  if (!best.move) return <div className="move dim" title={`over ${best.label}`}>{bestLine(best)}</div>;
  return (
    <div className="move" title={`expected ${unit} the move adds over ${best.label}; the ${best.moves} recommended together add ${gainLabel(best.gain)}`}>
      <span className="k">Move</span>
      <span>{bestLine(best)}</span>
      <span className="grow" />
      <span className="good">{gainLabel(best.move.gain)}</span>
    </div>
  );
}
