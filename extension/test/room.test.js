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
    { type: "turn_start", t: T0, overall: 1, slot: 1, clock_s: 30, teams: null },
    { type: "turn_start", t: T0 + 3100, overall: 2, slot: 2, clock_s: 30, teams: null },
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

test("picks of mine from the history frame land how history, with no time from the turn (#26)", () => {
  const r = room(1);
  r.ingest("D|1|1|30", T0); // the tab saw pick 1 go on the clock, then lost the room
  // A reconnect: Yahoo's history frame brings picks 1 (mine), 2 and 24 (mine).
  const out = r.ingest("P|1=10094,1,0|2=5352,2,0|24=6022,1,0|", T0 + 60000);
  assert.equal(out.landed, null);
  assert.deepEqual(
    out.history.map((rec) => r.landedEvent(rec)),
    [1, 24].map((overall, i) => ({
      type: "pick_landed",
      overall,
      yid: ["10094", "6022"][i],
      t: T0 + 60000,
      ms_from_turn: null,
      how: "history",
    })),
  );
  // Each is posted once: the same frame again, or the pick from the socket after it, adds none.
  assert.deepEqual(r.ingest("P|1=10094,1,0|24=6022,1,0|", T0 + 61000).history, []);
  assert.equal(r.ingest("0|24|6022|1|PG|0", T0 + 61500).landed, null);
  // A pick of mine from the socket is unchanged.
  r.ingest("D|25|1|30", T0 + 62000);
  assert.equal(r.landedEvent(r.ingest("0|25|6512|1|SF|0", T0 + 63000).landed).ms_from_turn, 1000);
});

test("the player of a failed request taken from the backstop's queue is the user's pick (#26)", () => {
  const r = room(1);
  r.ingest("D|1|1|30", T0);
  r.noteAttempt(1, "queue");
  r.noteRequested(1, 10094);
  r.ingest("X|29", T0 + 25000);
  r.ingest("5|1", T0 + 25010);
  let out = r.ingest("0|1|10094|1|C|0", T0 + 25100);
  assert.equal(r.landedEvent(out.landed, { autodraft: true }).how, "manual");
  // Yahoo took the best candidate queued second: the backstop's pick, as before.
  r.ingest("D|24|1|30", T0 + 30000);
  r.noteAttempt(24, "queue");
  r.noteRequested(24, 6022);
  r.ingest("5|1", T0 + 55010);
  out = r.ingest("0|24|6512|1|SF|0", T0 + 55100);
  assert.equal(r.landedEvent(out.landed, { autodraft: true }).how, "autopick");
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
  assert.equal(r.orderLen, 3, "the R| frame's length is kept for a note");
  assert.equal(r.order.error, "3 entries for 13 rounds", "and it does not check out: not used");
  assert.equal(r.snapshot().order_len, 3);
});

// A room's frames for picks 1..n: D| as each goes on the clock, then 0| as it lands.
const play = (r, teams, n, t = T0) => {
  const { pickOwner } = require("../lib/protocol.js");
  for (let k = 1; k <= n; k++) {
    const s = pickOwner(teams, k).slot;
    r.ingest(`D|${k}|${s}|30`, t + 2 * k);
    r.ingest(`0|${k}|${5000 + k}|${s}|C|0`, t + 2 * k + 1);
  }
};

test("the room's own team count shows where the snake first turns (#17)", () => {
  const r = room(1); // attached as 12, as mock 2 was
  assert.equal(r.teamsSeen(), null, "nothing seen: any count fits");
  play(r, 10, 10);
  assert.equal(r.teamsSeen(), null, "picks 1..10 on seats 1..10 fit 10 to 20 teams");
  r.ingest("D|11|10|30", T0 + 100); // the snake turns: pick 11 back on seat 10
  assert.equal(r.teamsSeen(), 10);
  assert.equal(r.snapshot().room_teams, 10);
  assert.equal(r.numTeams, 12, "the attach's count is the API's to change, not the tracker's");
  const twelve = room(5);
  play(twelve, 12, 13);
  assert.equal(twelve.teamsSeen(), 12);
});

