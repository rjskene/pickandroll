import assert from "node:assert/strict";
import { test } from "node:test";
import { hourAnchor, hourTicks, hourXs, labelRows } from "./hours.ts";
import { daily } from "./tracks/daily.ts";

test("hours already apart sit at their place on the axis", () => {
  assert.deepEqual(hourXs([0, 12, 24], 0, 240, 10), [0, 120, 240]);
});

test("dots minutes apart keep the gap, in order, and the last never passes the right end", () => {
  const xs = hourXs([4.83, 5, 6.75, 9, 9.25, 23.9, 24], 30, 330, 32);
  for (let i = 1; i < xs.length; i++) assert.ok(xs[i] - xs[i - 1] >= 32 - 1e-9, `${i}: ${xs[i - 1]} → ${xs[i]}`);
  assert.ok(xs[xs.length - 1] <= 330);
});

test("the daily track's hours fit both strips with the dots' gap", () => {
  const hours = daily.hours ?? [];
  assert.equal(hours.length, daily.labels.length);
  for (const [W, r] of [
    [960, 13],
    [360, 11],
  ]) {
    const xs = hourXs(hours, 30, W - 30, 2 * r + 10);
    assert.ok(xs[0] >= 30 && xs[xs.length - 1] <= W - 30, `${W}`);
    for (let i = 1; i < xs.length; i++) assert.ok(xs[i] - xs[i - 1] >= 2 * r + 10 - 1e-9, `${W}: ${i}`);
  }
});

test("the ticks run every three hours from 00 to 24", () => {
  const ticks = hourTicks(0, 240);
  assert.deepEqual(
    ticks.map((t) => t.h),
    [0, 3, 6, 9, 12, 15, 18, 21, 24],
  );
  assert.equal(ticks[8].x, 240);
});

test("labels on the same row never touch on the desktop strip (the phone shows one label)", () => {
  for (const [W, r] of [[960, 13]]) {
    const left = 30;
    const right = W - 30;
    const xs = hourXs(daily.hours ?? [], left, right, 2 * r + 10);
    const anchors = xs.map((x) => hourAnchor(x, left, right));
    const rows = labelRows(xs, daily.labels, anchors, 6, 6);
    assert.ok(rows.every((row) => row >= 0 && row < 3));
    const spans = xs.map((x, i) => {
      const w = daily.labels[i].length * 6;
      const x0 = anchors[i] === "start" ? x : anchors[i] === "end" ? x - w : x - w / 2;
      return [x0, x0 + w, rows[i]] as const;
    });
    for (let i = 0; i < spans.length; i++)
      for (let j = i + 1; j < spans.length; j++)
        if (spans[i][2] === spans[j][2]) assert.ok(spans[i][1] + 6 <= spans[j][0] || spans[j][1] + 6 <= spans[i][0], `labels ${i} and ${j} touch on row ${spans[i][2]}`);
  }
  assert.ok(labelRows([30, 211, 247, 283], ["the day", "04:50 sign-in", "05:00 daily", "06:45 watchdog"], ["start", "middle", "middle", "middle"], 6, 6).includes(2), "the crowded cluster uses the third row");
});
