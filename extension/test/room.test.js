// node --test extension/test
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { RoomTracker } = require("../lib/room.js");

const T0 = 1790543000000;
const room = (slot = 1) => new RoomTracker({ draftId: "d1", slot });

test("picks are kept once, with their first arrival time, and sent from the API cursor", () => {
  const r = room();
  assert.equal(r.ingest("0|1|10094|1|C|0", T0).picks, 1);
  assert.equal(r.ingest("0|1|10094|1|C|0", T0 + 50).picks, 0);
  assert.equal(r.ingest("P|1=10094,1,0|2=5352,2,0|3=6014,3,0|", T0 + 100).picks, 2);
  assert.equal(r.ingest("0|5|6512|5|SF|0", T0 + 200).picks, 1);
  assert.deepEqual(
    r.unsent().map((p) => [p.overall, p.yahoo_player_id, p.slot, p.t_room, p.src]),
    [
      [1, "10094", 1, T0, "socket"],
      [2, "5352", 2, T0 + 100, "history"],
      [3, "6014", 3, T0 + 100, "history"],
      [5, "6512", 5, T0 + 200, "socket"],
    ],
  );
  assert.equal(r.contiguous(), 3);
  assert.equal(r.last(), 5);
  r.synced({ synced_through: 3, waiting_for: 4 });
  assert.equal(r.gap, 4);
  assert.equal(r.behind(), 2);
  assert.deepEqual(r.unsent().map((p) => p.overall), [5]);
  assert.ok(r.taken().has("6014"));
});

test("every pick on the clock is a turn_start, once; mine is a turn", () => {
  const r = room(2);
  assert.equal(r.ingest("D|1|1|30", T0).turn, null);
  r.ingest("D|1|1|30", T0 + 10);
  r.ingest("0|1|10094|1|C|0", T0 + 3000);
  assert.equal(r.ingest("D|2|2|30", T0 + 3100).turn, 2);
  assert.equal(r.myTurnNow(), 2);
  assert.deepEqual(r.takeEvents(), [
    { type: "turn_start", t: T0, overall: 1, slot: 1, clock_s: 30 },
    { type: "turn_start", t: T0 + 3100, overall: 2, slot: 2, clock_s: 30 },
  ]);
  assert.deepEqual(r.takeEvents(), []);
});

test("my pick lands: manual after a trusted click, Yahoo's own pick after 5|slot, else unknown", () => {
  const r = room(1);
  r.ingest("D|1|1|30", T0);
  assert.equal(r.noteManual(T0 + 4000, "Draft"), 1);
  let out = r.ingest("0|1|10094|1|C|0", T0 + 5000);
  assert.deepEqual(r.landedEvent(out.landed), {
    type: "pick_landed",
    overall: 1,
    yid: "10094",
    t: T0 + 5000,
    ms_from_turn: 5000,
    how: "manual",
  });
  // Not my turn: a click on a Draft control is not a manual pick.
  r.ingest("D|2|2|30", T0 + 5100);
  assert.equal(r.noteManual(T0 + 5200, "Draft"), null);
  // Yahoo announces its own pick for another slot: nothing of mine.
  r.ingest("X|29", T0 + 5300);
  r.ingest("5|2", T0 + 5310);
  r.ingest("0|2|5352|2|C|0", T0 + 5400);
  // Pick 24 runs out the clock: Yahoo announces it, the seat is live, so it is an expiry.
  r.ingest("D|24|1|30", T0 + 10000);
  r.ingest("X|29", T0 + 40000);
  r.ingest("5|1", T0 + 40010);
  out = r.ingest("0|24|6022|1|PG|0", T0 + 40100);
  assert.equal(r.landedEvent(out.landed).how, "expiry");
  // Pick 25 with Yahoo's Autodraft switch on: autopick. A buzzer-beater by hand is manual.
  r.ingest("D|25|1|30", T0 + 40200);
  r.ingest("5|1", T0 + 40210);
  out = r.ingest("0|25|6512|1|SF|0", T0 + 40300);
  assert.equal(r.landedEvent(out.landed, { autodraft: true }).how, "autopick");
  r.ingest("D|48|1|30", T0 + 50000);
  r.ingest("C|1", T0 + 79000);
  r.noteManual(T0 + 79500, "Draft");
  out = r.ingest("0|48|6413|1|SF|0", T0 + 79900);
  assert.equal(r.landedEvent(out.landed).how, "manual");
  // Pick 49: nothing says how.
  r.ingest("D|49|1|30", T0 + 80000);
  out = r.ingest("0|49|6355|1|SF|0", T0 + 82000);
  assert.equal(r.landedEvent(out.landed).how, "unknown");
  // Pick 72 with Autodraft on: Yahoo picks at the turn start with no 5|slot (mock 2565888).
  r.ingest("D|72|1|30", T0 + 90000);
  out = r.ingest("0|72|6022|1|PG|0", T0 + 90200);
  assert.equal(r.landedEvent(out.landed, { autodraft: true }).how, "autopick");
  // Another team's pick is never a landed pick of mine.
  assert.equal(r.ingest("0|3|6014|3|PG|0", T0 + 83000).landed, null);
});

test("Yahoo's own pick wins over the extension's attempt", () => {
  const r = room(1);
  r.ingest("D|1|1|30", T0);
  r.noteAttempt(1, "row");
  r.ingest("5|1", T0 + 29900);
  const out = r.ingest("0|1|10094|1|C|0", T0 + 30000);
  assert.equal(r.landedEvent(out.landed).how, "expiry");
});

test("an attempt by the extension says how the pick landed", () => {
  const r = room(1);
  r.ingest("D|1|1|30", T0);
  r.noteAttempt(1, "row");
  const out = r.ingest("0|1|10094|1|C|0", T0 + 1500);
  assert.equal(r.landedEvent(out.landed).how, "row");
});

test("next pick of mine and the snapshot", () => {
  const r = room(12);
  assert.equal(r.nextMine(), 12);
  for (let k = 1; k <= 12; k++) r.ingest(`0|${k}|${1000 + k}|${k}|C|0`, T0 + k);
  assert.equal(r.nextMine(), 13);
  const s = r.snapshot();
  assert.equal(s.room_picks, 12);
  assert.equal(s.contiguous, 12);
  assert.equal(s.behind, 12);
});

test("the room's team count comes from the attached room", () => {
  const r = room(1);
  r.configure({ numTeams: 10, rounds: 13 });
  assert.deepEqual(r.mine.slice(0, 2), [1, 20]);
  assert.equal(r.ingest("R|a|b|c|", T0).kind, "order");
  assert.equal(r.numTeams, 10);
});
