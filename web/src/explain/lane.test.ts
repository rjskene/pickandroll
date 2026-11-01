import assert from "node:assert/strict";
import { test } from "node:test";
import { DAY_END, dayLanes, dayNow, dayTicks } from "./dayline.ts";
import { M, hhmm, laneEvents, laneState, laneWord, nextEvent, prevEvent } from "./lane.ts";
import type { Lane } from "./lane.ts";

const ln: Lane = { name: "x", segs: [{ a: 0, b: 10, k: "idle", l: "waits" }, { a: 10, b: 13, k: "run", l: "runs" }, { a: 13, b: 100, k: "after", l: "ran", w: "fired" }], marks: [{ at: 50, k: "stop" }] };

test("a lane's state is the segment the marker is in, the last past the end", () => {
  assert.equal(laneState(ln, 0).l, "waits");
  assert.equal(laneState(ln, 10).l, "runs");
  assert.equal(laneState(ln, 12.9).l, "runs");
  assert.equal(laneState(ln, 13).l, "ran");
  assert.equal(laneState(ln, 500).l, "ran");
  assert.equal(laneWord(laneState(ln, 0)), "—");
  assert.equal(laneWord(laneState(ln, 11)), "running");
  assert.equal(laneWord(laneState(ln, 20)), "fired");
});

test("events are every edge and mark, once, ascending", () => {
  assert.deepEqual(laneEvents([ln]), [0, 10, 13, 50, 100]);
  const ev = laneEvents([ln]);
  assert.equal(nextEvent(ev, 0, 100), 10);
  assert.equal(nextEvent(ev, 10, 100), 13);
  assert.equal(nextEvent(ev, 99, 100), 100);
  assert.equal(nextEvent(ev, 100, 100), 100);
  assert.equal(prevEvent(ev, 13, 0), 10);
  assert.equal(prevEvent(ev, 12, 0), 10);
  assert.equal(prevEvent(ev, 0, 0), 0);
});

test("minutes read as a clock", () => {
  assert.equal(hhmm(0), "00:00");
  assert.equal(hhmm(M(9, 15)), "09:15");
  assert.equal(hhmm(1440), "24:00");
  assert.equal(dayNow(M(22, 30), "sun"), "22:30 Sun");
  assert.equal(dayNow(M(6), "mon"), "06:00 Mon");
  assert.equal(dayNow(M(6), "week"), "06:00");
});

const lane = (lanes: Lane[], name: string) => {
  const l = lanes.find((x) => x.name.startsWith(name));
  assert.ok(l, name);
  return l;
};

test("a weekday's queue entry waits out the veto window, is due at 09:00 and claimed at 09:15", () => {
  const q = lane(dayLanes("week", false), "queue entry");
  assert.equal(laneState(q, M(5)).k, "idle");
  assert.equal(laneState(q, M(6)).k, "block");
  assert.equal(laneState(q, M(8)).k, "block");
  assert.equal(laneState(q, M(9)).k, "open");
  assert.equal(laneState(q, M(9, 15)).k, "done");
  assert.deepEqual(q.marks, [{ at: M(9), k: "tick" }]);
});

test("Sunday's execute time is 22:30 and the evening pass takes the claim", () => {
  const lanes = dayLanes("sun", false);
  const q = lane(lanes, "queue entry");
  assert.equal(laneState(q, M(12)).k, "block");
  assert.equal(laneState(q, M(22, 30)).k, "open");
  assert.equal(laneState(q, M(22, 40)).k, "done");
  assert.match(laneState(lane(lanes, "morning pass"), M(9, 20)).l, /nothing due/);
});

test("the recorder runs on Mondays only, inside its window", () => {
  const mon = lane(dayLanes("mon", false), "Monday recorder");
  assert.equal(laneState(mon, M(5)).k, "block");
  assert.equal(laneState(mon, M(6, 10)).k, "run");
  assert.equal(laneState(mon, M(11)).k, "open");
  assert.equal(laneState(mon, M(13)).k, "block");
  const week = lane(dayLanes("week", false), "Monday recorder");
  assert.equal(laneState(week, M(6, 10)).k, "block");
});

test("the working-agreement lane is open between windows and blocked inside; a draft room blocks the day", () => {
  const g = lane(dayLanes("week", false), "pull");
  assert.equal(laneState(g, M(2)).k, "open");
  assert.equal(laneState(g, M(5, 30)).k, "block");
  assert.equal(laneState(g, M(7)).k, "open");
  assert.equal(laneState(g, M(10)).k, "block");
  assert.equal(laneState(g, M(23, 30)).k, "open");
  const monday = lane(dayLanes("mon", false), "pull");
  assert.equal(laneState(monday, M(7)).k, "block");
  assert.match(laneState(monday, M(7)).l, /05:00 to 14:30/);
  const room = dayLanes("week", true);
  assert.equal(laneState(lane(room, "pull"), M(12)).k, "block");
  assert.equal(laneState(lane(room, "morning pass"), M(9, 20)).k, "block");
  assert.equal(laneState(lane(room, "daily chain"), M(5, 10)).k, "run");
});

test("the evening pass stops hard at 22:58 and the lineup lane locks at tip-off", () => {
  const lanes = dayLanes("week", false);
  const ev = lane(lanes, "evening pass");
  assert.deepEqual(ev.marks, [{ at: M(22, 58), k: "stop" }]);
  assert.match(laneState(ev, M(23)).l, /opens nothing/);
  const lu = lane(lanes, "lineup move");
  assert.equal(laneState(lu, M(17, 59)).k, "open");
  assert.equal(laneState(lu, M(18)).k, "block");
});

test("every lane covers the day without gaps", () => {
  for (const day of ["week", "sun", "mon"] as const)
    for (const room of [false, true])
      for (const ln of dayLanes(day, room)) {
        assert.equal(ln.segs[0].a, 0, ln.name);
        assert.equal(ln.segs[ln.segs.length - 1].b, DAY_END, ln.name);
        for (let i = 1; i < ln.segs.length; i++) assert.equal(ln.segs[i].a, ln.segs[i - 1].b, `${ln.name} ${i}`);
      }
  assert.equal(dayTicks(false).length, 9);
  assert.equal(dayTicks(true).length, 5);
});
