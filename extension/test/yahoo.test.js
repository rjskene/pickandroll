// node --test extension/test/*.test.js
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const Y = require("../lib/yahoo.js");

const rows = [
  { id: "5352", text: "N. Jokić DEN - C  1.2" },
  { id: "4612", text: "S. Curry GSW - PG  9.8" },
  { id: "4613", text: "S. Curry GSW - PG  210.0" }, // Seth: same initial, last name and team
  { id: "6515", text: "T. Haliburton IND - PG" }, // a headshot id that is not the Yahoo id
  { id: "10465", text: "M. Buzelis CHI - SF,PF" },
  { id: "6702", text: "J. Williams OKC - SF" },
];
const cand = (yahoo_player_id, ini, last, team) => ({ yahoo_player_id, ini, last, team });

test("the headshot id finds the row when the row also names the player", () => {
  assert.equal(Y.matchRow(rows, cand("5352", "N", "Jokic", "DEN")), 0);
  assert.equal(Y.matchRow(rows, cand("4612", "S", "Curry", "GSW")), 1);
  assert.equal(Y.matchRow(rows, cand("4613", "S", "Curry", "GSW")), 2);
});

test("a row whose image id differs is found by name and team", () => {
  assert.equal(Y.matchRow(rows, cand("6512", "T", "Haliburton", "IND")), 3);
  assert.equal(Y.matchRow(rows, cand("10265", "M", "Buzelis", "CHI")), 4);
});

test("an image id with another player's name is not a match", () => {
  const swapped = [{ id: "6702", text: "K. Durant HOU - SF" }, ...rows.slice(0, 5)];
  assert.equal(Y.matchRow(swapped, cand("6702", "J", "Williams", "OKC")), -1);
});

test("no row: -1", () => {
  assert.equal(Y.matchRow(rows, cand("9999", "D", "Smith", "WAS")), -1);
  assert.equal(Y.matchRow([], cand("5352", "N", "Jokic", "DEN")), -1);
});

test("Draft labels: bare, naming the player, naming someone else", () => {
  const c = cand("5352", "N", "Jokic", "DEN");
  assert.ok(Y.labelNames("Draft", c));
  assert.ok(Y.labelNames("Draft Nikola Jokić", c));
  assert.ok(!Y.labelNames("Draft Jamal Murray", c));
  assert.ok(Y.isDraftLabel("Draft"));
  assert.ok(Y.isDraftLabel(" draft Nikola Jokic"));
  assert.ok(!Y.isDraftLabel("Autodraft"));
  assert.ok(!Y.isDraftLabel("Drafted"));
});

test("headshot URLs", () => {
  assert.equal(Y.imageId("https://s.yimg.com/iu/api/res/1.2/x/players_l/20251015/10094.png"), "10094");
  assert.equal(Y.imageId("https://x/players/6515.1.png?w=40"), "6515");
  assert.equal(Y.imageId("https://x/logo.svg"), null);
});

test("candidates drop taken players and duplicates", () => {
  const plan = { candidates: [{ yahoo_player_id: 1 }, { yahoo_player_id: "2" }, { yahoo_player_id: "1" }, { yahoo_player_id: 3 }] };
  assert.deepEqual(
    Y.candidatesFor(plan, new Set(["2"])).map((c) => c.yahoo_player_id),
    ["1", "3"],
  );
  assert.deepEqual(Y.candidatesFor(null, new Set()), []);
});

test("a queue control is one labelled as the queue's, never a Draft or an unlabelled one", () => {
  assert.equal(Y.isQueueControl(["Add to Queue", "", ""]), true);
  assert.equal(Y.isQueueControl([null, "Add Nikola Jokić to queue", ""]), true);
  assert.equal(Y.isQueueControl(["Add to draft queue"]), true); // names the queue, not a Draft label
  assert.equal(Y.isQueueControl(["", "", ""]), false); // unlabelled
  assert.equal(Y.isQueueControl([null, null, "★"]), false);
  assert.equal(Y.isQueueControl(["Draft Nikola Jokić"]), false);
  assert.equal(Y.isQueueControl(["Draft", "Add to queue"]), false); // any Draft label refuses it
});

