// Node's own test runner with its built-in type stripping (`npm test`); outside tsc's project,
// since the web app has no Node types.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { PickRow, Score, ScoreEntry } from "../../api";
import { scorePoints, turnFilter } from "./scoreTurns.ts";

const ME = "t4";

const entry = (version: number, next_overall: number, on_the_clock: boolean, wins: number, mode: ScoreEntry["mode"] = "horizon"): ScoreEntry => ({
  version,
  next_overall,
  my_pick: on_the_clock ? next_overall : null,
  on_the_clock,
  mode,
  wins,
  value: wins * 10,
  matchups: Math.round(wins),
  top: `player ${version}`,
  drafted: 0,
  at: "",
});

const pick = (overall: number, team: string): PickRow => ({ overall, round: 1, position: 1, team, player_id: `p${overall}`, name: `player at ${overall}`, keeper: false });

const score = (history: ScoreEntry[], benchmark: ScoreEntry | null, extra: Partial<Score> = {}): Score => ({
  version: history.length ? history[history.length - 1].version : 0,
  objective: "wins" as Score["objective"],
  benchmark,
  best: null,
  latest: history.length ? history[history.length - 1] : null,
  final: null,
  drafted: 0,
  roster_size: 13,
  drafted_wins: 0,
  drafted_value: 0,
  current_wins: null,
  vs_benchmark: null,
  vs_best: null,
  history,
  ...extra,
});

test("a solve off the clock is never a turn", () => {
  assert.equal(turnFilter([], ME)(entry(1, 2, false, 5)), false);
});

test("my slot is a turn while its pick is not made, and once I make it", () => {
  const isTurn = turnFilter([pick(4, ME)], ME);
  assert.equal(isTurn(entry(1, 4, true, 5)), true);
  assert.equal(isTurn(entry(2, 21, true, 5)), true);
});

test("a slot the snake calls mine that another team picked at is not my turn", () => {
  const isTurn = turnFilter([pick(4, ME), pick(21, "t9")], ME);
  assert.equal(isTurn(entry(2, 21, true, 5)), false);
});

test("with the session's owner map, only my slots are turns: an acquired pick is, a traded-away one is not", () => {
  // Position 4 gave the snake's 28 and 45 to position 1 for 144 and 145 (traded picks).
  const mine = [4, 21, 52, 69, 76, 93, 100, 117, 124, 141, 144, 145, 148];
  const isTurn = turnFilter([pick(4, ME)], ME, mine);
  assert.equal(isTurn(entry(2, 28, true, 5)), false, "28 is position 1's whatever the snake says");
  assert.equal(isTurn(entry(3, 144, true, 5)), true, "144 is mine by the map");
  assert.equal(isTurn(entry(4, 52, true, 5)), true);
  assert.equal(isTurn(entry(5, 52, false, 5)), false, "still off the clock is no turn");
  // The booked team still rules out a slot the map calls mine that another team picked at.
  assert.equal(turnFilter([pick(21, "t9")], ME, mine)(entry(6, 21, true, 5)), false);
  // No map given (null): the booked team alone decides, as before.
  assert.equal(turnFilter([pick(4, ME)], ME, null)(entry(7, 28, true, 5)), true);
});

test("no picks loaded yet: every on-the-clock solve counts", () => {
  assert.equal(turnFilter(undefined, ME)(entry(1, 4, true, 5)), true);
});

test("points run pre, then each real turn in draft order, then now", () => {
  const pre = entry(1, 3, false, 5.0);
  const history = [pre, entry(2, 4, true, 5.1), entry(3, 9, false, 5.0), entry(4, 21, true, 5.2), entry(5, 28, true, 5.3)];
  const pts = scorePoints(score(history, pre), turnFilter([pick(4, ME), pick(21, ME)], ME));
  assert.deepEqual(
    pts.map((p) => [p.kind, p.overall, p.wins]),
    [
      ["pre", 3, 5.0],
      ["turn", 4, 5.1],
      ["turn", 21, 5.2],
      ["turn", 28, 5.3],
    ],
  );
});

test("a traded slot drops out; the latest solve after it shows as now", () => {
  const pre = entry(1, 3, false, 5.0);
  const history = [pre, entry(2, 4, true, 5.1), entry(3, 21, true, 5.2), entry(4, 22, false, 6.5, "roster")];
  const pts = scorePoints(score(history, pre), turnFilter([pick(4, ME), pick(21, "t9")], ME));
  assert.deepEqual(
    pts.map((p) => [p.kind, p.overall, p.mode]),
    [
      ["pre", 3, "horizon"],
      ["turn", 4, "horizon"],
      ["now", 22, "roster"],
    ],
  );
});

test("a turn re-solved on the same board keeps its last solve", () => {
  const pre = entry(1, 3, false, 5.0);
  const history = [pre, entry(2, 4, true, 5.1), entry(3, 4, true, 6.4, "roster")];
  const pts = scorePoints(score(history, pre), turnFilter([], ME));
  assert.deepEqual(
    pts.map((p) => [p.kind, p.overall, p.wins, p.mode]),
    [
      ["pre", 3, 5.0, "horizon"],
      ["turn", 4, 6.4, "roster"],
    ],
  );
});

test("the benchmark is my first turn's own solve: it is shown once, as pre", () => {
  const first = entry(1, 4, true, 5.0);
  assert.deepEqual(
    scorePoints(score([first], first), turnFilter([], ME)).map((p) => p.kind),
    ["pre"],
  );
  const history = [first, entry(2, 21, true, 5.2)];
  assert.deepEqual(
    scorePoints(score(history, first), turnFilter([pick(4, ME)], ME)).map((p) => [p.kind, p.overall]),
    [
      ["pre", 4],
      ["turn", 21],
    ],
  );
});

test("the final roster replaces now once the draft is over", () => {
  const pre = entry(1, 3, false, 5.0);
  const history = [pre, entry(2, 4, true, 5.1), entry(3, 9, false, 5.0)];
  const final = { wins: 5.4, value: 40, matchups: 7, cats_beaten: 50, opponents: [], categories: [] };
  const pts = scorePoints(score(history, pre, { final }), turnFilter([pick(4, ME)], ME));
  assert.deepEqual(
    pts.map((p) => [p.kind, p.wins, p.mode]),
    [
      ["pre", 5.0, "horizon"],
      ["turn", 5.1, "horizon"],
      ["final", 5.4, null],
    ],
  );
});

test("no solves yet: no points", () => {
  assert.deepEqual(scorePoints(score([], null), turnFilter([], ME)), []);
});
