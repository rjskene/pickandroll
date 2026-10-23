// Node's own test runner with its built-in type stripping (`npm test`), as format.test.ts.
// Every value is made up; leagues are numbered 1001, 1002 (public) and 2001 (private).
import assert from "node:assert/strict";
import { test } from "node:test";
import type { KnobChange, PooledWeek, ProgressLeague, ProgressMove, ProgressPayload, ProgressWeek } from "./api";
import {
  abGap,
  addMoves,
  bucketsOver,
  entryTime,
  matchCounts,
  moveCats,
  moveFigures,
  moveHorizon,
  movesTotals,
  movesTrend,
  scopeMoves,
  knobValue,
  lineupLostTitle,
  POOLED,
  rangeSum,
  recordedRange,
  recordLabel,
  scopeSentences,
  scopeWeeks,
  seasonFigures,
  shownRange,
  stepChange,
  stepRange,
  trend,
  verdictLabel,
  whyTried,
} from "./progress.ts";

const WEEKS = [
  { week: 1, start: "2026-10-19", end: "2026-10-25" },
  { week: 2, start: "2026-10-26", end: "2026-11-01" },
  { week: 3, start: "2026-11-02", end: "2026-11-08" },
];

function row(week: number, over: Partial<ProgressWeek> = {}, moves: Partial<ProgressWeek["moves"]> = {}): ProgressWeek {
  const expected = over.expected ?? 0.6;
  const won = over.won ?? 1;
  return {
    week,
    start: WEEKS[week - 1].start,
    end: WEEKS[week - 1].end,
    scoring: "categories",
    expected,
    won,
    outcome: won === 1 ? "W" : won === 0 ? "L" : "T",
    expected_categories: 5,
    categories: 6,
    brier: Number(((expected - won) ** 2).toFixed(4)),
    rank: 4,
    teams: 12,
    record: null,
    moves: { made: 1, scored: 1, realized_only: 0, unscored: 0, projected: 1, realized: 0.5, compared: null, paid: 0, ...moves },
    lineup_lost: null,
    cum: { weeks: 0, expected: 0, won: 0, won_all: 0, expected_categories: null, categories: null, moves: { made: 0, realized_value: {}, compared: {} } },
    ...over,
  };
}

function league(id: string, pub: boolean, weeks: ProgressWeek[]): ProgressLeague {
  return { league: id, public: pub, status: "recorded", scoring: weeks[0]?.scoring ?? null, weeks };
}

function change(over: Partial<KnobChange> = {}): KnobChange {
  return {
    id: "K1",
    monday: "2026-10-26",
    knob: "blend",
    from: 0.5,
    to: 0.6,
    leagues: ["1001"],
    source: "master",
    reason: "the blend leans on one system",
    decided_at: null,
    verdict: null,
    judged_on: null,
    rolled_out: null,
    week: 2,
    ab: null,
    ...over,
  };
}

function payload(leagues: ProgressLeague[], over: Partial<ProgressPayload> = {}): ProgressPayload {
  return {
    system: "bbm",
    today: "2026-11-03",
    week: 3,
    last_recorded: 2,
    weeks: WEEKS,
    leagues,
    pooled: { weeks: [], to_date: null, calibration: { weeks: 0, brier: null, buckets: [] } },
    moves: [],
    knobs: { in_force: {}, leagues: {}, frozen: {}, changes: [] },
    notes: [],
    action_items: null,
    sentences: [],
    sources: { leagues: leagues.length, recorded: leagues.length, public: 2, moves: { made: 0, as_recommended: 0, differently: 0, not_recommended: 0, no_entry: 0, near: 0 }, knob_file: false, notes: 0 },
    problems: [],
    skipped: [],
    ...over,
  };
}

const compared = (moves: number, projected: number, realized: number, same_way: number) => ({ moves, projected, realized, same_way, share: projected > 0 ? realized / projected : null });

const P = payload([
  league("1001", true, [row(1, { expected: 0.6, won: 1 }, { compared: compared(1, 2, 1, 1) }), row(2, { expected: 0.5, won: 0, rank: 3 })]),
  league("1002", true, [
    row(1, { expected: 0.4, won: 0.5, rank: 8, scoring: "points", expected_categories: null, categories: null }, { compared: compared(2, 30, 36, 2), realized: 36 }),
    row(2, { expected: 0.7, won: 1, rank: 6, scoring: "points", expected_categories: null, categories: null }),
  ]),
  league("2001", false, [row(1, { expected: 0.9, won: 0 })]),
]);

