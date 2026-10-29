import type { RecommendationResponse } from "./api";

/** How often the recommendation is polled, in ms, or false for not at all (#46). While the
 * server solves (running or pending), every 2 s. Also while the result shown is older than the
 * session (``stale``, or solved for an earlier version) and a server solve is due (solve-ahead on,
 * picks left): a page that missed the ``recommendation`` event (opened mid-solve in a hidden
 * pane, or between its first fetch and the stream's connect) would otherwise show
 * "Re-planning for pick N" until the next event. Never after my last pick, or without
 * solve-ahead, where no solve comes on its own. */
export function recommendationPoll(
  data: RecommendationResponse | undefined,
  version: number,
  serverSolves: boolean,
  havePicks: boolean,
): number | false {
  if (!data) return false;
  if (data.solver.running || data.solver.pending) return 2000;
  const behind = !!data.recommendation && (data.stale || (data.solved_version ?? -1) < version);
  return behind && serverSolves && havePicks ? 2000 : false;
}
