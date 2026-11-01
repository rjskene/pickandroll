import assert from "node:assert/strict";
import { test } from "node:test";
import { laneEvents, laneState, laneWord } from "./lane.ts";
import type { Lane } from "./lane.ts";
import { RC_END, rcLanes, rcLeft, rcTicks } from "./roomclock.ts";
import type { Act, Board, Row } from "./roomclock.ts";

const BOARDS: Board[] = ["hit", "cold"];
const ACTS: Act[] = [0, 15];
const ROWS: Row[] = ["found", "top4", "none"];

const lane = (lanes: Lane[], name: string): Lane => {
  const ln = lanes.find((l) => l.name === name);
  assert.ok(ln, name);
  return ln;
};

test("every lane covers the whole turn with no gaps or overlaps, in every setting", () => {
  for (const b of BOARDS)
    for (const a of ACTS)
      for (const r of ROWS) {
        const lanes = rcLanes(b, a, r);
        assert.equal(lanes.length, 7);
        for (const ln of lanes) {
          assert.equal(ln.segs[0].a, 0, `${b}/${a}/${r} ${ln.name}`);
          assert.equal(ln.segs[ln.segs.length - 1].b, RC_END, `${b}/${a}/${r} ${ln.name}`);
          for (let i = 1; i < ln.segs.length; i++) assert.equal(ln.segs[i].a, ln.segs[i - 1].b, `${b}/${a}/${r} ${ln.name} ${i}`);
          for (const g of ln.segs) assert.ok(g.b >= g.a && g.l.length > 0, `${b}/${a}/${r} ${ln.name}`);
        }
        const ev = laneEvents(lanes);
        assert.equal(ev[0], 0);
        assert.equal(ev[ev.length - 1], RC_END);
      }
});

test("a hit is solved ahead: the click lands within 2 s of the turn", () => {
  const lanes = rcLanes("hit", 0, "found");
  assert.equal(laneWord(laneState(lane(lanes, "plan solve"), 0)), "ran");
  assert.equal(laneState(lane(lanes, "the drafter's wait"), 0).k, "open");
  assert.equal(laneState(lane(lanes, "the drafter's wait"), 1).k, "after");
  assert.equal(laneState(lane(lanes, "the click"), 1).k, "run");
  assert.equal(laneState(lane(lanes, "the click"), 2.1).k, "done");
  assert.equal(laneState(lane(lanes, "queue backstop"), 29).k, "idle");
  assert.equal(laneState(lane(lanes, "Yahoo's autopick"), 29.9).k, "idle");
});

test("a cold board solves 5 s then prices 12 s; the wait holds to 12 s left and the plan is fresh", () => {
  const lanes = rcLanes("cold", 0, "found");
  assert.equal(laneState(lane(lanes, "plan solve"), 4.9).k, "run");
  assert.equal(laneState(lane(lanes, "plan solve"), 5).k, "after");
  assert.equal(laneState(lane(lanes, "pricing"), 4.9).k, "idle");
  assert.equal(laneState(lane(lanes, "pricing"), 16.9).k, "run");
  assert.equal(laneState(lane(lanes, "pricing"), 17).k, "after");
  const wait = lane(lanes, "the drafter's wait");
  assert.equal(laneState(wait, 16.9).k, "open");
  assert.match(laneState(wait, 17).l, /fresh plan arrived with 13 s left/);
  assert.deepEqual(wait.marks, [{ at: 18, k: "tick" }]);
  assert.equal(laneState(lane(lanes, "the click"), 17).k, "run");
  assert.equal(laneState(lane(lanes, "the click"), 18.5).k, "done");
});

test("act at 15 s left holds a hit's click, and a cold board's wait runs to act time, not fresh", () => {
  const hit = rcLanes("hit", 15, "found");
  const hold = lane(hit, "act-at hold");
  assert.equal(laneState(hold, 0.4).k, "idle");
  assert.equal(laneState(hold, 10).k, "block");
  assert.equal(laneState(hold, 15).k, "after");
  assert.equal(laneState(lane(hit, "the click"), 14.9).k, "idle");
  assert.equal(laneState(lane(hit, "the click"), 15).k, "run");
  const cold = rcLanes("cold", 15, "found");
  assert.equal(laneState(lane(cold, "act-at hold"), 10).k, "idle");
  assert.match(laneState(lane(cold, "the drafter's wait"), 15).l, /the wait ran out/);
  assert.equal(laneState(lane(cold, "the click"), 15).k, "run");
});

test("no row at all: the view resets until 2 s left, nothing to queue, Yahoo autopicks at zero", () => {
  const lanes = rcLanes("hit", 0, "none");
  assert.equal(laneState(lane(lanes, "the click"), 27.9).k, "run");
  assert.equal(laneState(lane(lanes, "the click"), 28).k, "block");
  assert.equal(laneState(lane(lanes, "queue backstop"), 23.9).k, "idle");
  assert.equal(laneState(lane(lanes, "queue backstop"), 24).k, "open");
  assert.equal(laneState(lane(lanes, "queue backstop"), 28).k, "block");
  const auto = lane(lanes, "Yahoo's autopick");
  assert.equal(laneState(auto, 28).k, "block");
  assert.equal(laneWord(laneState(auto, 29)), "at zero");
  assert.deepEqual(auto.marks, [{ at: 30, k: "stop" }]);
});

test("the top four missing: the backstop queues the best remaining candidate at 6 s left", () => {
  const lanes = rcLanes("cold", 0, "top4");
  assert.equal(laneState(lane(lanes, "the click"), 23.9).k, "run");
  assert.equal(laneState(lane(lanes, "the click"), 24).k, "after");
  const q = lane(lanes, "queue backstop");
  assert.equal(laneState(q, 24).k, "run");
  assert.equal(laneState(q, 24.6).k, "done");
  assert.deepEqual(q.marks, [{ at: 24, k: "stop" }]);
  assert.equal(laneState(lane(lanes, "Yahoo's autopick"), 29).k, "idle");
});

test("the clock reads seconds left and ticks every 5 s, 10 s on a phone", () => {
  assert.equal(rcLeft(0), "30 s left");
  assert.equal(rcLeft(17.5), "12.5 s left");
  assert.equal(rcLeft(30), "0 s left");
  assert.deepEqual(
    rcTicks(false).map((t) => t.l),
    ["30 s", "25 s", "20 s", "15 s", "10 s", "5 s", "0 s"],
  );
  assert.deepEqual(
    rcTicks(true).map((t) => t.v),
    [0, 10, 20, 30],
  );
});