test("the pooled scope sums the public leagues' weeks and leaves the private league out", () => {
  const [w1, w2] = scopeWeeks(P, POOLED);
  assert.equal(w1.projected, 2);
  assert.equal(w1.expected, 1);
  assert.equal(w1.won, 1.5);
  assert.deepEqual(w1.record, [1, 0, 1]);
  // Only the categories league has categories.
  assert.equal(w1.expectedCategories, 5);
  assert.equal(w1.rank, 6);
  assert.equal(w1.teams, null);
  assert.deepEqual(
    w1.lines.map((l) => l.league),
    ["1001", "1002"],
  );
  // The moves by scoring, never summed across the two.
  assert.deepEqual(w1.realized, { categories: 0.5, points: 36 });
  assert.equal(w1.compared.categories?.share, 0.5);
  assert.equal(w1.compared.points?.share, 1.2);
  assert.equal(w2.won, 1);
});

test("a league's scope is its own weeks, the private league among them", () => {
  const weeks = scopeWeeks(P, "2001");
  assert.equal(weeks.length, 1);
  assert.equal(weeks[0].won, 0);
  assert.equal(weeks[0].teams, 12);
  assert.deepEqual(scopeWeeks(P, POOLED, 2, 2).map((w) => w.week), [2]);
});

test("the trend sums the actual and the expected over the range", () => {
  const wins = trend(scopeWeeks(P, POOLED), "wins");
  assert.deepEqual(
    wins.map((t) => [t.actual, t.expected]),
    [
      [1.5, 1],
      [2.5, 2.2],
    ],
  );
  const cats = trend(scopeWeeks(P, POOLED), "categories");
  assert.deepEqual(
    cats.map((t) => [t.actual, t.expected]),
    [
      [6, 5],
      [12, 10],
    ],
  );
  const standing = trend(scopeWeeks(P, "1002"), "standing");
  assert.deepEqual(
    standing.map((t) => [t.actual, t.expected]),
    [
      [8, null],
      [6, null],
    ],
  );
  // A points league has no categories: no line rather than a line at zero.
  assert.deepEqual(
    trend(scopeWeeks(P, "1002"), "categories").map((t) => t.actual),
    [null, null],
  );
});

test("the range's sums give the record, the moves by scoring and the Brier score over its matchups", () => {
  const s = rangeSum(scopeWeeks(P, POOLED));
  assert.deepEqual(s.record, [2, 1, 1]);
  assert.equal(recordLabel(s.record), "2-1-1");
  assert.equal(recordLabel([3, 2, 0]), "3-2");
  assert.equal(s.won, 2.5);
  assert.equal(s.expected, 2.2);
  assert.equal(s.rankFirst, 6);
  assert.equal(s.rankLast, 4.5);
  assert.deepEqual(Object.keys(s.compared).sort(), ["categories", "points"]);
  // Week 1: (0.16 + 0.01) / 2; week 2: (0.25 + 0.09) / 2; the mean over the four matchups.
  assert.equal(s.brierLast, 0.17);
  assert.equal(s.brier, 0.1275);
});

test("the games lost to the lineup sum the weeks read and say how many of their days were (#149)", () => {
  const p = payload([league("1001", true, [row(1), row(2, { lineup_lost: 2, lineup_days_read: 5, lineup_days: 7 })])]);
  const weeks = scopeWeeks(p, "1001");
  assert.deepEqual(
    weeks.map((w) => [w.lineupLost, w.lineupDaysRead, w.lineupDays]),
    [
      [null, 0, 7],
      [2, 5, 7],
    ],
  );
  // A week recorded before the count is a week of days not read.
  const s = rangeSum(weeks);
  assert.deepEqual([s.lineupLost, s.lineupDaysRead, s.lineupDays], [2, 5, 14]);
  assert.equal(lineupLostTitle(s), "player-games lost to the lineup: a player who played while benched with an eligible slot open or idle; 5 of 14 days read");
  assert.equal(lineupLostTitle(rangeSum(weeks.slice(0, 1))), "player-games lost to the lineup: no lineup read after its day");
  // Pooled: the public leagues' games and their league-days.
  const two = payload([
    league("1001", true, [row(2, { lineup_lost: 2, lineup_days_read: 5 })]),
    league("1002", true, [row(2, { lineup_lost: 0, lineup_days_read: 7 })]),
    league("2001", false, [row(2, { lineup_lost: 4, lineup_days_read: 7 })]),
  ]);
  const [week2] = scopeWeeks(two, POOLED);
  assert.deepEqual([week2.lineupLost, week2.lineupDaysRead, week2.lineupDays], [2, 12, 14]);
});