test("history alone shows the count; a pick no snake order explains shows none", () => {
  const r = room(3);
  r.ingest("P|1=11,1,0|2=12,2,0|3=13,3,0|4=14,4,0|5=15,4,0|6=16,3,0|", T0);
  assert.equal(r.teamsSeen(), 4);
  const traded = room(3);
  play(traded, 12, 14);
  traded.ingest("0|15|9999|7|C|0", T0 + 100); // a traded pick: 15 is seat 10's in a 12-team snake
  assert.equal(traded.teamsSeen(), null);
});

test("each turn_start carries the room's count once it shows (#17)", () => {
  const r = room(1);
  play(r, 10, 10);
  const before = r.takeEvents();
  assert.equal(before.length, 10);
  assert.ok(before.every((e) => e.teams === null));
  r.ingest("D|11|10|30", T0 + 100);
  assert.deepEqual(
    r.takeEvents().map((e) => [e.overall, e.teams]),
    [[11, 10]],
    "the turn that shows the count carries it",
  );
});

test("nothing past the draft's last pick is mine: the frame after 156 starts no turn", () => {
  const { pickOwner } = require("../lib/protocol.js");
  const r = room(12); // slot 12 makes 156 and, in a 14th round, 157
  for (let k = 1; k <= 156; k++) r.ingest(`0|${k}|${9000 + k}|${pickOwner(12, k).slot}|C|0`, T0 + k);
  assert.equal(r.isMine(156), true);
  assert.equal(r.isMine(157), false);
  r.takeEvents();
  const out = r.ingest("D|157|12|30", T0 + 200);
  assert.equal(out.turn ?? null, null);
  assert.equal(r.myTurnNow(), null);
  assert.equal(r.nextMine(), null);
  assert.deepEqual(r.takeEvents(), [], "no turn_start past the end");
  assert.equal(r.ingest("0|157|9157|12|C|0", T0 + 300).picks, 0, "nor a pick to send");
  assert.equal(r.unsent().some((p) => p.overall === 157), false);
});

// Keepers (docs/KEEPERS.md): slot 1 keeps at pick 24 (round 2), slot 6 at pick 19.
const KEPT = [{ overall: 19, slot: 6 }, { overall: 24, slot: 1 }];
function throughPick(r, last, skip = []) {
  const { pickOwner } = require("../lib/protocol.js");
  for (let k = 1; k <= last; k++) {
    if (!skip.includes(k)) r.ingest(`0|${k}|${9000 + k}|${pickOwner(12, k).slot}|C|0`, T0 + k);
  }
}

test("a keeper slot of mine on the clock is no turn: no draft attempt and no landing", () => {
  const r = room(1);
  r.configure({ keepers: KEPT });
  assert.deepEqual(r.mine.slice(0, 3), [1, 25, 48], "my keeper slot is not a pick of mine");
  assert.equal(r.isMine(24), false);
  throughPick(r, 23);
  r.takeEvents();
  assert.equal(r.nextMine(), 25);
  const out = r.ingest("D|24|1|30", T0 + 100);
  assert.equal(out.turn, null, "the frame arms nothing");
  assert.equal(r.myTurnNow(), null);
  assert.deepEqual(r.takeEvents(), [
    { type: "turn_start", t: T0 + 100, overall: 24, slot: 1, clock_s: 30, teams: 12, keeper: true },
  ]);
  const kept = r.ingest("0|24|7777|1|C|0", T0 + 200);
  assert.equal(kept.picks, 1, "the keeper's pick still goes to the API");
  assert.equal(kept.landed, null, "and is no landing of mine");
  assert.equal(r.ingest("D|25|1|30", T0 + 300).turn, 25, "the pick after it is my turn");
});

