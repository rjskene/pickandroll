// node --test extension/test/*.test.js
// Turns are independent: starting turn k stops turn k-1 wherever it is, and nothing about k
// waits for k-1 to settle. A discrete-event clock runs the two turns side by side.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { RoomTracker } = require("../lib/room.js");
const { Drafter } = require("../lib/drafter.js");
const { autodraftSeen } = require("../lib/yahoo.js");

const SLOT = 1; // 12 teams: my picks 24 and 25 come back to back
const START = 1_000_000;

const flush = () => new Promise((r) => setImmediate(r));

/** Timers on a virtual clock: ``sleep`` registers one, ``run`` fires them in time order and
 * lets every promise settle between two of them, until every promise in ``promises`` has
 * settled, those added while it runs included (a turn started by a frame mid-run). */
function scheduler() {
  const clock = { t: START };
  const timers = [];
  let seq = 0;
  const sleep = (ms) => new Promise((r) => timers.push([clock.t + Math.max(0, ms), seq++, r]));
  const at = (ms, fn) => timers.push([START + ms, seq++, fn]);
  async function run(promises, limitMs = 120000) {
    const settled = new Set();
    const watched = new Set();
    for (let n = 0; ; n++) {
      await flush();
      for (const p of promises) {
        if (watched.has(p)) continue;
        watched.add(p);
        p.then(() => settled.add(p), () => settled.add(p));
      }
      await flush();
      if (promises.every((p) => settled.has(p))) return Promise.all([...promises]);
      if (n > 20000) throw new Error(`spinning at ${clock.t - START} ms, ${timers.length} timers`);
      timers.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      const next = timers.shift();
      if (!next || next[0] > START + limitMs) throw new Error(`stuck at ${clock.t - START} ms`);
      clock.t = Math.max(clock.t, next[0]);
      next[2]();
    }
  }
  return { clock, sleep, at, run };
}

const rows = (ys) => ys.map((y) => ({ yahoo_player_id: y, name: `P ${y}`, ini: "P", last: y, team: "T" }));

/** Yahoo's own ranking, for an autopick with an empty queue: players not in our plan. */
const ROOM_RANK = ["201", "202", "203"];

/** A room at pick 24 on the clock, my picks 24 and 25. ``clicksToLand`` per overall: how many
 * clicks Yahoo needs before the pick lands (99: never by click). ``planHold`` per board: how
 * long the API holds /plan. Every page action is logged with its time and the turn on the
 * clock. ``startTurn`` is what content.js does on a turn frame.
 * Like Yahoo, the room autopicks the moment a turn starts with Autodraft on (mock 1: on every
 * such pick, with no X| or 5| frames): the queue's head, else its own ranking. It decides on
 * its side at the turn frame, so nothing the client does after that frame changes the pick. */
