import assert from "node:assert/strict";
import { test } from "node:test";
import type { RecommendationResponse } from "./api";
import { recommendationPoll } from "./solvePoll.ts";

const answer = (over: Partial<RecommendationResponse> = {}, solver: Partial<RecommendationResponse["solver"]> = {}): RecommendationResponse => ({
  version: 7,
  solved_version: 7,
  stale: false,
  solver: { enabled: true, running: false, pending: false, runs: 3, solved_version: 7, last_started: null, last_finished: null, last_error: null, recommendation_version: 7, ...solver },
  recommendation: {} as RecommendationResponse["recommendation"],
  ...over,
});

test("the recommendation is polled while the server solves, and while the shown result is behind the session (#46)", () => {
  assert.equal(recommendationPoll(undefined, 7, true, true), false);
  // Fresh: no poll; the next event refetches it.
  assert.equal(recommendationPoll(answer(), 7, true, true), false);
  // A solve running or queued.
  assert.equal(recommendationPoll(answer({}, { running: true }), 7, true, true), 2000);
  assert.equal(recommendationPoll(answer({}, { pending: true }), 7, true, true), 2000);
  // The missed event: the result is for an earlier version and the solver is idle.
  assert.equal(recommendationPoll(answer({ solved_version: 6 }), 7, true, true), 2000);
  assert.equal(recommendationPoll(answer({ stale: true }), 7, true, true), 2000);
  assert.equal(recommendationPoll(answer({ solved_version: null }), 7, true, true), 2000);
  // No solve comes on its own: after my last pick, or without solve-ahead; nothing to show yet.
  assert.equal(recommendationPoll(answer({ solved_version: 6 }), 7, true, false), false);
  assert.equal(recommendationPoll(answer({ solved_version: 6 }), 7, false, true), false);
  assert.equal(recommendationPoll(answer({ recommendation: null, solved_version: null }), 7, true, true), false);
});