test("a probe on a Draft control that lands nothing is a dropped click; failed is the star's", () => {
  assert.equal(Y.probeOutcome(true, false, ["Draft"]), "drafted");
  assert.equal(Y.probeOutcome(false, true, ["Add to Queue"]), "queued");
  assert.equal(Y.probeOutcome(false, false, ["Draft", "Draft Nikola Jokić"]), "dropped");
  assert.equal(Y.probeOutcome(false, false, ["Add to Queue"]), "failed");
  assert.equal(Y.probeOutcome(false, false, ["", "", ""]), "failed"); // an unlabelled star
});

test("a queue entry is removed only through a control labelled remove or queue, never Draft", () => {
  assert.equal(Y.isRemoveControl(["Remove", "", ""]), true);
  assert.equal(Y.isRemoveControl([null, "Remove Nikola Jokić from queue", ""]), true);
  assert.equal(Y.isRemoveControl(["", "Delete", ""]), true);
  assert.equal(Y.isRemoveControl(["", "", ""]), false); // unlabelled: the old positional pick
  assert.equal(Y.isRemoveControl([null, null, "×"]), false);
  assert.equal(Y.isRemoveControl(["Draft"]), false);
  assert.equal(Y.isRemoveControl(["Draft", "Remove from queue"]), false); // any Draft label refuses it
});

test("the drafter's own Autodraft switch leaves the seat armed; only Yahoo's flip is autopick", () => {
  const off = { autopick: false, reason: null, note: "autodraft off" };
  assert.equal(Y.autodraftSeen(false, false), null);
  assert.equal(Y.autodraftSeen(true, null), null); // switch not found: nothing changes
  assert.deepEqual(Y.autodraftSeen(false, true, { ours: true }), {
    autopick: false,
    reason: "autodraft by pickandroll",
    note: "autodraft on by pickandroll",
  });
  assert.deepEqual(Y.autodraftSeen(true, false, { ours: true }), off);
  assert.deepEqual(Y.autodraftSeen(false, true), { autopick: true, reason: "autopick", note: "autodraft on by Yahoo" });
  assert.deepEqual(Y.autodraftSeen(false, true, { byHand: true }), {
    autopick: true,
    reason: "autodraft by hand",
    note: "autodraft on by hand",
  });
  assert.equal(Y.autodraftSeen(null, true).reason, "autodraft at entry");
  assert.equal(Y.autodraftSeen(null, true).autopick, true);
  assert.equal(Y.autodraftSeen(null, false).autopick, null); // off at entry: nothing to report
});

test("the guard leaves a hand-set Autodraft and its queue alone", () => {
  const g = (o) => Y.guardActions(o);
  // Yahoo's flip after a missed pick: switch off, then the queue.
  assert.deepEqual(g({ on: true, reason: "autopick", queued: 1 }), { autodraftOff: true, clearQueue: true });
  // The user's own: on by hand, or on at entry. Neither is touched.
  assert.deepEqual(g({ on: true, reason: "autodraft by hand", queued: 2 }), { autodraftOff: false, clearQueue: false });
  assert.deepEqual(g({ on: true, reason: "autodraft at entry", queued: 1 }), { autodraftOff: false, clearQueue: false });
  // A backstop switch a turn could not undo: off, then its queue.
  assert.deepEqual(g({ on: true, reason: "autodraft by pickandroll", ours: true, queued: 1 }), {
    autodraftOff: true,
    clearQueue: true,
  });
  // Switch off: a leftover queue is emptied (we queue only for the pick on the clock).
  assert.deepEqual(g({ on: false, reason: null, queued: 1 }), { autodraftOff: false, clearQueue: true });
  assert.deepEqual(g({ on: false, reason: null, queued: 0 }), { autodraftOff: false, clearQueue: false });
});