function room({
  clicksToLand = { 24: 1, 25: 1 },
  planHold = {},
  autodraftSticks = false,
  secondQueues = true,
  probe = "drafted", // what Yahoo does with the probe's star: "drafted" or "queued"
  probeRound = null,
  watch = false, // content.js's switch watcher, run at every flip, and its armed gate on turn frames
} = {}) {
  const s = scheduler();
  const tracker = new RoomTracker({ draftId: "d", slot: SLOT });
  for (let k = 1; k < 24; k++) tracker.ingest(`0|${k}|${900 + k}|${k <= 12 ? k : 25 - k}|X|0`, s.clock.t - 5000);
  tracker.ingest(`D|24|${SLOT}|30`, s.clock.t);
  const log = { page: [], events: [], plans: [], aborts: [], turns: {}, how: {} };
  const clicks = {};
  let auto = false;
  let queue = []; // Yahoo's queue of yids, head first
  const act = (what) => log.page.push([s.clock.t - START, what]);
  // What content.js does with a flip of the switch (watchYahoo, reportControl): a control event
  // only when the seat changes hands; a seat handed to Yahoo refuses the next turn (takeTurn).
  const seat = { was: false, autopick: false, events: [], refused: [] };
  function watchSwitch() {
    if (!watch) return;
    const seen = autodraftSeen(seat.was, auto, { ours: d.touched.autodraft });
    seat.was = auto;
    if (!seen) return;
    seat.events.push(seen.note);
    if (seen.autopick === null || seen.autopick === seat.autopick) return;
    seat.autopick = seen.autopick;
    seat.events.push(seen.autopick ? `control absent ${seen.reason}` : "control armed");
  }
  const d = new Drafter({
    tracker,
    dom: {
      draftable: () => true,
      find: (c) => ({ yid: c.yahoo_player_id }),
      scrollTo: async () => null,
      search: async () => null,
      async click(row, c) {
        const k = tracker.myTurnNow();
        act(`click ${k} ${c.yahoo_player_id}`);
        clicks[k] = (clicks[k] || 0) + 1;
        if (k !== null && clicks[k] === clicksToLand[k]) {
          await s.sleep(300);
          if (!tracker.picks.has(k)) land(k, c.yahoo_player_id);
        }
        await s.sleep(100);
        return "clicked";
      },
      nudge: async () => {},
      async queueOnly(c) {
        act(`queue ${tracker.myTurnNow()} ${c.yahoo_player_id}`);
        queue = [String(c.yahoo_player_id)]; // alone in the queue
        await s.sleep(400);
        return { ok: true };
      },
      async probeQueue(c) {
        const k = tracker.myTurnNow();
        const yid = String(c.yahoo_player_id);
        act(`probe ${k} ${yid}`);
        if (probe === "drafted") {
          await s.sleep(300);
          if (!tracker.picks.has(k)) land(k, yid);
          return { outcome: "drafted", panel: [], control: "Draft" };
        }
        queue.push(yid);
        await s.sleep(400);
        return { outcome: "queued", panel: [`P ${yid}`], control: "Add to Queue" };
      },
      async queueAlso(c2, c) {
        act(`queue2 ${tracker.myTurnNow()} ${c2.yahoo_player_id}`);
        await s.sleep(350);
        if (!secondQueues) return { ok: false, msg: "queue check failed", single: await this.queueOnly(c) };
        queue.push(String(c2.yahoo_player_id));
        return { ok: true };
      },
      async setAutodraft(on) {
        act(`autodraft ${on}`);
        if (!(autodraftSticks && !on)) auto = on;
        watchSwitch(); // the worst case: the watcher sees the flip at once
        await s.sleep(350);
        return auto;
      },
      autodraftOn: () => auto,
      async clearQueue() {
        act("clearQueue");
        queue = [];
        await s.sleep(50);
        return true;
      },
      async reset() {
        act("reset");
      },
    },
    plan: async (wait, board, signal) => {
      log.plans.push([s.clock.t - START, wait, board]);
      const held = s.sleep(Math.min((wait || 0) * 1000, planHold[board] ?? 20));
      // A cancelled hold fails at once, as the service worker's aborted fetch does.
      const cancelled = new Promise((_, reject) => {
        if (!signal) return;
        signal.addEventListener("abort", () => {
          log.aborts.push([s.clock.t - START, board]);
          reject(Object.assign(new Error("cancelled"), { status: 499 }));
        });
      });
      cancelled.catch(() => {});
      await Promise.race([held, cancelled]);
      const taken = tracker.taken();
      const ys = ["101", "102", "103", "104", "105"].filter((y) => !taken.has(y));
      // Board 23 is pick 24's, and 25 is mine too: the plan's player for 25 (104) leads second.
      const second = board === 23 ? rows(["104", "102", "103"].filter((y) => !taken.has(y))) : null;
      return { fresh: true, board, waited_ms: 20, candidates: rows(ys), second_pick: second ? 25 : null, second };
    },
    emit: (e) => log.events.push({ ...e, at: e.t === undefined ? null : e.t - START }),
    sleep: s.sleep,
    now: () => s.clock.t,
  });
  d.probeRound = probeRound;
  const promises = [];
  function startTurn(k) {
    if (watch && seat.autopick) {
      seat.refused.push(k);
      return Promise.resolve(null);
    }
    log.turns[k] = s.clock.t - START;
    const p = d.turn(k).then((out) => (log.turns[`${k}:out`] = out));
    promises.push(p);
    return p;
  }
  /** Pick k lands (labelled as content.js labels it, with the switch as it is at landing);
   * when it is 24, Yahoo puts 25 on the clock and its frame starts that turn. With Autodraft on
   * at that frame, Yahoo takes 25 at once: its frame follows the turn frame, before the turn's
   * first page action can reach Yahoo. */
  function land(k, yid, frames = []) {
    for (const f of frames) tracker.ingest(f, s.clock.t);
    tracker.ingest(`0|${k}|${yid}|${SLOT}|X|0`, s.clock.t);
    queue = queue.filter((y) => y !== String(yid));
    log.how[k] = tracker.how(k, { autodraft: auto });
    log.page.push([s.clock.t - START, `landed ${k} ${yid}`]);
    if (k === 24) {
      const autopick = auto;
      tracker.ingest(`D|25|${SLOT}|30`, s.clock.t);
      startTurn(25);
      if (autopick) land(25, queue[0] ?? ROOM_RANK.find((y) => !tracker.taken().has(y)));
    }
  }
  const pageAfter = (ms) => log.page.filter(([t, w]) => t >= ms && !w.startsWith("landed"));
  /** A missed pick: Yahoo turns the switch on itself. */
  const yahooFlips = () => {
    auto = true;
    watchSwitch();
  };
  return { s, d, tracker, log, land, startTurn, promises, pageAfter, seat, yahooFlips, auto: () => auto, queue: () => queue };
}

