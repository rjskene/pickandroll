import assert from "node:assert/strict";
import { test } from "node:test";
import { HOME, formatHash, move, nextLabel, parseHash } from "./nav.ts";
import type { Track } from "./types";

const t = (id: Track["id"], title: string, n: number): Track => ({
  id,
  title,
  lede: "",
  labels: Array.from({ length: n }, (_, i) => String(i)),
  steps: Array.from({ length: n }, (_, i) => ({ id: `s${i}`, title: "T", kicker: "k", figure: "export-row" as const, bullets: [{ text: "x" }], source: [] })),
});
const tracks = [t("draft", "Draft", 9), t("moves", "Moves & trades", 4), t("daily", "Daily play", 9)];

test("the hash names the track and the step from one", () => {
  assert.deepEqual(parseHash("#draft/3", tracks), { track: "draft", step: 2 });
  assert.deepEqual(parseHash("moves/1", tracks), { track: "moves", step: 0 });
  assert.deepEqual(parseHash("#daily", tracks), { track: "daily", step: 0 });
  assert.equal(formatHash({ track: "moves", step: 3 }), "#moves/4");
  assert.deepEqual(parseHash(formatHash({ track: "daily", step: 8 }), tracks), { track: "daily", step: 8 });
});

test("a hash off the map lands on the first step or the nearest", () => {
  assert.deepEqual(parseHash("", tracks), HOME);
  assert.deepEqual(parseHash("#nope/2", tracks), HOME);
  assert.deepEqual(parseHash("#draft/0", tracks), { track: "draft", step: 0 });
  assert.deepEqual(parseHash("#moves/40", tracks), { track: "moves", step: 3 });
  assert.deepEqual(parseHash("#draft/x", tracks), HOME);
});

test("next past a track's last step opens the next track; prev before its first goes back", () => {
  assert.deepEqual(move({ track: "draft", step: 8 }, 1, tracks), { track: "moves", step: 0 });
  assert.deepEqual(move({ track: "moves", step: 0 }, -1, tracks), { track: "draft", step: 8 });
  assert.deepEqual(move({ track: "draft", step: 0 }, -1, tracks), { track: "draft", step: 0 });
  assert.deepEqual(move({ track: "daily", step: 8 }, 1, tracks), { track: "daily", step: 8 });
  assert.deepEqual(move({ track: "moves", step: 1 }, 1, tracks), { track: "moves", step: 2 });
});

test("the Next button names the next track on a last step", () => {
  assert.equal(nextLabel({ track: "draft", step: 0 }, tracks), "Next →");
  assert.equal(nextLabel({ track: "draft", step: 8 }, tracks), "Next: Moves & trades →");
  assert.equal(nextLabel({ track: "daily", step: 8 }, tracks), "Done");
});
