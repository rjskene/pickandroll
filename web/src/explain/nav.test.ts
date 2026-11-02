import assert from "node:assert/strict";
import { test } from "node:test";
import { HOME, formatHash, hasIntro, move, nextLabel, parseHash, plannedSteps, stepCount, stepNumber } from "./nav.ts";
import type { Track } from "./types";

// A track of `n` steps; with `intro`, the first is its overview and the rest number from one.
const t = (id: Track["id"], title: string, n: number, intro = false): Track => ({
  id,
  title,
  short: title,
  lede: "",
  labels: Array.from({ length: n }, (_, i) => (intro && i === 0 ? "Overview" : String(i))),
  steps: Array.from({ length: n }, (_, i) => ({
    id: `s${i}`,
    title: "T",
    kicker: "k",
    figure: "export-row" as const,
    bullets: [{ text: "x" }],
    source: [],
    ...(intro && i === 0 ? { intro: true } : {}),
  })),
});
const tracks = [t("draft", "Draft", 10, true), t("moves", "Moves & trades", 5, true), t("daily", "Daily play", 9)];
const [draft, moves, daily] = tracks;

test("the hash carries the number the step shows: the overview 0, the steps from one", () => {
  assert.deepEqual(parseHash("#draft/3", tracks), { track: "draft", step: 3 });
  assert.deepEqual(parseHash("#draft/0", tracks), { track: "draft", step: 0 });
  assert.deepEqual(parseHash("moves/1", tracks), { track: "moves", step: 1 });
  assert.equal(formatHash({ track: "moves", step: 3 }, tracks), "#moves/3");
  assert.equal(formatHash({ track: "draft", step: 0 }, tracks), "#draft/0");
  for (const p of [{ track: "draft", step: 9 }, { track: "moves", step: 0 }, { track: "daily", step: 8 }] as const)
    assert.deepEqual(parseHash(formatHash(p, tracks), tracks), p);
});

test("a track without an overview still counts its steps from one", () => {
  assert.deepEqual(parseHash("#daily/1", tracks), { track: "daily", step: 0 });
  assert.deepEqual(parseHash("#daily/0", tracks), { track: "daily", step: 0 });
  assert.equal(formatHash({ track: "daily", step: 3 }, tracks), "#daily/4");
});

test("a track named alone opens on its overview; a hash off the map lands on the first step or the nearest", () => {
  assert.deepEqual(parseHash("#daily", tracks), { track: "daily", step: 0 });
  assert.deepEqual(parseHash("#draft", tracks), { track: "draft", step: 0 });
  assert.deepEqual(parseHash("", tracks), HOME);
  assert.deepEqual(parseHash("#nope/2", tracks), HOME);
  assert.deepEqual(parseHash("#moves/40", tracks), { track: "moves", step: 4 });
  assert.deepEqual(parseHash("#draft/x", tracks), HOME);
});

test("the arrows walk into a track's overview, from either side", () => {
  assert.deepEqual(move({ track: "draft", step: 9 }, 1, tracks), { track: "moves", step: 0 });
  assert.deepEqual(move({ track: "moves", step: 1 }, -1, tracks), { track: "moves", step: 0 });
  assert.deepEqual(move({ track: "moves", step: 0 }, -1, tracks), { track: "draft", step: 9 });
  assert.deepEqual(move({ track: "draft", step: 0 }, -1, tracks), { track: "draft", step: 0 });
  assert.deepEqual(move({ track: "draft", step: 0 }, 1, tracks), { track: "draft", step: 1 });
  assert.deepEqual(move({ track: "moves", step: 4 }, 1, tracks), { track: "daily", step: 0 });
  assert.deepEqual(move({ track: "daily", step: 8 }, 1, tracks), { track: "daily", step: 8 });
});

test("the Next button names the next track on a last step", () => {
  assert.equal(nextLabel({ track: "draft", step: 0 }, tracks), "Next →");
  assert.equal(nextLabel({ track: "draft", step: 9 }, tracks), "Next: Moves & trades →");
  assert.equal(nextLabel({ track: "daily", step: 8 }, tracks), "Done");
});

test("the count reads Overview on the overview, and n of N over the numbered steps", () => {
  assert.ok(hasIntro(draft) && hasIntro(moves) && !hasIntro(daily));
  assert.equal(plannedSteps(draft), 9);
  assert.equal(plannedSteps(daily), 9);
  assert.equal(stepCount(draft, 0), "Overview");
  assert.equal(stepCount(draft, 1), "1 of 9");
  assert.equal(stepCount(moves, 4), "4 of 4");
  assert.equal(stepCount(daily, 0), "1 of 9");
  assert.deepEqual([stepNumber(draft, 2), stepNumber(daily, 2)], [2, 3]);
});