test("turn k+1 starts on its frame while k waits to re-click; k clicks nothing after", async () => {
  const r = room({ clicksToLand: { 24: 99, 25: 1 } });
  // Yahoo registers turn 24's first click late, mid re-click wait.
  r.s.at(2400, () => r.land(24, "101"));
  r.startTurn(24);
  await r.s.run(r.promises); // turn 25 joins the list while 24 runs
  const out24 = r.log.turns["24:out"];
  const out25 = r.log.turns["25:out"];
  assert.equal(out24.result, "landed");
  assert.equal(out24.stopped, "superseded");
  assert.equal(r.log.turns[25], 2400); // on its own frame, not after 24 settled
  assert.deepEqual(
    r.log.page.filter(([t, w]) => t >= 2400 && w.startsWith("click 24")),
    [],
    "turn 24 clicked after it was superseded",
  );
  assert.equal(out25.result, "landed");
  assert.equal(out25.yid, "102");
  const attempts = r.log.events.filter((e) => e.type === "draft_attempt");
  assert.deepEqual(
    attempts.map((e) => [e.overall, e.yid, e.board]),
    [
      [24, "101", 23],
      [24, "101", 23], // the re-click at 1.8 s
      [25, "102", 24],
    ],
  );
});

test("a /plan hold in turn k does not delay turn k+1's ask", async () => {
  // The API holds board 23's plan for 18 s; pick 24 lands meanwhile (the user's queue, say).
  const r = room({ planHold: { 23: 18000 } });
  r.s.at(1000, () => r.land(24, "105", ["X|29", `5|${SLOT}`]));
  r.startTurn(24);
  await r.s.run(r.promises);
  const asks = r.log.plans.map(([t, , board]) => [t, board]);
  assert.deepEqual(asks[0], [0, 23]);
  assert.deepEqual(asks[1], [1000, 24]); // asked the moment 25 went on the clock
  const firstClick25 = r.log.page.find(([, w]) => w.startsWith("click 25"));
  assert.ok(firstClick25[0] < 1000 + 2000, `turn 25 clicked at ${firstClick25[0]} ms`);
  assert.deepEqual(r.log.aborts, [[1000, 23]], "turn 24's hold was not cancelled when 25 began");
  assert.equal(r.log.turns["24:out"].stopped, "superseded");
  assert.equal(r.log.turns["25:out"].result, "landed");
});

/** Turn 24's clicks never land; at 6 s left it queues 101 alone and turns Autodraft on, and
 * Yahoo takes 101 from the queue 500 ms later. Pick 25 then starts with Autodraft still on. */
function backstopThenLand(r) {
  r.startTurn(24);
  const state = { landedAt: null };
  const poll = () => {
    const on = r.log.page.find(([, w]) => w === "autodraft true");
    if (on && state.landedAt === null) {
      state.landedAt = r.s.clock.t - START + 500;
      r.s.at(state.landedAt, () => r.land(24, "101", ["X|29", `5|${SLOT}`]));
    } else if (state.landedAt === null) r.s.at(r.s.clock.t - START + 100, poll);
  };
  r.s.at(100, poll);
  return state;
}

test("a superseded turn left Autodraft on: the next turn turns it off before anything else", async () => {
  const r = room({ clicksToLand: { 24: 99, 25: 1 } });
  const state = backstopThenLand(r);
  await r.s.run(r.promises);
  const after = r.pageAfter(state.landedAt).map(([, w]) => w);
  // The handover undoes 24's backstop first, Autodraft before the queue; turn 25 then has
  // nothing left to draft (Yahoo took 25 at its turn frame) and only tidies.
  assert.deepEqual(after, ["autodraft false", "clearQueue", "reset", "clearQueue", "reset"]);
  assert.equal(r.auto(), false);
  assert.equal(r.log.turns["24:out"].yid, "101");
  assert.equal(r.log.plans.filter(([, , board]) => board === 24).length, 0, "asked /plan for a pick already taken");
});