test("moves sums add up and keep their share", () => {
  const a = addMoves(undefined, compared(1, 2, 1, 1));
  assert.deepEqual(addMoves(a, compared(1, 2, 3, 1)), { moves: 2, projected: 4, realized: 4, same_way: 2, share: 1 });
  assert.equal(addMoves(undefined, compared(1, -1, 1, 0)).share, null);
});

test("the week range steps within the recorded weeks and never crosses itself", () => {
  assert.deepEqual(recordedRange(P, POOLED), [1, 2]);
  assert.deepEqual(recordedRange(P, "2001"), [1, 1]);
  assert.equal(recordedRange(payload([]), POOLED), null);
  assert.deepEqual(stepRange([1, 5], [1, 6], 0, 1), [2, 5]);
  assert.deepEqual(stepRange([1, 5], [1, 6], 1, 1), [1, 6]);
  assert.deepEqual(stepRange([1, 6], [1, 6], 1, 1), [1, 6]);
  assert.deepEqual(stepRange([3, 3], [1, 6], 0, 1), [3, 3]);
  assert.deepEqual(stepRange([1, 5], [1, 6], 0, -1), [1, 5]);
  assert.deepEqual(shownRange([1, 6], null), [1, 6]);
  assert.deepEqual(shownRange([2, 6], [1, 4]), [2, 4], "cut to another scope's weeks");
  assert.deepEqual(shownRange([5, 6], [1, 3]), [5, 6], "nothing left: all of the scope's");
  assert.deepEqual(shownRange(null, [1, 3]), [1, 0]);
});

test("a scope's sentences are the pooled ones with the leagues named, or a league's own", () => {
  const say = [
    { topic: "wins", scope: POOLED, tone: "neutral", text: "a" },
    { topic: "league", scope: "1001", tone: "bad", text: "b" },
    { topic: "moves", scope: POOLED, tone: "good", text: "c" },
  ] as const;
  assert.deepEqual(
    scopeSentences([...say], POOLED).map((s) => s.text),
    ["a", "b", "c"],
  );
  assert.deepEqual(
    scopeSentences([...say], "1001").map((s) => s.text),
    ["b"],
  );
});

test("a change reads pending with when it is judged, or its verdict with A over B", () => {
  assert.deepEqual(verdictLabel(change()), { text: "judged after wk 3", tone: "dim", figure: null });
  assert.equal(verdictLabel(change({ week: null })).text, "pending");
  const half = { leagues: [], moves_a_week: null, standing_climbed: 0, brier: null, moves: {} };
  const kept = change({ verdict: "kept", ab: { window: [2, 3], a: { ...half, wins_above: 0.75 }, b: { ...half, wins_above: -0.5 }, series: [] } });
  assert.deepEqual(verdictLabel(kept), { text: "kept", tone: "good", figure: "+1.3 A over B" });
  assert.equal(abGap(change({ verdict: "reverted" })), null);
  assert.equal(verdictLabel(change({ verdict: "reverted" })).tone, "bad");
});

test("the sheet steps through the changes and quotes the Monday note's decision", () => {
  const changes = [change(), change({ id: "K2", monday: "2026-11-02" })];
  assert.equal(stepChange(changes, "K1", 1), "K2");
  assert.equal(stepChange(changes, "K1", -1), "K2");
  assert.equal(stepChange(changes, "K9", 1), "K9");
  const note = { monday: "2026-10-26", posted: null, working: null, not_working: null, decision: "One change: blend.", actions: [], week: 2, scored_week: 1 };
  assert.deepEqual(whyTried(payload([], { notes: [note] }), changes[0]), { text: "One change: blend.", from: "the 2026-10-26 note" });
  assert.deepEqual(whyTried(payload([]), changes[0]), { text: "the blend leans on one system", from: "the knob file" });
  assert.equal(whyTried(payload([]), change({ reason: null })), null);
});

