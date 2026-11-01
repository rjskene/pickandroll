import assert from "node:assert/strict";
import { test } from "node:test";
import { railItems, railLoop, railOpen, railTime, railTimed } from "./railModel.ts";
import { TRACKS } from "./tracks/index.ts";
import { daily } from "./tracks/daily.ts";
import { draft } from "./tracks/draft.ts";
import { moves } from "./tracks/moves.ts";
import type { Track } from "./types";

test("an hour reads as hh:mm, to the nearest minute", () => {
  assert.equal(railTime(4.83), "04:50");
  assert.equal(railTime(5), "05:00");
  assert.equal(railTime(9.25), "09:15");
  assert.equal(railTime(22.67), "22:40");
  assert.equal(railTime(23.999), "00:00");
});

test("the rows before the current one are done, the current one lit, the rest to do", () => {
  const items = railItems(draft, 3);
  assert.equal(items.length, draft.labels.length);
  assert.deepEqual(
    items.map((it) => it.state),
    ["done", "done", "done", "cur", "todo", "todo", "todo", "todo", "todo"],
  );
  assert.ok(items.every((it) => it.can));
  assert.equal(items[3].label, "Objective");
});

test("a row past the written steps is still to come and opens nothing", () => {
  const short: Track = { ...moves, steps: moves.steps.slice(0, 2) };
  const items = railItems(short, 1);
  assert.deepEqual(
    items.map((it) => [it.state, it.can]),
    [
      ["done", true],
      ["cur", true],
      ["soon", false],
      ["soon", false],
    ],
  );
});

test("the daily rows carry their time of day; the day's overview row has none", () => {
  assert.ok(railTimed(daily));
  const items = railItems(daily, 0);
  assert.equal(items[0].time, null);
  assert.deepEqual(
    items.slice(1).map((it) => it.time),
    ["04:50", "05:00", "06:45", "09:00", "09:15", "15:00", "21:00", "22:40"],
  );
  for (let i = 2; i < items.length; i++) assert.ok((items[i].time ?? "") > (items[i - 1].time ?? ""), `${i}: times ascend`);
  assert.ok(items.every((it) => !/^\d\d:\d\d/.test(it.label)), "the time is its own column, not in the label");
});

test("only the draft has a loop, from the room back to survival, labelled short", () => {
  const loop = railLoop(draft);
  assert.ok(loop);
  assert.equal(draft.labels[loop.from], "Yahoo room");
  assert.equal(draft.labels[loop.to], "Survival");
  assert.ok(loop.label.length <= 30, loop.label);
  assert.equal(railLoop(moves), undefined);
  assert.equal(railLoop(daily), undefined);
  assert.equal(railLoop({ ...draft, loop: { from: 2, to: 8, label: "x" } }), undefined, "a loop runs back up the rail");
});

test("every track's rail has a short lede and a short title for the phone", () => {
  for (const t of TRACKS) {
    assert.ok(t.lede.length <= 120, `${t.id}: lede ${t.lede.length}`);
    assert.match(t.lede, /^[A-Z]/, `${t.id}: the lede is a sentence on its own`);
    assert.ok(t.short && t.short.length <= 8, `${t.id}: short title`);
    for (const l of t.labels) assert.ok(l.length <= 16, `${t.id}: label "${l}" fits the rail`);
  }
});

test("the rail opens unless this browser kept it folded", () => {
  assert.equal(railOpen(null), true);
  assert.equal(railOpen("open"), true);
  assert.equal(railOpen("folded"), false);
  assert.equal(railOpen("FOLDED"), true);
  assert.equal(railOpen(""), true);
});