test("back-to-back backstop: the plan's player for 25 is queued behind 24's, and Yahoo takes it", async () => {
  // The exception (user, 2026-10-02): 24's backstop queues 101 for 24 and the plan's player for
  // 25 (104, plan.second) behind it. Yahoo takes 101 from the queue, then autopicks 25 from the
  // queue's head at 25's turn frame: our player, not its own ranking's.
  const r = room({ clicksToLand: { 24: 99, 25: 1 } });
  const state = backstopThenLand(r);
  await r.s.run(r.promises);
  assert.deepEqual(
    r.log.page.filter(([, w]) => w.startsWith("queue")).map(([, w]) => w),
    ["queue 24 101", "queue2 24 104"],
  );
  assert.equal(r.log.turns["24:out"].yid, "101");
  assert.equal(r.log.turns["25:out"].yid, "104", "25 is the plan's player");
  assert.equal(r.log.how[25], "queue");
  assert.deepEqual(
    r.log.page.filter(([, w]) => w.startsWith("landed")).map(([t, w]) => [t, w]),
    [
      [state.landedAt, "landed 24 101"],
      [state.landedAt, "landed 25 104"],
    ],
  );
  // Both queue attempts are on board 23, so the scorecard labels 25 stale, honestly.
  assert.deepEqual(
    r.log.events.filter((e) => e.type === "draft_attempt" && e.method === "queue").map((e) => [e.overall, e.yid, e.board]),
    [
      [24, "101", 23],
      [25, "104", 23],
    ],
  );
  const own = r.log.events.filter((e) => e.type === "draft_attempt" && e.overall === 24).length;
  assert.equal(r.log.turns["24:out"].attempts, own, "the attempt for 25 is not turn 24's");
  // The handover still turns Autodraft off first, and turn 25 clicks nothing.
  assert.equal(r.pageAfter(state.landedAt)[0][1], "autodraft false");
  assert.ok(!r.log.page.some(([, w]) => w.startsWith("click 25")));
  assert.equal(r.auto(), false);
});

test("the backstop's own Autodraft switch is not Yahoo's flip: no control event, and 25 still starts", async () => {
  const r = room({ clicksToLand: { 24: 99, 25: 1 }, watch: true });
  const state = backstopThenLand(r);
  await r.s.run(r.promises);
  assert.deepEqual(r.seat.events, ["autodraft on by pickandroll", "autodraft off"]); // no control event
  assert.equal(r.seat.autopick, false, "the seat stayed armed");
  assert.deepEqual(r.seat.refused, []);
  assert.equal(r.log.turns[25], state.landedAt, "the back-to-back turn started on its frame");
  assert.equal(r.log.turns["25:out"].yid, "104");
  assert.equal(r.auto(), false);
});

test("a flip Yahoo makes hands the seat over: control absent, and the next turn is refused", async () => {
  const r = room({ watch: true });
  r.yahooFlips();
  assert.equal(await r.startTurn(24), null);
  assert.deepEqual(r.seat.events, ["autodraft on by Yahoo", "control absent autopick"]);
  assert.deepEqual(r.seat.refused, [24]);
});

test("back-to-back backstop whose second entry fails: 24's player alone, and Yahoo ranks 25", async () => {
  const r = room({ clicksToLand: { 24: 99, 25: 1 }, secondQueues: false });
  const state = backstopThenLand(r);
  await r.s.run(r.promises);
  assert.deepEqual(
    r.log.page.filter(([, w]) => w.startsWith("queue")).map(([, w]) => w),
    ["queue 24 101", "queue2 24 104", "queue 24 101"],
    "the queue is put back to this pick's player alone",
  );
  assert.ok(r.log.events.some((e) => e.what === "queue backstop: second entry failed" && e.overall === 25));
  assert.ok(!r.log.events.some((e) => e.type === "draft_attempt" && e.overall === 25));
  assert.equal(r.log.turns["25:out"].yid, "201", "Yahoo's own ranking");
  assert.equal(r.log.how[25], "autopick");
  assert.equal(r.log.turns[25], state.landedAt);
  assert.equal(r.auto(), false);
});

test("a backstop whose next pick is not mine queues exactly one player", async () => {
  // 24 lands on its first click; 25's clicks never land, and my next pick after 25 is 48.
  const r = room({ clicksToLand: { 24: 1, 25: 99 } });
  r.startTurn(24);
  let landedAt = null;
  const poll = () => {
    const on = r.log.page.find(([, w]) => w === "autodraft true");
    if (on && landedAt === null) {
      landedAt = r.s.clock.t - START + 500;
      r.s.at(landedAt, () => r.land(25, "102", ["X|29", `5|${SLOT}`]));
    } else if (landedAt === null) r.s.at(r.s.clock.t - START + 100, poll);
  };
  r.s.at(100, poll);
  await r.s.run(r.promises);
  assert.deepEqual(
    r.log.page.filter(([, w]) => w.startsWith("queue")).map(([, w]) => w),
    ["queue 25 102"],
  );
  assert.equal(r.log.turns["24:out"].yid, "101");
  assert.equal(r.log.turns["25:out"].yid, "102");
  assert.equal(r.auto(), false);
});

