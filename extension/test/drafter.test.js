// node --test extension/test/*.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { RoomTracker } = require("../lib/room.js");
const { Drafter, planWait } = require("../lib/drafter.js");

const SLOT = 1;
const K = 24; // my pick: round 2, slot 1

/** A virtual clock, a room at pick K on the clock, a scripted draft client and a plan. */
function world({ visible = ["101", "102", "103"], clicksToLand = 1, landMs = 300, plan = {}, planMs = 2000, landInClick = false } = {}) {
  const clock = { t: 1_000_000 };
  const queue = [];
  const run = () => {
    queue.sort((x, y) => x[0] - y[0]);
    while (queue.length && queue[0][0] <= clock.t) queue.shift()[1]();
  };
  const at = (ms, fn) => queue.push([clock.t + ms, fn]);
  const sleep = async (ms) => {
    clock.t += ms;
    run();
    await null;
  };
  const tracker = new RoomTracker({ draftId: "d", slot: SLOT });
  for (let k = 1; k < K; k++) tracker.ingest(`0|${k}|${900 + k}|${k <= 12 ? k : 25 - k}|X|0`, clock.t - 5000);
  tracker.ingest(`D|${K}|${SLOT}|30`, clock.t);
  const land = (yid, frames = []) => {
    for (const f of frames) tracker.ingest(f, clock.t);
    tracker.ingest(`0|${K}|${yid}|${SLOT}|X|0`, clock.t);
  };
  const log = { clicks: [], plans: [], events: [], autodraft: [], queued: [], cleared: 0, reset: 0 };
  let auto = false;
  const dom = {
    draftable: () => true,
    find: (c) => (visible.includes(c.yahoo_player_id) ? { yid: c.yahoo_player_id } : null),
    scrollTo: async () => null,
    search: async () => null,
    click(row, c) {
      log.clicks.push([clock.t, c.yahoo_player_id]);
      const mine = log.clicks.filter((x) => x[1] === c.yahoo_player_id).length;
      if (mine === clicksToLand && landInClick) {
        land(c.yahoo_player_id); // the room answers before the click returns
        log.howAtLand = tracker.how(K, { autodraft: auto });
      } else if (mine === clicksToLand) at(landMs, () => !tracker.picks.has(K) && land(c.yahoo_player_id));
      return "clicked";
    },
    nudge: async () => {},
    async queueOnly(c) {
      log.queued.push(c.yahoo_player_id);
      return { ok: true };
    },
    async setAutodraft(on) {
      log.autodraft.push(on);
      auto = on;
      if (on) at(500, () => !tracker.picks.has(K) && land(log.queued.at(-1), ["X|29", `5|${SLOT}`]));
      return on;
    },
    autodraftOn: () => auto,
    async clearQueue() {
      log.cleared++;
    },
    async reset() {
      log.reset++;
    },
  };
  const served = {
    fresh: true,
    waited_ms: 2000,
    candidates: ["101", "102", "103", "104"].map((y) => ({ yahoo_player_id: y, name: `P ${y}`, ini: "P", last: y, team: "T" })),
    ...(Array.isArray(plan) ? {} : plan),
  };
  const d = new Drafter({
    tracker,
    dom,
    plan: async (wait) => {
      log.plans.push(wait);
      await sleep(wait ? planMs : 20);
      const next = Array.isArray(plan) ? plan[Math.min(log.plans.length, plan.length) - 1] : null;
      return next ? { ...served, ...next } : served;
    },
    emit: (e) => log.events.push(e),
    sleep,
    now: () => clock.t,
  });
  return { d, tracker, log, clock, at, land };
}

const attempts = (log) => log.events.filter((e) => e.type === "draft_attempt").map((e) => [e.yid, e.method, e.attempt]);

test("plan wait: hold up to 20 s, never past 12 s left", () => {
  assert.equal(planWait(30), 18);
  assert.equal(planWait(40), 20);
  assert.equal(planWait(15.5), 3);
  assert.equal(planWait(10), 0);
  assert.equal(planWait(null), 20);
});