test("a keeper slot the room never sends counts as known, so the turn after it is found", () => {
  const r = room(1);
  r.configure({ keepers: KEPT });
  throughPick(r, 23, [19]);
  assert.equal(r.contiguous(), 24, "19 and 24 are kept: picks through 24 are known");
  assert.equal(r.nextMine(), 25);
  assert.equal(r.nextMine(), r.contiguous() + 1, "the title guard's test holds on my next pick");
  assert.equal(r.ingest("D|25|1|30", T0 + 300).turn, 25);
  assert.deepEqual(r.snapshot().keepers, [19, 24]);
  r.configure({ keepers: [] });
  assert.equal(r.isMine(24), true, "an emptied keeper table gives the slot back");
});

test("a pick the room never sent counts as known once the API has synced past it", () => {
  const r = room(1);
  throughPick(r, 23, [19]); // 19: a keeper the table does not know about
  assert.equal(r.contiguous(), 18, "the tracker alone stalls at the gap");
  r.synced({ synced_through: 18, waiting_for: 19 });
  assert.equal(r.contiguous(), 18);
  r.synced({ synced_through: 23, waiting_for: null }); // the API filled 19 with a stand-in
  assert.equal(r.contiguous(), 23);
  assert.equal(r.nextMine(), r.contiguous() + 1, "the title guard's test holds on my next pick");
  assert.deepEqual(r.unsent(), [], "nothing to resend: the gap has no pick to send");
});

// ---------------------------------------------------------------- league rooms: Yahoo team ids
// In a league room the draft path and every frame name a team by its Yahoo team id, which the
// mock lobby makes equal to the seat but a league does not. League 222017 (10 teams, 13 rounds,
// 2026-10-11): the user drew position 1 as team 10. Position -> team id in round 1:
const LEAGUE = [null, 10, 2, 9, 5, 8, 4, 1, 7, 6, 3];
const leagueRoom = (teamId = 10) => {
  const r = new RoomTracker({ draftId: "222017", teamId });
  r.configure({ numTeams: 10, rounds: 13 }); // what the attached room says
  return r;
};
/** The R| frame read as the team id on each overall: snake order over ``seats`` (position ->
 * team id), ``rounds`` rounds. */
const orderFrame = (seats, rounds = 13) => {
  const first = seats.slice(1);
  const out = [];
  for (let r = 1; r <= rounds; r++) out.push(...(r % 2 ? first : [...first].reverse()));
  return `R|${out.join("|")}|`;
};
const notes = (events, what) => events.filter((e) => e.type === "note" && e.what === what);

