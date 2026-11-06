// The History screen's words and filters (#334).
import assert from "node:assert/strict";
import { test } from "node:test";
import type { HistoryRow } from "./api";
import { bidText, filterRows, moveLine, NO_FILTER, whyLines } from "./history.ts";

const name = (id: number | null | undefined) => (id == null ? "" : `P${id}`);

function row(over: Partial<HistoryRow> = {}): HistoryRow {
  return {
    id: "x",
    league: "1",
    date: "2026-11-02",
    at: null,
    kind: "claim",
    player: null,
    add: 1,
    drop: 2,
    sides: null,
    bid: 3,
    result: "won",
    who: "the queue",
    unread: false,
    why: {},
    ...over,
  };
}

test("the filters take league, kind and result together", () => {
  const rows = [row({ id: "a" }), row({ id: "b", league: "2" }), row({ id: "c", kind: "drop" }), row({ id: "d", result: "lost" })];
  assert.deepEqual(filterRows(rows, NO_FILTER).length, 4);
  assert.deepEqual(filterRows(rows, { ...NO_FILTER, league: "2" }).map((r) => r.id), ["b"]);
  assert.deepEqual(filterRows(rows, { league: "1", kind: "claim", result: "won" }).map((r) => r.id), ["a"]);
});

test("a move's line names the add and the drop, a lone one alone", () => {
  assert.equal(moveLine(row(), name), "+P1 · −P2");
  assert.equal(moveLine(row({ add: null, kind: "drop" }), name), "−P2");
  assert.equal(moveLine(row({ drop: null }), name), "+P1");
});

test("a comeback and an IL move name who moved", () => {
  assert.equal(moveLine(row({ kind: "comeback", player: 5, add: null, drop: 6 }), name), "P5 back · −P6");
  assert.equal(moveLine(row({ kind: "il", player: 7, add: null, drop: null, why: { need: { for: 1, slot: "IL" } } }), name), "P7 to IL");
});

test("a trade reads its sides, and lists its players when no side reads", () => {
  const sides = [
    { player: 1, name: "A", side: "got" as const, detail: null },
    { player: 2, name: "B", side: "gave" as const, detail: null },
  ];
  assert.equal(moveLine(row({ kind: "trade", sides }), name), "got A · gave B");
  assert.equal(moveLine(row({ kind: "trade", sides: sides.map((s) => ({ ...s, side: null })), unread: true }), name), "A, B");
});

test("a queued move says its set, gains, odds and bid", () => {
  const why = { set: "three", week: 0.2, three: 0.4, season: 1.5, matchup: 0.61, bid_reason: "$3: over the typical gain" };
  assert.deepEqual(whyLines(row({ why }), name), [
    "From the three weeks' set.",
    "Gain: +0.20 this week, +0.40 over the three weeks, +1.50 to the season's end.",
    "Matchup odds when logged: 61%.",
    "Bid: $3: over the typical gain.",
  ]);
});

test("a week plan's step says which, and the odds it was chosen against", () => {
  const why = { set: "week_plan", step: 2, steps_of: 3, week: 0.3, three: -0.1, matchup: 0.7, against: 0.6 };
  const lines = whyLines(row({ why }), name);
  assert.equal(lines[0], "Step 2 of 3 of the week plan.");
  assert.equal(lines[2], "Matchup odds when logged: 70%, against 60% with the three weeks' set.");
});

test("a move by hand says how it compared and with what gains", () => {
  const why = { match: "differently", move: { add: 1, drop: 2 }, set: "three", week: 0.2, three: 0.4 };
  assert.deepEqual(whyLines(row({ why }), name), [
    "Made differently from the latest recommendation.",
    "It said +P1 · −P2, from the three weeks' set.",
    "Gain: +0.20 this week, +0.40 over the three weeks.",
  ]);
  assert.deepEqual(whyLines(row({ why: { match: "not_recommended" } }), name), ["Not among the latest recommendation's moves."]);
});

test("a row with no record says so plainly", () => {
  assert.deepEqual(whyLines(row({ why: { match: "no_entry", note: "no record: moves before 2026-10-24 have no queue record" } }), name), [
    "no record: moves before 2026-10-24 have no queue record",
  ]);
});

test("a comeback and an IL move give the need and each step's outcome", () => {
  const steps = [
    { stage: "drop", player: 6, outcome: "dropped", at: null, words: null },
    { stage: "move", player: 5, outcome: "failed", at: null, words: "Error 160" },
  ];
  assert.deepEqual(whyLines(row({ kind: "comeback", why: { need: "he needs a drop first", steps } }), name), ["he needs a drop first", "drop P6, dropped", "move P5, failed: Error 160"]);
  assert.equal(whyLines(row({ kind: "il", why: { need: { for: 1, slot: "IL" }, steps: [] } }), name)[0], "It opened a spot for the claim on P1.");
});

test("a bid reads in dollars, blank for none and $0 for a zero bid", () => {
  assert.equal(bidText(null), "");
  assert.equal(bidText(0), "$0");
  assert.equal(bidText(4), "$4");
});