test("knob values read as the file holds them", () => {
  assert.equal(knobValue(0.5), "0.5");
  assert.equal(knobValue("natural"), "natural");
  assert.equal(knobValue(null), "—");
  assert.equal(knobValue({ a: 1 }), '{"a":1}');
});

function mv(over: Partial<ProgressMove> & { set?: string | null; proj?: number | null; real?: number | null; complete?: boolean } = {}): ProgressMove {
  const { set = "week", proj = 1, real = 0.5, complete = true, ...rest } = over;
  const h = set === "three" ? "three" : "week";
  const span = (value: number | null, cats: Record<string, number>) => ({ from: "2026-10-27", to: "2026-11-01", add_games: 3, drop_games: 2, value, cats });
  return {
    league: "1001",
    public: true,
    week: 2,
    scoring: "categories",
    names: { add: "Player A", drop: "Player B" },
    group: "scored",
    day: "2026-10-27",
    at: "2026-10-27T14:00:00Z",
    add: 11,
    drop: 12,
    detail: null,
    bid: 0,
    match: { kind: "as_recommended", entry: "20261027T130000000000-moves-bbm", move: null, near: false },
    projected: set == null ? null : { set, gain: {}, value: { add: 1, drop: 0, horizons: { [h]: span(proj, { pts: 0.75, reb: 0.25 }) } } },
    realized: {
      valued: real != null,
      reason: real == null ? "not_read" : null,
      add: null,
      drop: null,
      horizons: real == null ? {} : { [h]: { ...span(real, { pts: 0.75, reb: -0.25 }), through: "2026-11-01", complete, missing: [], add: real, drop: 0, gaps: 0 } },
      scorer: { entry: "e", own: true },
      lag_days: 0,
    },
    ...rest,
  };
}

test("a move is judged on its set's horizon, and its gap only once that is over", () => {
  assert.equal(moveHorizon(mv()), "week");
  assert.equal(moveHorizon(mv({ set: "plan" })), "week");
  assert.equal(moveHorizon(mv({ set: "three" })), "three");
  assert.equal(moveHorizon(mv({ set: "natural" })), "three", "a strategy set");
  assert.equal(moveHorizon(mv({ set: null })), "week");
  assert.equal(moveHorizon(mv({ judged: "three" })), "three", "the row's own judging horizon first (#143)");
  assert.deepEqual(moveFigures(mv({ set: "three", proj: 2, real: 2.5 })), { horizon: "three", projected: 2, realized: 2.5, complete: true, delta: 0.5 });
  assert.equal(moveFigures(mv({ complete: false })).delta, null, "so far");
  assert.equal(moveFigures(mv({ real: null })).realized, null);
  assert.equal(moveFigures(mv({ group: "realized_only" })).delta, null, "only a scored move is set against its projection");
});

test("the moves are filtered by scope, week and match, and totalled by scoring", () => {
  const moves = [
    mv(),
    mv({ league: "1002", scoring: "points", proj: 10, real: 12, bid: 3 }),
    mv({ league: "2001", public: false }),
    mv({ week: 3, complete: false, match: { kind: "differently", entry: null, move: null, near: false } }),
    mv({ week: 3, real: null, set: null, match: { kind: "no_entry", entry: null, move: null, near: false } }),
  ];
  const p = payload([], { moves });
  assert.equal(scopeMoves(p, POOLED).length, 4);
  assert.equal(scopeMoves(p, "2001").length, 1);
  assert.equal(scopeMoves(p, POOLED, 3, 3).length, 2);
  assert.equal(scopeMoves(p, POOLED, 1, 9, "differently").length, 1);
  assert.deepEqual(matchCounts(scopeMoves(p, POOLED)), { as_recommended: 2, differently: 1, not_recommended: 0, no_entry: 1 });
  const t = movesTotals(scopeMoves(p, POOLED));
  assert.deepEqual(t.compared.categories, { moves: 1, projected: 1, realized: 0.5, same_way: 1, share: 0.5 });
  assert.deepEqual(t.compared.points, { moves: 1, projected: 10, realized: 12, same_way: 1, share: 1.2 });
  assert.deepEqual([t.made, t.soFar, t.realizedOnly, t.unscored, t.paid, t.bids], [4, 1, 0, 1, 3, 1]);
  const borrowed = movesTotals([mv({ group: "realized_only" })]);
  assert.deepEqual([borrowed.compared, borrowed.realizedOnly], [{}, 1]);
  assert.deepEqual(movesTrend(scopeMoves(p, POOLED), [1, 2, 3], "categories"), [
    { week: 1, projected: 0, realized: 0 },
    { week: 2, projected: 1, realized: 0.5 },
    { week: 3, projected: 1, realized: 0.5 },
  ]);
});