test("Autodraft that will not go off: the queue is left alone", async () => {
  const r = room({ clicksToLand: { 24: 99, 25: 1 }, autodraftSticks: true });
  r.startTurn(24);
  await r.s.run(r.promises);
  const page = r.log.page.map(([, w]) => w);
  const off = page.lastIndexOf("autodraft false");
  assert.ok(off >= 0);
  assert.ok(!page.slice(off).includes("clearQueue"), page.join(", "));
});

test("a hand pick mid-turn stops the turn before its next page action", async () => {
  const r = room({ clicksToLand: { 24: 99, 25: 1 } });
  r.s.at(1500, () => {
    r.tracker.noteManual(r.s.clock.t, "Draft");
    r.d.handPick(24); // what content.js does on the user's trusted click
  });
  r.s.at(2500, () => r.tracker.ingest(`0|24|777|${SLOT}|X|0`, r.s.clock.t));
  r.startTurn(24);
  await r.s.run(r.promises);
  const out = r.log.turns["24:out"];
  assert.equal(out.result, "manual");
  assert.equal(out.stopped, "manual");
  assert.deepEqual(r.pageAfter(1500), [], "the drafter touched the page after the hand pick");
  assert.ok(r.log.events.filter((e) => e.type === "draft_attempt").every((e) => e.at < 1500));
});

test("an older turn is never restarted, and a turn is taken once", async () => {
  const r = room({ clicksToLand: { 24: 99, 25: 1 } });
  r.s.at(2400, () => r.land(24, "101"));
  r.startTurn(24);
  await r.s.run(r.promises);
  assert.equal(await r.d.turn(24), null);
  assert.equal(await r.d.turn(25), null);
  assert.equal(r.d.busy, false);
});

const probes = (r) => r.log.events.filter((e) => e.what === "queue_probe");

test("the queue probe whose star drafts: logged once, and the pick is a row pick", async () => {
  // Round 3 from pick 25 on: 24 is round 2, and 25 (next mine 48) is the first turn due.
  const r = room({ probeRound: 3, probe: "drafted" });
  r.startTurn(24);
  await r.s.run(r.promises);
  assert.deepEqual(
    probes(r).map((e) => [e.overall, e.yid, e.outcome, e.control, e.board]),
    [[25, "102", "drafted", "Draft", 24]],
  );
  assert.ok(!r.log.page.some(([, w]) => w.startsWith("click 25")), "drafted by the star: no click after");
  const out = r.log.turns["25:out"];
  assert.equal(out.yid, "102");
  assert.equal(r.log.how[25], "row");
  const a25 = r.log.events.filter((e) => e.type === "draft_attempt" && e.overall === 25);
  assert.deepEqual(a25.map((e) => [e.yid, e.method, e.at]), [["102", "row", probes(r)[0].at]]);
});

test("the queue probe whose star queues: the normal click follows, and the queue is emptied", async () => {
  const r = room({ probeRound: 3, probe: "queued" });
  r.startTurn(24);
  await r.s.run(r.promises);
  assert.deepEqual(
    probes(r).map((e) => [e.overall, e.outcome, e.panel]),
    [[25, "queued", ["P 102"]]],
  );
  const page = r.log.page.map(([, w]) => w);
  const at = page.indexOf("probe 25 102");
  assert.equal(page[at + 1], "click 25 102", page.join(", "));
  assert.equal(r.log.turns["25:out"].yid, "102");
  assert.ok(page.slice(at).includes("clearQueue"));
  assert.deepEqual(r.queue(), []);
});

test("the queue probe runs once, never on a turn whose next pick is mine, and not when off", async () => {
  // From round 1 on: 24's next pick (25) is mine, so 25 is the first turn due; 48 would not be.
  const r = room({ probeRound: 1, probe: "queued" });
  r.startTurn(24);
  await r.s.run(r.promises);
  assert.deepEqual(probes(r).map((e) => e.overall), [25]);
  assert.equal(r.d.probed, 25);
  assert.equal(r.d.probeDue(48), false);
  const off = room({ probe: "queued" });
  off.startTurn(24);
  await off.s.run(off.promises);
  assert.deepEqual(probes(off), []);
  assert.ok(!off.log.page.some(([, w]) => w.startsWith("probe")));
});