test("the first click lands: one attempt, how row, Autodraft untouched", async () => {
  const { d, log, tracker } = world();
  const out = await d.turn(K);
  assert.equal(out.result, "landed");
  assert.equal(out.yid, "101");
  assert.equal(out.how, "row");
  assert.deepEqual(log.plans, [18]);
  assert.deepEqual(attempts(log), [["101", "row", 1]]);
  assert.deepEqual(log.autodraft, []);
  assert.equal(tracker.how(K), "row");
  assert.equal(await d.turn(K), null); // a turn is taken once
});

test("a pick that lands while the click settles is still the extension's row pick", async () => {
  const { d, log } = world({ landInClick: true });
  const out = await d.turn(K);
  assert.equal(out.result, "landed");
  assert.equal(log.howAtLand, "row"); // what content.js posts in pick_landed at that moment
});

test("a click lost to a re-render is repeated on the same row at 1.8 s", async () => {
  const { d, log } = world({ clicksToLand: 2 });
  const out = await d.turn(K);
  assert.equal(out.yid, "101");
  assert.deepEqual(attempts(log), [["101", "row", 1], ["101", "row", 2]]);
  const [first, second] = log.clicks.map((c) => c[0]);
  assert.ok(second - first >= 1800 && second - first < 2100, `re-click after ${second - first} ms`);
});

test("taken and row-less candidates are skipped", async () => {
  const { d, log, tracker } = world({ visible: ["103"] });
  tracker.add(K - 1, "101", 2, 0, "socket"); // 101 went just before my turn
  const out = await d.turn(K);
  assert.equal(out.yid, "103");
  assert.deepEqual(attempts(log), [["103", "row", 1]]);
});

test("clicks that never register: the queue backstop by 6 s left, then Autodraft off", async () => {
  const { d, log, clock } = world({ clicksToLand: 99, planMs: 9000 });
  const start = clock.t;
  const out = await d.turn(K);
  assert.equal(out.result, "landed");
  assert.equal(log.queued[0], "101");
  assert.deepEqual(log.autodraft, [true, false]);
  assert.ok(log.cleared >= 1);
  assert.equal(out.how, "autopick"); // Yahoo announced it (5|slot) with Autodraft on
  const queuedAt = log.events.find((e) => e.method === "queue").t;
  assert.ok(queuedAt - start <= 24000, `queue set ${(queuedAt - start) / 1000} s into the turn`);
});

test("a hand pick during the plan wait: no attempt, and the page is left alone", async () => {
  const { d, log, tracker, at } = world({ planMs: 4000 });
  at(1000, () => tracker.noteManual(1_001_000, "Draft"));
  const out = await d.turn(K);
  assert.equal(out.result, "manual");
  assert.deepEqual(attempts(log), []);
  assert.equal(log.reset, 0);
  assert.deepEqual(log.autodraft, []);
});

test("a stale plan near the end of the clock is drafted, not waited on", async () => {
  const { d, log, tracker, clock } = world({ plan: { fresh: false } });
  tracker.ingest("C|11", clock.t);
  const out = await d.turn(K);
  assert.deepEqual(log.plans, [0, 0]); // the wait, then one last look
  assert.equal(out.fresh, false);
  assert.equal(out.yid, "101");
});

test("a fresh plan that lands just after the wait is the one drafted", async () => {
  const top = (y) => ["101", "102", "103"].sort((a, b) => (a === y ? -1 : b === y ? 1 : 0));
  const rows = (ys) => ys.map((y) => ({ yahoo_player_id: y, name: `P ${y}`, ini: "P", last: y, team: "T" }));
  const { d, log } = world({
    plan: [
      { fresh: false, candidates: rows(top("101")) },
      { fresh: true, candidates: rows(top("102")) },
    ],
  });
  const out = await d.turn(K);
  assert.deepEqual(log.plans, [18, 0]);
  assert.equal(out.fresh, true);
  assert.equal(out.yid, "102");
});
