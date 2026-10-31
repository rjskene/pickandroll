import { useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { api, type BestMove, type ProjectionSystem } from "../api";
import { isRefreshing, landingRows, onLanding, type GridOrder } from "../season";

/** The table's moves come from the league page's default projection, so a solve there shows here. */
export const SYSTEM: ProjectionSystem = "bbm";
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

/** The landing table's leagues in its order (#191): its saved sort and points setting, each
 * shown league's best move read from the moves already solved today (a look solves nothing).
 * The table, the landing's overview sheet and the league page's previous and next buttons
 * (#253) share it: the same queries, so one answer serves all three. The landing holds one for
 * its table and its sheet, so a new sort moves both. */
export function useLandingOrder() {
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
  const list = seasons.data ?? [];
  // Only the leagues shown look for their best move: a hidden points league costs no request.
  const movable = list.filter((s) => onLanding(s, showPoints) && s.has_snapshot && !s.error && s.my_team);
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
  const rows = landingRows(list, best, order, showPoints);
  return { seasons, list, best, lookError, rows, order, setOrder, showPoints, setShowPoints };
}

export type LandingOrder = ReturnType<typeof useLandingOrder>;
