import { useEffect, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type BestMove, type ProjectionSystem, type SeasonSummary } from "../api";
import type { SeasonViewId } from "../keys";
import { isExpanded, isRefreshing, landingRows, leaguesLabel, onLanding, toggleExpanded, type GridOrder } from "../season";
import { LeagueBlock, UnreadBlock } from "./LeagueBlock";
import { StatusSheet, useSeasonStatus } from "./StatusLight";

/** The table's moves come from the league page's default projection, so a solve there shows here. */
const SYSTEM: ProjectionSystem = "bbm";
const ORDER_KEY = "pickandroll.landing.order";
const POINTS_KEY = "pickandroll.landing.points";

function savedOrder(): GridOrder {
  try {
    return localStorage.getItem(ORDER_KEY) === "name" ? "name" : "gain";
  } catch {
    return "gain";
  }
}

function savedPoints(): boolean {
  try {
    return localStorage.getItem(POINTS_KEY) === "shown";
  } catch {
    return false;
  }
}

/** The leagues in season as a table (#191, after the #108 grid): two rows per league, this week's
 * score, the opponent, my place, the adds left, the flags, the best recommended move with its
 * gain and the freshness light, then the format, my team, the week and the set in a line; a
 * chevron opens the whole recommended set and the league's facts. The private league is pinned
 * first and opens expanded; the points leagues are hidden until shown. The best move is only
 * ever read from the moves already solved today: loading the table solves nothing, a league
 * without an answer says so, and its button solves it. */
export default function LeagueGrid({ onOpen }: { onOpen: (league: string, view?: SeasonViewId) => void }) {
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
  const [showPoints, setShowPointsState] = useState(savedPoints);
  const setShowPoints = (shown: boolean) => {
    setShowPointsState(shown);
    try {
      localStorage.setItem(POINTS_KEY, shown ? "shown" : "hidden");
    } catch {
      // Like the order: hidden again without storage.
    }
  };
  // The panels opened or closed by hand; the private league's starts open.
  const [toggled, setToggled] = useState<ReadonlyMap<string, boolean>>(new Map());
  const list = seasons.data ?? [];
  // Only the leagues shown look for their best move: a hidden points league costs no request.
  const shown = list.filter((s) => onLanding(s, showPoints));
  const movable = shown.filter((s) => s.has_snapshot && !s.error && s.my_team);
  // One look per league, each row filling in as its answer lands; a new snapshot looks again.
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
  // Each row's freshness light (#153) and the league whose sheet is open; a new read moves it.
  const status = useSeasonStatus();
  const [sheetFor, setSheetFor] = useState<string | null>(null);
  const reads = list.map((s) => s.updated_at).join();
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ["status"] });
  }, [queryClient, reads]);
  const open = list.find((s) => s.league === sheetFor);
  const now = Date.now();
  if (!list.length && !seasons.error) return seasons.isPending ? <p className="muted">Reading the leagues…</p> : null;
  const rows = landingRows(list, best, order, showPoints);
  const block = (s: SeasonSummary) => {
    const common = {
      s,
      status: status.data,
      refreshing: refresh.isPending && refresh.variables === s.league,
      onRefresh: () => refresh.mutate(s.league),
      onStatus: () => setSheetFor(s.league),
    };
    if (s.error || !s.has_snapshot) return <UnreadBlock key={s.league} {...common} />;
    return (
      <LeagueBlock
        key={s.league}
        {...common}
        now={now}
        best={best.get(s.league)}
        lookError={lookError.get(s.league) ?? null}
        solving={solving.has(s.league)}
        solveError={solve.isError && solve.variables?.league === s.league ? solve.error.message : null}
        open={isExpanded(s, toggled)}
        onToggle={() => setToggled((t) => toggleExpanded(s, t))}
        onOpen={() => onOpen(s.league)}
        onLineup={() => onOpen(s.league, "lineup")}
        onSolve={() => solve.mutate(s)}
      />
    );
  };
  return (
    <section className="league-grid" aria-label="Leagues">
      <div className="lg-head">
        <h2>LEAGUES</h2>
        <span className="muted">
          {leaguesLabel([...rows.pinned, ...rows.rest])} · the private league first, then the rest by {order === "gain" ? "most to gain" : "name"} · a
          chevron opens the league's recommended set, its name the league page
        </span>
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
      <div className="lt-scroll">
        <div className="lt">
          <div className="lt-head">
            <span />
            <span className="k">League</span>
            <span className="k">This week</span>
            <span className="k">Place</span>
            <span className="k">Adds</span>
            <span className="k">Flags</span>
            <span className="k">Best move</span>
            <span className="k lt-gain">Gain</span>
            <span className="k">Read</span>
            <span />
          </div>
          {rows.pinned.map(block)}
          {rows.rest.map(block)}
        </div>
      </div>
      {list.some((s) => s.public !== false && s.scoring === "points") && (
        <p className="lt-foot muted">
          {showPoints ? (
            <button className="link" onClick={() => setShowPoints(false)}>
              hide the points leagues
            </button>
          ) : (
            <>
              {rows.hidden} points league{rows.hidden === 1 ? "" : "s"} hidden{" "}
              <button className="link" onClick={() => setShowPoints(true)}>
                show them
              </button>
            </>
          )}
        </p>
      )}
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