test("league room (2026-10-11 frames): the title places team 10 at pick 1, every frame is read by position", () => {
  const { roomFromPath, titlePosition } = require("../lib/protocol.js");
  const where = roomFromPath("/draftclient/nba/222017/10");
  const r = new RoomTracker({ draftId: where.draft_id, teamId: where.team });
  r.configure({ numTeams: 10, rounds: 13 });
  assert.equal(r.slot, null, "the path's 10 is the team id: no seat yet");
  assert.deepEqual(r.mine, []);
  assert.equal(r.nextMine(), null);
  assert.equal(r.fromTitle(titlePosition("You pick 1st | Live NBA Draft"), T0 - 60000), true);
  assert.equal(r.slot, 1);
  assert.deepEqual(r.mine.slice(0, 3), [1, 20, 21]);

  assert.equal(r.ingest("D|1|10|60", T0).turn, 1, "my first turn");
  const mine = r.ingest("0|1|5352|10|C|0", T0 + 30000);
  assert.equal(mine.landed.overall, 1, "pick 1 is mine");
  r.ingest("D|2|2|60", T0 + 30100);
  r.ingest("0|2|10094|2|C|0", T0 + 60000);
  assert.equal(r.ingest("D|3|9|60", T0 + 60100).turn, null);
  r.ingest("0|7|5185|1|C|0", T0 + 200000); // team 1 on pick 7: position 7
  assert.equal(r.ingest("D|20|10|60", T0 + 500000).turn, 20, "round 2 comes back to me at 20");
  r.ingest("X|29", T0 + 530000);
  r.ingest("5|10", T0 + 530010); // Yahoo picks for team 10: mine
  const twenty = r.ingest("0|20|6022|10|PG|0", T0 + 560000);
  assert.equal(r.landedEvent(twenty.landed).how, "expiry");
  assert.equal(r.ingest("D|21|10|60", T0 + 560100).turn, 21, "and at 21, back to back");
  assert.equal(r.teamsSeen(), 10, "the snake turns at 20 and 21 on position 1");

  assert.deepEqual(
    r.unsent().map((p) => [p.overall, p.slot]),
    [[1, 1], [2, 2], [7, 7], [20, 1]],
    "the API gets positions: my picks on 1, team 1's pick 7 on 7",
  );
  const events = r.takeEvents();
  const turns = events.filter((e) => e.type === "turn_start");
  assert.deepEqual(
    turns.map((e) => [e.overall, e.slot, e.team]),
    [[1, 1, 10], [2, 2, undefined], [3, 3, 9], [20, 1, 10], [21, 1, 10]],
    "turn_start says the position, and Yahoo's team id when it differs",
  );
  assert.deepEqual(
    notes(events, "seat").map((e) => [e.team, e.slot, e.src]),
    [[10, 1, "title"]],
  );
  assert.deepEqual(notes(events, "seat conflict"), [], "round 1 agrees with the title");
  assert.equal(r.snapshot().team_id, 10);
  assert.equal(r.snapshot().seat_src, "title");
});

test("league room with no title and no R|: the seat is found at my own round-1 turn", () => {
  const r = leagueRoom(5); // position 4
  for (let k = 1; k <= 3; k++) {
    assert.equal(r.ingest(`D|${k}|${LEAGUE[k]}|60`, T0 + k).turn, null);
    r.ingest(`0|${k}|${5000 + k}|${LEAGUE[k]}|C|0`, T0 + k + 1);
    assert.equal(r.slot, null);
    assert.equal(r.myTurnNow(), null);
  }
  r.ingest("5|5", T0 + 9); // nothing to say while the seat is unknown, and no error
  assert.equal(r.yahooMade.size, 0);
  const out = r.ingest("D|4|5|60", T0 + 10);
  assert.equal(out.seat, 4);
  assert.equal(out.turn, 4, "just in time");
  assert.equal(r.myTurnNow(), 4);
  assert.deepEqual(r.mine.slice(0, 3), [4, 17, 24]);
  assert.deepEqual(
    notes(r.takeEvents(), "seat").map((e) => [e.slot, e.src]),
    [[4, "frame"]],
  );
});

test("league room: a valid R| places every team before pick 1", () => {
  const r = leagueRoom(10);
  // The form league 222017 sent, 106 ms after entry (the drone's capture).
  assert.ok(orderFrame(LEAGUE).startsWith("R|10|2|9|5|8|4|1|7|6|3|3|6|7|1|4|8|5|9|2|10|10|2|"));
  const out = r.ingest(orderFrame(LEAGUE), T0);
  assert.equal(out.kind, "order");
  assert.equal(out.seat, 1);
  assert.equal(r.slot, 1);
  assert.deepEqual(r.order, { entries: 130, teams: 10 });
  for (let p = 1; p <= 10; p++) assert.equal(r.seatOf(LEAGUE[p]), p);
  assert.equal(r.ingest("D|1|10|60", T0 + 10).turn, 1);
  r.fromTitle(1, T0 + 20); // agrees
  const events = r.takeEvents();
  assert.deepEqual(notes(events, "seat").map((e) => e.src), ["order"]);
  assert.deepEqual(notes(events, "seat conflict"), []);
});