/** ``mv`` with a season horizon (#144): projected over the season, realized so far, the flag. */
function seasonal(proj: number, soFar: number | null, costly: boolean | null, over: Partial<ProgressMove> = {}): ProgressMove {
  const m = mv(over);
  const logged = { from: "2026-10-27", to: "2027-04-04", add_games: 70.5, drop_games: 66, value: proj, cats: {}, extrapolated_games: { add: 40.5, drop: 38 } };
  const span = { from: "2026-10-27", to: "2027-04-04", through: "2026-11-01", complete: false, missing: [], add_games: 3, drop_games: 2, add: 1, drop: 0, gaps: 0, value: soFar, cats: {} };
  return {
    ...m,
    season_costly: costly,
    projected: m.projected && { ...m.projected, value: { ...m.projected.value, horizons: { ...m.projected.value.horizons, season: logged } } },
    realized: m.realized && { ...m.realized, horizons: { ...m.realized.horizons, ...(soFar == null ? {} : { season: span }) } },
  };
}

test("a move's season stands beside its judging figure, and the flagged are counted", () => {
  const v = seasonFigures(seasonal(-12.5, -1.25, true));
  assert.deepEqual(v, {
    projected: -12.5,
    games: { add: 70.5, drop: 66, extrapolated: 78.5 },
    realized: -1.25,
    read: { add: 3, drop: 2, through: "2026-11-01" },
    complete: false,
    costly: true,
  });
  // The judging figure is untouched: the week's.
  assert.deepEqual(moveFigures(seasonal(-12.5, -1.25, true)).horizon, "week");
  assert.equal(moveHorizon(seasonal(5, null, false, { judged: "season" })), "season");
  // No season horizon logged (an entry before #144): nothing, and no flag.
  assert.deepEqual(seasonFigures(mv()), { projected: null, games: { add: null, drop: null, extrapolated: 0 }, realized: null, read: { add: null, drop: null, through: null }, complete: false, costly: null });
  const t = movesTotals([
    seasonal(-12.5, -1.25, true), // flagged, below zero so far
    seasonal(-3, 0.5, true), // flagged, above so far
    seasonal(-3, -0.5, true, { group: "realized_only" }), // flagged, not scored
    seasonal(4, -0.5, false),
    mv(),
  ]);
  assert.deepEqual([t.checked, t.costly, t.costlyBelow], [4, 3, 1]);
});

test("a move's categories, largest first, with how many beat their projection", () => {
  const c = moveCats(mv());
  assert.deepEqual(
    c.rows.map((r) => [r.cat, r.projected, r.realized]),
    [
      ["pts", 0.75, 0.75],
      ["reb", 0.25, -0.25],
    ],
  );
  assert.deepEqual([c.above, c.both], [0, 2]);
  // Logged before #129: no projected split, the realized one alone.
  const old = mv();
  delete old.projected!.value.horizons.week!.cats;
  assert.deepEqual(
    moveCats(old).rows.map((r) => r.projected),
    [null, null],
  );
  assert.equal(entryTime("20261027T130500000000-moves-bbm"), "2026-10-27 13:05");
  assert.equal(entryTime(null), null);
});

test("the odds' buckets sum over the pooled weeks by count", () => {
  const b = (count: number, odds: number | null, won: number | null) => ({ from: 0.6, to: 0.8, count, odds, won });
  const week = (n: number, buckets: ReturnType<typeof b>[]) => ({ week: n, buckets }) as unknown as PooledWeek;
  const out = bucketsOver([week(1, [b(10, 0.7, 0.5)]), week(2, [b(30, 0.66, 0.7)]), week(3, [b(0, null, null)])], 1, 3);
  assert.deepEqual(out, [{ from: 0.6, to: 0.8, count: 40, odds: 0.67, won: 0.65 }]);
  assert.deepEqual(bucketsOver([week(1, [b(10, 0.7, 0.5)])], 2, 3), []);
});
