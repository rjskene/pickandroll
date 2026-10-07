// node --test extension/test/*.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { RoomTracker } = require("../lib/room.js");
const { Drafter, planWait, BACKSTOP_BY_S } = require("../lib/drafter.js");

const SLOT = 1;
const K = 24; // my pick: round 2, slot 1

/** A virtual clock, a room at pick K on the clock, a scripted draft client and a plan. ``fail``:
 * how many /plan asks fail first (a 502); ``held``: the plan the page fetched ahead for pick K;
 * ``clockFrame``: false starts the turn before any D| frame, ``clock``: null sends pick K's D|
 * frame without its clock; ``searchable``: rows Yahoo's search box finds; ``settleMs``: a click
 * returns that long after it registers (Yahoo's ~400 ms); ``backToBack``: pick K+1 is mine too
 * and goes on the clock the moment K lands (slots 1 and 12); ``draftableAfter``: the table shows
 * no Draft buttons until that many ms into the turn (a click on a row then finds none);
 * ``planHang``: a held /plan ask never answers (the solve outlives the turn); ``unqueueable``:
 * rows the queue cannot take; ``switchMs``: the Autodraft switch returns that long after it is
 * thrown, and Yahoo picks from the queue ``autoLandMs`` after it is; ``starDrafts``: on my turn
 * a row's star drafts its player (the harness's table, and the probe's "drafted"). */
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
  clock: clockValue = 30,
  searchable = [],
  settleMs = 0,
  backToBack = false,
  draftableAfter = 0,
  planHang = false,
  dud = [], // rows whose clicks never land
  mislabeled = [], // rows whose Draft button names another player
  unqueueable = [],
  switchMs = 0,
  autoLandMs = 500,
  starDrafts = false,
} = {}) {
  const clock = { t: 1_000_000 };
  const draftable = () => clock.t >= 1_000_000 + draftableAfter;
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
  if (clockFrame) tracker.ingest(`D|${K}|${SLOT}${clockValue === null ? "" : `|${clockValue}`}`, clock.t);
  const land = (yid, frames = []) => {
    for (const f of frames) tracker.ingest(f, clock.t);
    tracker.ingest(`0|${K}|${yid}|${SLOT}|X|0`, clock.t);
    if (backToBack) tracker.ingest(`D|${K + 1}|${SLOT}|30`, clock.t);
  };
  const log = { clicks: [], plans: [], boards: [], events: [], autodraft: [], queued: [], queued2: [], searches: [], cleared: 0, reset: 0 };
  let auto = false;
  const dom = {
    draftable,
    find: (c) => (visible.includes(c.yahoo_player_id) ? { yid: c.yahoo_player_id } : null),
    scrollTo: async () => null,
    async search(c) {
      log.searches.push(c.yahoo_player_id);
      return searchable.includes(c.yahoo_player_id) ? { yid: c.yahoo_player_id } : null;
    },
    async click(row, c) {
      if (!draftable()) return "none";
      if (mislabeled.includes(c.yahoo_player_id)) return "mismatch";
      log.clicks.push([clock.t, c.yahoo_player_id, tracker.myTurnNow()]);
      if (dud.includes(c.yahoo_player_id)) return "clicked";
      const mine = log.clicks.filter((x) => x[1] === c.yahoo_player_id).length;
      if (mine === clicksToLand && landInClick) {
        land(c.yahoo_player_id); // the room answers before the click returns
        log.howAtLand = tracker.how(K, { autodraft: auto });
      } else if (mine === clicksToLand) {
        at(landMs, () => {
          if (tracker.picks.has(K)) return;
          land(c.yahoo_player_id);
          log.howAtLand = tracker.how(K, { autodraft: auto }); // what pick_landed would say
        });
      }
      if (settleMs) await sleep(settleMs);
      return "clicked";
    },
    nudge: async () => {},
    async queueOnly(c) {
      if (unqueueable.includes(c.yahoo_player_id)) return { ok: false, msg: "no row" };
      log.queued.push(c.yahoo_player_id);
      if (starDrafts && !tracker.picks.has(K)) land(c.yahoo_player_id);
      return { ok: true };
    },
    async queueAlso(c2) {
      log.queued2.push(c2.yahoo_player_id);
      return { ok: true };
    },
    async setAutodraft(on) {
      log.autodraft.push(on);
      auto = on;
      if (on) at(autoLandMs, () => !tracker.picks.has(K) && land(log.queued.at(-1), ["X|29", `5|${SLOT}`]));
      if (switchMs) await sleep(switchMs);
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
      if (planHang && wait) return new Promise(() => {});
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

const ticks = async (n) => {
  for (let i = 0; i < n; i++) await null;
};
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

test("the backstop's attempts are stamped as the switch is thrown, before Yahoo picks (#26)", async () => {
  // Yahoo picks 100 ms after the switch is thrown; the switch returns 400 ms after it is.
  const { d, log, tracker } = world({ clicksToLand: 99, planMs: 9000, switchMs: 400, autoLandMs: 100 });
  await d.turn(K);
  const queued = log.events.filter((e) => e.method === "queue");
  assert.deepEqual(queued.map((e) => [e.overall, e.yid]), [[K, "101"], [K + 1, "102"]]);
  assert.ok(queued.every((e) => e.t < tracker.picks.get(K).t), "logged before the pick it made");
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

test("a turn with no clock from the room still row-clicks", async () => {
  const { d, log, tracker } = world({ clock: null });
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

test("a request's attempt is stamped when its click is made, not when it settles (#26)", async () => {
  const { d, log } = world({ settleMs: 400 });
  await d.request(ask("103"));
  const [click] = log.clicks;
  const attempt = log.events.find((e) => e.type === "draft_attempt");
  assert.equal(attempt.method, "request");
  assert.equal(attempt.t, click[0]);
});

test("a row's attempts are stamped when each click is made, not when it settles (#26)", async () => {
  // A reco can land while a click settles; the scorecard judges the pick by the reco before
  // its first attempt, so the attempt carries the click's own time.
  const { d, log } = world({ settleMs: 400, clicksToLand: 2 });
  const out = await d.turn(K);
  assert.equal(out.result, "landed");
  const stamps = log.events.filter((e) => e.type === "draft_attempt").map((e) => [e.method, e.attempt, e.t]);
  assert.equal(log.clicks.length, 2);
  assert.deepEqual(stamps, log.clicks.map(([t], i) => ["row", i + 1, t]));
});

/** An armed turn whose clicks never land, with the user's request for 103 coming at 9 s left:
 * both its clicks are lost (#26). Pick 25 is mine too unless ``single`` (then a keeper's). */
async function lostRequest({ single = false, ...opts } = {}) {
  const w = world({ clicksToLand: 99, planMs: 9000, dud: ["103"], ...opts });
  if (single) w.tracker.configure({ keepers: [{ overall: K + 1 }] });
  let asked = null;
  w.at(21000, () => {
    asked = w.d.request(ask("103", { id: "r7" }));
  });
  const out = await w.d.turn(K);
  return { ...w, out, req: await asked };
}

test("armed: after a lost request click the backstop queues the requested player first (#26)", async () => {
  const { out, req, log, tracker } = await lostRequest({ single: true });
  assert.equal(req.result, "failed");
  assert.equal(req.attempts, 2);
  assert.deepEqual(log.queued, ["103"], "the requested player alone, then");
  assert.deepEqual(log.queued2, ["101"], "the plan's top second");
  assert.equal(out.yid, "103");
  assert.equal(out.how, "manual", "the user's pick, as a request that lands");
  assert.equal(tracker.how(K, { autodraft: true }), "manual");
  const queued = log.events.filter((e) => e.method === "queue").map((e) => [e.overall, e.yid, e.attempt]);
  assert.deepEqual(queued, [[K, "103", 1], [K, "101", 2]], "the attempt log names both");
  const note = log.events.find((e) => e.what === "backstop landed the request");
  assert.deepEqual([note.overall, note.yid, note.request_id], [K, "103", "r7"]);
  assert.deepEqual(log.autodraft, [true, false]);
});

test("armed, back to back: the requested player for this pick, the plan's top for the next (#26)", async () => {
  const { out, log } = await lostRequest({ backToBack: true, plan: { second_pick: K + 1, second: rows(["104"]) } });
  assert.equal(out.yid, "103");
  assert.deepEqual(log.queued, ["103"]);
  assert.deepEqual(log.queued2, ["101"], "no third entry: Yahoo's next autopick takes 101");
  const queued = log.events.filter((e) => e.method === "queue").map((e) => [e.overall, e.yid, e.attempt]);
  assert.deepEqual(queued, [[K, "103", 1], [K, "101", 2], [K + 1, "101", 1]]);
});

test("armed: a requested player the queue cannot take leaves the usual backstop, with a note (#26)", async () => {
  const { out, log } = await lostRequest({ backToBack: true, unqueueable: ["103"] });
  const note = log.events.find((e) => e.what === "queue backstop: requested player failed");
  assert.deepEqual([note.overall, note.yid, note.msg], [K, "103", "no row"]);
  assert.deepEqual(log.queued, ["101"]);
  assert.deepEqual(log.queued2, ["102"], "the plan's player for my next pick, as before");
  assert.equal(out.yid, "101");
  assert.equal(out.how, "autopick");
  assert.equal(log.events.some((e) => e.what === "backstop landed the request"), false);
});

test("armed: a star that drafts the requested player ends the backstop there (#26)", async () => {
  const { out, log } = await lostRequest({ starDrafts: true });
  assert.equal(out.yid, "103");
  assert.equal(out.how, "manual");
  assert.deepEqual(log.queued, ["103"]);
  assert.deepEqual(log.queued2, [], "nothing behind a pick that is in");
  assert.deepEqual(log.autodraft, [], "and no Autodraft switch");
  const queued = log.events.filter((e) => e.method === "queue").map((e) => [e.overall, e.yid, e.attempt]);
  assert.deepEqual(queued, [[K, "103", 1]]);
  assert.ok(log.events.find((e) => e.what === "backstop landed the request"));
  assert.equal(log.events.some((e) => /queue backstop/.test(e.what || "")), false, "no failure note");
});

test("a request that failed on an earlier pick leaves this pick's backstop alone (#26)", async () => {
  const { d, log } = world({ clicksToLand: 99, planMs: 9000 });
  d.failed = { k: K - 12, c: ask("103", { overall: K - 12 }), id: "r1" };
  const out = await d.turn(K);
  assert.deepEqual(log.queued, ["101"]);
  assert.equal(out.yid, "101");
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

// ---------------------------------------------------------------- #10: act_at_s
const T0 = 1_000_000; // the world's clock at the turn frame (30 s on the clock)
const rowClicks = (log) => log.clicks.map(([t, y]) => [t - T0, y]);

test("plan wait with act_at_s: it stops at act time", () => {
  assert.equal(planWait(30, 20), 10);
  assert.equal(planWait(30, 12), 18);
  assert.equal(planWait(18, 20), 0);
});

test("act_at_s: the click waits for its time, then the plan is looked at once more", async () => {
  // The second look finds a re-solve on the same board that puts 102 first.
  const { d, log } = world({ plan: [{}, { candidates: rows(["102", "101"]) }] });
  d.actAt = 20;
  const out = await d.turn(K);
  assert.deepEqual(log.plans, [10, 0], "the plan wait stops at act time; the last look waits for nothing");
  assert.deepEqual(log.boards, [K - 1, K - 1]);
  const [[t, yid]] = rowClicks(log);
  assert.equal(yid, "102");
  assert.ok(t >= 10000 && t < 11000, `clicked ${t / 1000} s into the turn`);
  assert.equal(out.result, "landed");
  assert.equal(out.act_at_s, 20);
  assert.ok(out.held_ms >= 7000, `held ${out.held_ms} ms after the plan came`);
});

test("act_at_s: a plan still stale at act time is acted on then, not waited on to 12 s", async () => {
  const { d, log } = world({ plan: { fresh: false } });
  d.actAt = 20;
  const out = await d.turn(K);
  assert.equal(out.fresh, false);
  const [[t]] = rowClicks(log);
  // The world's stale answer takes 2 s whatever the wait: the last ask can run past act time.
  assert.ok(t >= 10000 && t < 12500, `clicked ${t / 1000} s into the turn, not 18 s`);
  assert.equal(log.plans.at(-1), 0, "one last look when the wait is up");
});

test("act_at_s: a hand pick while the click waits ends the turn", async () => {
  const { d, log, tracker, at } = world();
  d.actAt = 20;
  at(5000, () => tracker.noteManual(T0 + 5000, "Draft"));
  const out = await d.turn(K);
  assert.equal(out.result, "manual");
  assert.deepEqual(attempts(log), []);
  assert.deepEqual(log.plans, [10], "no last look");
  assert.deepEqual(log.autodraft, []);
});

test("act_at_s: a request landing while the click waits ends the turn", async () => {
  const { d, log, at } = world();
  d.actAt = 20;
  let asked = null;
  at(4000, () => {
    asked = d.request(ask("103"));
  });
  const out = await d.turn(K);
  assert.equal((await asked).result, "landed");
  assert.equal(out.yid, "103");
  assert.equal(out.how, "manual");
  assert.deepEqual(attempts(log), [["103", "request", 1]], "the drafter clicked nothing");
});

test("act_at_s: after a failed request the turn still acts at its time", async () => {
  const { d, log, at } = world({ dud: ["103"] });
  d.actAt = 20;
  let asked = null;
  at(3000, () => {
    asked = d.request(ask("103"));
  });
  const out = await d.turn(K);
  assert.equal((await asked).result, "failed");
  assert.equal(out.yid, "101");
  assert.deepEqual(attempts(log), [["103", "request", 1], ["103", "request", 2], ["101", "row", 1]]);
  const t = rowClicks(log).find(([, y]) => y === "101")[0];
  assert.ok(t >= 10000 && t < 11000, `clicked ${t / 1000} s into the turn`);
});

test("act_at_s with no clock from the room: nothing to count down, the turn acts at once", async () => {
  const { d, log } = world({ clock: null });
  d.actAt = 20;
  const out = await d.turn(K);
  assert.equal(out.result, "landed");
  assert.equal(out.held_ms, 0);
  assert.equal(log.plans.length, 1);
});

// ---------------------------------------------------------------- #10 review: queued clicks
test("armed back to back: a request while the drafter's click settles never drafts the next pick", async () => {
  // Slot 1, pick 24 on the clock and 25 mine too. The drafter clicks 101 at 200 ms; Yahoo takes
  // it at 500 ms while the click settles (to 600 ms); the user's request for 103 comes at 250 ms
  // and its click queues behind the drafter's.
  const { d, log, tracker, at } = world({ planMs: 200, settleMs: 400, backToBack: true });
  let asked = null;
  at(250, () => {
    asked = d.request(ask("103"));
  });
  const out = await d.turn(K);
  const req = await asked;
  assert.equal(out.yid, "101");
  assert.equal(log.howAtLand, "row", "pick_landed says the drafter took 24");
  assert.equal(tracker.how(K), "row");
  const for24 = log.events.filter((e) => e.type === "draft_attempt" && e.overall === K);
  assert.deepEqual(for24.map((e) => [e.yid, e.method]), [["101", "row"]]);
  assert.deepEqual(log.clicks.map(([, y, on]) => [y, on]), [["101", K]], "no click on 25's frame");
  assert.equal(tracker.myTurnNow(), K + 1);
  assert.equal(req.result, "other");
  assert.equal(req.attempts, 0);
  assert.equal(log.events.some((e) => e.what === "request failed"), false);
});

test("a turn superseded while its click waits for the page clicks nothing", async () => {
  // An older action holds the page (a click still settling) when the turn comes to click 101;
  // a newer turn supersedes this one before the page is free.
  const { d, log, tracker } = world({ planMs: 200 });
  let free;
  d.page(() => new Promise((resolve) => (free = resolve)));
  const turn = d.turn(K);
  for (let i = 0; i < 200; i++) await null; // the turn reaches its click and queues it
  assert.equal(log.clicks.length, 0);
  d.current.stop("superseded");
  free();
  const out = await turn;
  assert.equal(out.result, "superseded");
  assert.deepEqual(log.clicks, [], "the queued click is a no-op");
  assert.equal(tracker.attempts.has(K), false, "and notes no attempt");
});

// ---------------------------------------------------------------- #20
test("a request at the turn's frame waits for the Draft buttons, as a row draft does", async () => {
  const { d, log } = world({ draftableAfter: 600 });
  const out = await d.request(ask("103"));
  assert.equal(out.result, "landed");
  assert.deepEqual(attempts(log), [["103", "request", 1]], "the first try is not spent on a bare row");
  const [[t]] = log.clicks;
  assert.ok(t - 1_000_000 >= 600 && t - 1_000_000 < 1000, `clicked at ${t - 1_000_000} ms`);
});

test("each request is its own: the same player asked again after a failed request is served", async () => {
  const { d, log } = world({ clicksToLand: 3 }); // the first request's two clicks land nothing
  // By time, as an API before #22 names its requests (the id where there is one, below).
  const first = await d.request(ask("103", { t: "t1" }));
  assert.equal(first.result, "failed");
  assert.equal(await d.request(ask("103", { t: "t1" })), null, "the same request is served once");
  const again = d.request(ask("103", { t: "t2" })); // the user asks for 103 again
  assert.equal(d.yields(K), true, "an armed turn stands aside for it");
  assert.equal((await again).result, "landed");
  assert.deepEqual(attempts(log), [["103", "request", 1], ["103", "request", 2], ["103", "request", 1]]);
});

test("a request replaced by the user stops before its next try, with no failure note", async () => {
  const { d, log, at } = world({ dud: ["103"] });
  at(1000, () => d.requesting.ctx.stop("replaced")); // the tab read the user's newer request
  const first = await d.request(ask("103"));
  assert.equal(first.result, "stopped");
  assert.equal(first.attempts, 1);
  assert.equal(log.events.some((e) => e.what === "request failed"), false);
  const second = await d.request(ask("102"));
  assert.equal(second.result, "landed");
  assert.deepEqual(attempts(log), [["103", "request", 1], ["102", "request", 1]]);
});

// ---------------------------------------------------------------- #22
test("a request's wait for the Draft buttons ends at the backstop line", async () => {
  const { d } = world({ clock: 7, draftableAfter: 60_000 }); // 7 s left, no buttons yet
  const lefts = []; // seconds left at each try's look for the row, right after its wait
  const find = d.dom.find;
  d.dom.find = (c) => {
    lefts.push(d.left());
    return find(c);
  };
  const out = await d.request(ask("103"));
  assert.equal(out.result, "failed");
  // The first try waits down to the line (6 s left, in 250 ms steps) and no further; the
  // second, already past it, does not wait at all.
  assert.equal(lefts.length, 2);
  assert.ok(lefts[0] > BACKSTOP_BY_S - 0.25 && lefts[0] <= BACKSTOP_BY_S, `first look at ${lefts[0]} s left`);
  assert.ok(lefts[1] < lefts[0], `second look at ${lefts[1]} s left`);
});

test("a late request leaves the armed turn that stood aside its backstop: no second try", async () => {
  const { d, log } = world({ clock: 7, draftableAfter: 60_000 }); // 7 s left, no buttons yet
  let at = null; // seconds left when the backstop switched Autodraft on
  const set = d.dom.setAutodraft;
  d.dom.setAutodraft = async (on) => {
    if (on && at === null) at = d.left();
    return set(on);
  };
  const looks = [];
  const find = d.dom.find;
  d.dom.find = (c) => {
    looks.push(c.yahoo_player_id);
    return find(c);
  };
  const req = d.request(ask("103", { id: "r1" }));
  const turn = d.turn(K); // armed: stands aside while the request is pending
  assert.equal((await req).result, "failed");
  const out = await turn;
  assert.deepEqual(looks, ["103"], "one try: a second would cross the backstop line");
  // The request's wait ends at 6 s left and its one try takes a confirmation (800 ms).
  assert.ok(at !== null && at >= BACKSTOP_BY_S - 1, `backstop at ${at} s left`);
  assert.equal(out.result, "landed");
  assert.deepEqual(log.autodraft, [true, false]);
});

test("a request's wait for the Draft buttons ends when the pick is in", async () => {
  const { d, clock, at, land } = world({ draftableAfter: 60_000 }); // no buttons all turn
  const t0 = clock.t;
  at(300, () => land("999")); // the pick lands by other means
  const out = await d.request(ask("103"));
  assert.equal(out.result, "other");
  assert.ok(clock.t - t0 < 1000, `the request ended ${clock.t - t0} ms in`);
});

test("a request whose page action throws is noted like any other", async () => {
  const { d, log } = world();
  d.dom.find = () => {
    throw new Error("detached node");
  };
  const out = await d.request(ask("103", { id: "r1" }));
  assert.equal(out.result, "failed");
  const notes = log.events.filter((e) => e.type === "note").map((e) => [e.what, e.result ?? null, e.request_id]);
  assert.deepEqual(notes, [
    ["request failed", null, "r1"],
    ["request", "failed", "r1"],
  ]);
  assert.equal(d.requesting, null);
});

test("a request's notes name it by the API's id for it", async () => {
  const { d, log } = world({ dud: ["103"] });
  await d.request(ask("103", { id: "r1" }));
  const notes = log.events.filter((e) => e.type === "note").map((e) => [e.what, e.yid, e.request_id]);
  assert.deepEqual(notes, [["request failed", "103", "r1"], ["request", "103", "r1"]]);
});

test("a request that lands ends the armed turn that stood aside, its /plan hold included", async () => {
  const { d, log } = world({ planHang: true });
  const turn = d.turn(K); // holds /plan for the solve of picks 1..K-1, which never comes
  const req = await d.request(ask("103", { id: "r1" }));
  assert.equal(req.result, "landed");
  const out = await Promise.race([turn, ticks(2000).then(() => "still holding")]);
  assert.notEqual(out, "still holding");
  assert.equal(out.result, "landed");
  assert.equal(out.how, "manual");
  assert.equal(out.attempts, 0);
  assert.deepEqual(attempts(log), [["103", "request", 1]], "the drafter clicked nothing");
});

test("offer: a newer request for the pick stops the one being served, which hands over at once", async () => {
  const { d, log, at } = world({ dud: ["103"] });
  const heard = [];
  const done = new Promise((resolve) => {
    d.onRequest = (e) => {
      heard.push(e.start ? ["start", e.start.yahoo_player_id] : ["end", e.out.yid, e.out.result]);
      if (e.out && e.out.yid === "102") resolve();
    };
  });
  d.offer(ask("103", { id: "r1" }));
  d.offer(ask("103", { id: "r1" })); // the next poll reads the same request: nothing new
  at(1000, () => d.offer(ask("102", { id: "r2" }))); // the user asked for another player
  await Promise.race([done, ticks(5000)]);
  assert.deepEqual(heard, [["start", "103"], ["end", "103", "stopped"], ["start", "102"], ["end", "102", "landed"]]);
  const notes = log.events.filter((e) => e.type === "note").map((e) => [e.what, e.yid, e.result, e.request_id]);
  assert.deepEqual(notes, [
    ["request", "103", "stopped", "r1"],
    ["request", "102", "landed", "r2"],
  ]);
  assert.deepEqual(attempts(log), [["103", "request", 1], ["102", "request", 1]]);
});

test("offer: a request read before its turn is served when the turn comes", async () => {
  const { d, tracker, clock } = world({ clockFrame: false });
  d.offer(ask("103", { id: "r1" }));
  assert.equal(d.requesting, null, "pick K is not on the clock yet");
  const done = new Promise((resolve) => {
    d.onRequest = (e) => e.out && resolve(e.out);
  });
  tracker.ingest(`D|${K}|${SLOT}|30`, clock.t);
  d.serveOffered(); // content.js on the turn frame
  const out = await Promise.race([done, ticks(5000).then(() => null)]);
  assert.equal(out && out.result, "landed");
  d.offer(null);
  assert.equal(d.offered, null);
});