test("league room: an R| that does not check out is ignored, and round 1 places the seat", () => {
  for (const [frame, error] of [
    ["R|a|b|c|", "3 entries for 13 rounds"],
    [`R|${Array(130).fill("x").join("|")}|`, "not all integers"],
    [orderFrame([null, 10, 2, 9, 5, 8, 4, 1, 7, 6, 10]), "the first round repeats a team"],
    [orderFrame(LEAGUE).replace(/\|3\|$/, "|99|"), "a team outside the first round"],
    [orderFrame(LEAGUE).replace(/\|3\|$/, "|"), "129 entries for 13 rounds"],
  ]) {
    const r = leagueRoom(10);
    r.ingest(frame, T0);
    assert.equal(r.order.error, error, frame.slice(0, 30));
    assert.equal(r.slot, null);
    assert.equal(r.seats.size, 0);
    assert.equal(r.ingest("D|1|10|60", T0 + 10).turn, 1, "round 1 still finds it");
  }
});

test("league room: a round-1 frame overrides the title; the title after pick 1 is only noted", () => {
  const r = leagueRoom(10);
  r.fromTitle(2, T0); // a wrong reading
  assert.equal(r.slot, 2);
  const out = r.ingest("D|1|10|60", T0 + 10);
  assert.equal(out.seat, 1);
  assert.equal(out.turn, 1);
  const [conflict] = notes(r.takeEvents(), "seat conflict");
  assert.deepEqual(
    [conflict.team, conflict.position, conflict.src, conflict.kept, conflict.had],
    [10, 1, "frame", "new", [{ team: 10, position: 2, src: "title" }]],
  );
  r.ingest("0|1|5352|10|C|0", T0 + 20);
  assert.equal(r.fromTitle(19, T0 + 30), false, "once a pick is in, the title is not a seat");
  assert.equal(r.slot, 1);
  assert.deepEqual(
    notes(r.takeEvents(), "title seat").map((e) => [e.position, e.slot, e.last]),
    [[19, 1, 1]],
  );
  r.fromTitle(19, T0 + 40);
  assert.deepEqual(notes(r.takeEvents(), "title seat"), [], "each value once");
});

test("league room: a team placed late puts its position on the picks already kept", () => {
  const r = leagueRoom(10);
  r.ingest("P|1=5352,10,0|2=10094,2,0|", T0); // a reconnect: history, round 1 so far
  assert.equal(r.slot, 1);
  r.ingest("0|16|7001|8|C|0", T0 + 10); // team 8 (position 5) before anything placed it
  assert.equal(r.unsent().find((p) => p.overall === 16).slot, null, "the API falls back to the snake owner");
  r.ingest(orderFrame(LEAGUE), T0 + 20);
  assert.equal(r.unsent().find((p) => p.overall === 16).slot, 5, "R| placed team 8 at 5");
  assert.equal(r.owners.get(16), 5);
});

test("mock room (team ids = seats): seats learned from the room match a tracker told its seat", () => {
  const { pickOwner } = require("../lib/protocol.js");
  const ids = [null, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
  const frames = [];
  for (let k = 1; k <= 40; k++) {
    const s = pickOwner(12, k).slot;
    frames.push(`D|${k}|${s}|30`, `0|${k}|${5000 + k}|${s}|C|0`);
  }
  for (const order of [true, false]) {
    const told = new RoomTracker({ draftId: "m", slot: 3 });
    const learned = new RoomTracker({ draftId: "m", teamId: 3 });
    const outs = [[], []];
    if (order) for (const r of [told, learned]) r.ingest(orderFrame(ids), T0);
    frames.forEach((f, i) => {
      outs[0].push(told.ingest(f, T0 + i).turn);
      outs[1].push(learned.ingest(f, T0 + i).turn);
    });
    assert.deepEqual(outs[1], outs[0], `turns, R| ${order}`);
    const strip = (es) => es.filter((e) => e.type !== "note");
    assert.deepEqual(strip(learned.takeEvents()), strip(told.takeEvents()), `events, R| ${order}`);
    assert.deepEqual(learned.unsent(), told.unsent());
    assert.equal(learned.teamsSeen(), 12);
    assert.equal(learned.slot, 3);
  }
});
