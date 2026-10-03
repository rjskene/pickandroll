// node --test extension/test
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const P = require("../lib/protocol.js");

test("draft id and slot come from the draft-client path", () => {
  assert.deepEqual(P.roomFromPath("/draftclient/nba/2515267/1"), { draft_id: "2515267", slot: 1 });
  assert.deepEqual(P.roomFromPath("/draftclient/nba/2514980/12/"), { draft_id: "2514980", slot: 12 });
  assert.equal(P.roomFromPath("/nba/mock_lobby"), null);
  assert.equal(P.roomFromPath("/draftclient/nba/2515267"), null);
  assert.equal(P.roomFromPath("/draftclient/nba/2515267/0"), null);
});

test("pick, history, on-deck, clock and order frames", () => {
  assert.deepEqual(P.parseMessage("0|1|10094|1|C|0"), {
    kind: "pick",
    overall: 1,
    yid: "10094",
    slot: 1,
    pos: "C",
  });
  assert.deepEqual(P.parseMessage("0|132|4622|12|PG|0"), {
    kind: "pick",
    overall: 132,
    yid: "4622",
    slot: 12,
    pos: "PG",
  });
  assert.deepEqual(P.parseMessage("P|1=10094,1,0|2=5352,2,0|3=6014,3,0|"), {
    kind: "history",
    picks: [
      { overall: 1, yid: "10094", slot: 1 },
      { overall: 2, yid: "5352", slot: 2 },
      { overall: 3, yid: "6014", slot: 3 },
    ],
  });
  assert.deepEqual(P.parseMessage("D|133|12|30"), { kind: "on_deck", overall: 133, slot: 12, clock: 30 });
  assert.deepEqual(P.parseMessage("C|24"), { kind: "clock", clock: 24 });
  assert.deepEqual(P.parseMessage("R|a|b|c|"), { kind: "order", order: ["a", "b", "c"] });
  assert.deepEqual(P.parseMessage("X|29"), { kind: "auto_warn", value: 29 });
  assert.deepEqual(P.parseMessage("5|7"), { kind: "auto", slot: 7 });
  assert.equal(P.parseMessage("5|x"), null);
});

test("frames the extension does not use, and malformed ones, parse to null", () => {
  for (const f of ["", "x", "8|2515267|1|Mozilla", "0|x|10094|1|C|0", "0|1||1|C|0", "D|1", "C|", "Z|1|2", null, 42]) {
    assert.equal(P.parseMessage(f), null, String(f));
  }
  assert.deepEqual(P.parseMessage("P|"), { kind: "history", picks: [] });
});

test("the hello frame gives the slot and nothing else", () => {
  assert.equal(P.parseHello("8|31822|7|Mozilla%2F5.0|x"), 7);
  assert.equal(P.parseHello("8|31822|x|y"), null);
  assert.equal(P.parseHello("0|1|10094|1|C|0"), null);
});

test("snake picks match draft.settings.snake_picks", () => {
  assert.deepEqual(P.snakePicks(12, 1, 13), [1, 24, 25, 48, 49, 72, 73, 96, 97, 120, 121, 144, 145]);
  assert.deepEqual(P.snakePicks(12, 12, 4), [12, 13, 36, 37]);
  assert.deepEqual(P.snakePicks(12, 6, 3), [6, 19, 30]);
  assert.throws(() => P.snakePicks(12, 13, 13), RangeError);
});

test("pick owner matches draft.settings.pick_owner and inverts snakePicks", () => {
  assert.deepEqual(P.pickOwner(12, 1), { round: 1, slot: 1 });
  assert.deepEqual(P.pickOwner(12, 13), { round: 2, slot: 12 });
  assert.deepEqual(P.pickOwner(12, 24), { round: 2, slot: 1 });
  assert.deepEqual(P.pickOwner(12, 156), { round: 13, slot: 12 });
  for (let slot = 1; slot <= 12; slot++) {
    for (const k of P.snakePicks(12, slot, 13)) assert.equal(P.pickOwner(12, k).slot, slot);
  }
  assert.throws(() => P.pickOwner(12, 0), RangeError);
});
