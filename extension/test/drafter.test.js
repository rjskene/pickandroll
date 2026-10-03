// node --test extension/test/*.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { RoomTracker } = require("../lib/room.js");
const { Drafter, planWait } = require("../lib/drafter.js");

const SLOT = 1;
const K = 24; // my pick: round 2, slot 1

/** A virtual clock, a room at pick K on the clock, a scripted draft client and a plan. ``fail``:
 * how many /plan asks fail first (a 502); ``held``: the plan the page fetched ahead for pick K;
 * ``clockFrame``: false starts the turn before any D| frame; ``searchable``: rows Yahoo's
 * search box finds. */
function world({
  visible = ["101", "102", "103"],
  clicksToLand = 1,
  landMs = 300,
  plan = {},
  planMs = 2000,
  landInClick = false,
  fail = 0,
  held = null,
  clockFrame = true,
  searchable = [],
  dud = [], // rows whose clicks never land
  mislabeled = [], // rows whose Draft button names another player
} = {}) {
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
  if (clockFrame) tracker.ingest(`D|${K}|${SLOT}|30`, clock.t);
  const land = (yid, frames = []) => {
    for (const f of frames) tracker.ingest(f, clock.t);
    tracker.ingest(`0|${K}|${yid}|${SLOT}|X|0`, clock.t);
  };
  const log = { clicks: [], plans: [], boards: [], events: [], autodraft: [], queued: [], queued2: [], searches: [], cleared: 0, reset: 0 };
  let auto = false;
  const dom = {
    draftable: () => true,
    find: (c) => (visible.includes(c.yahoo_player_id) ? { yid: c.yahoo_player_id } : null),
    scrollTo: async () => null,
    async search(c) {
      log.searches.push(c.yahoo_player_id);
      return searchable.includes(c.yahoo_player_id) ? { yid: c.yahoo_player_id } : null;
    },
    click(row, c) {
      if (mislabeled.includes(c.yahoo_player_id)) return "mismatch";
      log.clicks.push([clock.t, c.yahoo_player_id]);
      if (dud.includes(c.yahoo_player_id)) return "clicked";
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
    async queueAlso(c2) {
      log.queued2.push(c2.yahoo_player_id);
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
    board: K - 1,
    waited_ms: 2000,
    candidates: ["101", "102", "103", "104"].map((y) => ({ yahoo_player_id: y, name: `P ${y}`, ini: "P", last: y, team: "T" })),
    ...(Array.isArray(plan) ? {} : plan),
  };
  const d = new Drafter({
    tracker,
    dom,
    plan: async (wait, board) => {
      log.plans.push(wait);
      log.boards.push(board);
      if (log.plans.length <= fail) {
        await sleep(20);
        throw Object.assign(new Error("Bad Gateway"), { status: 502 });
      }
      await sleep(wait ? planMs : 20);
      const next = Array.isArray(plan) ? plan[Math.min(log.plans.length, plan.length) - 1] : null;
      return next ? { ...served, ...next } : served;
    },
    held: (k) => (k === K ? held : null),
    emit: (e) => log.events.push(e),
    sleep,
    now: () => clock.t,
  });
  return { d, tracker, log, clock, at, land };
}

const attempts = (log) => log.events.filter((e) => e.type === "draft_attempt").map((e) => [e.yid, e.method, e.attempt]);
const rows = (ys) => ys.map((y) => ({ yahoo_player_id: y, name: `P ${y}`, ini: "P", last: y, team: "T" }));

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
  assert.deepEqual(log.boards, [K - 1]); // held for the solve of picks 1..K-1
  assert.deepEqual(attempts(log), [["101", "row", 1]]);
  assert.equal(log.events.find((e) => e.type === "draft_attempt").board, K - 1);
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
  assert.equal(log.queued2[0], "102"); // 25 is mine too: the next candidate behind (no plan.second)
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
  const { d, log } = world({
    planMs: 18000, // the API holds the whole wait
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

test("the previous board's plan is never drafted while this turn's can still come", async () => {
  // The sync of pick K-1 is a few ms behind the turn: the API calls board K-2's plan fresh.
  const { d, log } = world({
    plan: [
      { fresh: true, board: K - 2, waited_ms: 5, candidates: rows(["101", "102", "103"]) },
      { fresh: true, board: K - 1, candidates: rows(["102", "101", "103"]) },
    ],
  });
  const out = await d.turn(K);
  assert.equal(log.plans.length, 2);
  assert.deepEqual(log.boards, [K - 1, K - 1]);
  assert.equal(out.fresh, true);
  assert.equal(out.board, K - 1);
  assert.equal(out.yid, "102");
  assert.deepEqual(
    log.events.filter((e) => e.type === "draft_attempt").map((e) => [e.yid, e.board]),
    [["102", K - 1]],
  );
});

test("an API that only ever has the older board: asks end by 12 s left, the attempt says so", async () => {
  const { d, log, clock } = world({ plan: { fresh: true, board: K - 2, waited_ms: 5 } });
  const start = clock.t;
  const out = await d.turn(K);
  assert.equal(out.fresh, false);
  assert.equal(out.board, K - 2);
  assert.equal(out.yid, "101");
  assert.equal(log.plans.at(-1), 0); // the last look
  const attempt = log.events.find((e) => e.type === "draft_attempt");
  assert.equal(attempt.board, K - 2); // the scorecard labels this pick stale
  assert.ok(attempt.t - start <= 19000, `first attempt ${(attempt.t - start) / 1000} s into the turn`);
});

const notes = (log, what) => log.events.filter((e) => e.type === "note" && e.what === what);

test("a failed /plan is asked again: a 502, then the plan's top is drafted", async () => {
  const { d, log } = world({ fail: 1 });
  const out = await d.turn(K);
  assert.equal(out.result, "landed");
  assert.equal(out.yid, "101");
  assert.equal(out.fresh, true);
  assert.equal(log.plans.length, 2);
  assert.deepEqual(attempts(log), [["101", "row", 1]]);
  const [note] = notes(log, "plan errors");
  assert.equal(note.errors, 1);
  assert.equal(note.msg, "502 Bad Gateway");
  assert.equal(note.board, K - 1);
});

test("/plan failing the whole turn: the plan fetched ahead is acted on as stale, then the backstop", async () => {
  const ahead = { fresh: true, board: K - 3, waited_ms: 0, candidates: rows(["102", "101", "103"]) };
  const { d, log, clock } = world({ fail: Infinity, held: ahead, clicksToLand: 99 });
  const start = clock.t;
  const out = await d.turn(K);
  assert.ok(log.plans.length > 10, `asked ${log.plans.length} times`); // every 0.5 s until 12 s left
  assert.equal(out.board, K - 3);
  assert.equal(out.fresh, false);
  const first = log.events.find((e) => e.type === "draft_attempt");
  assert.equal(first.yid, "102");
  assert.equal(first.board, K - 3); // the scorecard labels this pick stale
  assert.ok(first.t - start <= 19000, `first attempt ${(first.t - start) / 1000} s into the turn`);
  assert.equal(log.queued[0], "102"); // the backstop, on the plan held
  assert.deepEqual(log.autodraft, [true, false]);
  assert.equal(out.result, "landed");
  assert.equal(notes(log, "plan errors")[0].board, K - 3);
});

test("/plan failing the whole turn with no plan held: no click, no throw, and the notes say so", async () => {
  const { d, log } = world({ fail: Infinity });
  const out = await d.turn(K);
  assert.equal(out.result, "none");
  assert.deepEqual(attempts(log), []);
  assert.deepEqual(log.autodraft, []);
  assert.equal(notes(log, "plan errors").length, 1);
  assert.equal(notes(log, "no candidates").length, 1);
  assert.equal(notes(log, "turn error").length, 0);
});

test("a plan held for this turn's board beats an older board's answer", async () => {
  const ahead = { fresh: true, board: K - 1, waited_ms: 0, candidates: rows(["103", "101", "102"]) };
  const { d, log, tracker } = world({ plan: { fresh: true, board: K - 2, waited_ms: 5 }, held: ahead });
  tracker.ingest("C|11", tracker.clock.at); // the wait is already over: one ask and the last look
  const out = await d.turn(K);
  assert.equal(out.fresh, true);
  assert.equal(out.board, K - 1);
  assert.equal(out.yid, "103");
  assert.deepEqual(log.plans, [0, 0]);
});

test("a turn started before any clock frame still row-clicks", async () => {
  const { d, log, tracker } = world({ clockFrame: false });
  assert.equal(tracker.clockLeft(Date.now()), null);
  const out = await d.turn(K);
  assert.equal(out.result, "landed");
  assert.deepEqual(attempts(log), [["101", "row", 1]]);
  assert.deepEqual(log.queued, []);
  assert.deepEqual(log.autodraft, []);
});

test("an off-screen row is never searched for unless the option is on", async () => {
  const off = world({ visible: [], searchable: ["101"] });
  const outOff = await off.d.turn(K);
  assert.deepEqual(off.log.searches, []);
  assert.deepEqual(attempts(off.log).filter(([, how]) => how !== "queue"), []);
  assert.equal(off.log.queued[0], "101"); // scroll found nothing: the backstop
  assert.equal(outOff.result, "landed");

  const on = world({ visible: [], searchable: ["101"] });
  on.d.searchFallback = true;
  const outOn = await on.d.turn(K);
  assert.deepEqual(on.log.searches, ["101"]);
  assert.deepEqual(attempts(on.log), [["101", "search", 1]]);
  assert.equal(outOn.result, "landed");
});

// ---------------------------------------------------------------- #10: "Draft in Yahoo"
const ask = (y, extra = {}) => ({ overall: K, board: K - 1, yahoo_player_id: y, name: `P ${y}`, ini: "P", last: y, team: "T", ...extra });

test("a request from the web app clicks its player on its turn; the pick is the user's (#10)", async () => {
  const { d, log, tracker } = world();
  const out = await d.request(ask("103"));
  assert.equal(out.result, "landed");
  assert.deepEqual(attempts(log), [["103", "request", 1]]);
  assert.equal(log.events.find((e) => e.type === "draft_attempt").board, K - 1);
  assert.equal(tracker.how(K), "manual");
  assert.equal(await d.request(ask("103")), null, "a request is served once");
  assert.equal(log.events.some((e) => e.what === "request failed"), false);
});

test("a request that lands nothing after two tries is dropped with a note", async () => {
  const { d, log } = world({ dud: ["103"] });
  const out = await d.request(ask("103"));
  assert.equal(out.result, "failed");
  assert.deepEqual(attempts(log), [["103", "request", 1], ["103", "request", 2]]);
  const note = log.events.find((e) => e.what === "request failed");
  assert.equal(note.overall, K);
  assert.equal(note.yid, "103");
  assert.equal(d.requesting, null);
});

test("a request clicks only while its pick is mine on the clock", async () => {
  const early = world({ clockFrame: false }); // the room has not put pick K on the clock yet
  assert.equal(await early.d.request(ask("103")), null);
  const later = world();
  assert.equal(await later.d.request(ask("103", { overall: K + 1 })), null, "my next pick, not this one");
  assert.deepEqual(early.log.clicks.concat(later.log.clicks), []);
});

test("a request keeps the row click's label guard", async () => {
  const { d, log } = world({ mislabeled: ["103"] });
  const out = await d.request(ask("103"));
  assert.equal(out.result, "failed");
  assert.deepEqual(log.clicks, [], "a Draft button naming another player is never clicked");
  assert.ok(log.events.find((e) => e.what === "request failed"));
});

test("armed: a pending request holds the turn, and its pick ends it", async () => {
  const { d, log } = world({ planMs: 200 });
  const turn = d.turn(K);
  const asked = d.request(ask("103"));
  const [out, req] = await Promise.all([turn, asked]);
  assert.equal(req.result, "landed");
  assert.equal(out.result, "landed");
  assert.equal(out.how, "manual");
  assert.deepEqual(attempts(log), [["103", "request", 1]], "the drafter clicked nothing");
  assert.deepEqual(log.queued, []);
});

test("armed: after a failed request the turn goes on as usual", async () => {
  const { d, log } = world({ planMs: 200, dud: ["103"] });
  const turn = d.turn(K);
  const asked = d.request(ask("103"));
  const [out, req] = await Promise.all([turn, asked]);
  assert.equal(req.result, "failed");
  assert.equal(out.result, "landed");
  assert.equal(out.yid, "101");
  assert.deepEqual(attempts(log), [["103", "request", 1], ["103", "request", 2], ["101", "row", 1]]);
});

test("armed: a request arriving mid-turn takes over before the drafter's next click", async () => {
  const { d, log, at } = world({ dud: ["101"], planMs: 200 });
  // The drafter clicks 101 (a dud) and waits to re-click it; the user's request comes meanwhile.
  let asked = null;
  at(1200, () => {
    asked = d.request(ask("103"));
  });
  const out = await d.turn(K);
  const req = await asked;
  assert.equal(req.result, "landed");
  assert.equal(out.yid, "103");
  assert.deepEqual(attempts(log), [["101", "row", 1], ["103", "request", 1]]);
});

test("a hand pick in Yahoo stops a pending request", async () => {
  const { d, log, tracker, land, at } = world({ dud: ["103"] });
  at(1000, () => {
    tracker.noteManual(Date.now(), "Draft Q 105");
    d.handPick(K);
    land("105");
  });
  const req = await d.request(ask("103"));
  assert.equal(req.result, "manual");
  assert.equal(log.events.some((e) => e.what === "request failed"), false);
});
