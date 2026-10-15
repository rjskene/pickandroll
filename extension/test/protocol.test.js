// node --test extension/test
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const P = require("../lib/protocol.js");

test("draft id and my Yahoo team id come from the draft-client path", () => {
  assert.deepEqual(P.roomFromPath("/draftclient/nba/2515267/1"), { draft_id: "2515267", team: 1 });
  assert.deepEqual(P.roomFromPath("/draftclient/nba/2514980/12/"), { draft_id: "2514980", team: 12 });
  // A league room: team 10 drew position 1 (league 222017); the path says the team.
  assert.deepEqual(P.roomFromPath("/draftclient/nba/222017/10"), { draft_id: "222017", team: 10 });
  assert.equal(P.roomFromPath("/nba/mock_lobby"), null);
  assert.equal(P.roomFromPath("/draftclient/nba/2515267"), null);
  assert.equal(P.roomFromPath("/draftclient/nba/2515267/0"), null);
});

test("pick, history, on-deck, clock and order frames", () => {
  assert.deepEqual(P.parseMessage("0|1|10094|1|C|0"), {
    kind: "pick",
    overall: 1,
    yid: "10094",
    team: 1,
    pos: "C",
  });
  assert.deepEqual(P.parseMessage("0|132|4622|12|PG|0"), {
    kind: "pick",
    overall: 132,
    yid: "4622",
    team: 12,
    pos: "PG",
  });
  assert.deepEqual(P.parseMessage("P|1=10094,1,0|2=5352,2,0|3=6014,3,0|"), {
    kind: "history",
    picks: [
      { overall: 1, yid: "10094", team: 1 },
      { overall: 2, yid: "5352", team: 2 },
      { overall: 3, yid: "6014", team: 3 },
    ],
  });
  assert.deepEqual(P.parseMessage("D|133|12|30"), { kind: "on_deck", overall: 133, team: 12, clock: 30 });
  assert.deepEqual(P.parseMessage("C|24"), { kind: "clock", clock: 24 });
  assert.deepEqual(P.parseMessage("R|a|b|c|"), { kind: "order", order: ["a", "b", "c"] });
  assert.deepEqual(P.parseMessage("X|29"), { kind: "auto_warn", value: 29 });
  assert.deepEqual(P.parseMessage("5|7"), { kind: "auto", team: 7 });
  assert.equal(P.parseMessage("5|x"), null);
});

test("frames the extension does not use, and malformed ones, parse to null", () => {
  for (const f of ["", "x", "8|2515267|1|Mozilla", "0|x|10094|1|C|0", "0|1||1|C|0", "D|1", "C|", "Z|1|2", null, 42]) {
    assert.equal(P.parseMessage(f), null, String(f));
  }
  assert.deepEqual(P.parseMessage("P|"), { kind: "history", picks: [] });
});

test("the title gives my seat only in its 'You pick Nth' form", () => {
  assert.equal(P.titlePosition("You pick 1st | Live NBA Draft"), 1);
  assert.equal(P.titlePosition("You pick 4th | Live NBA Draft"), 4);
  assert.equal(P.titlePosition("you pick 12th"), 12);
  assert.equal(P.titlePosition("YOUR TURN, DRAFT NOW"), null);
  assert.equal(P.titlePosition("Live NBA Draft"), null);
  assert.equal(P.titlePosition("You pick 0th"), null);
  assert.equal(P.titlePosition("You pick 21st"), null);
  assert.equal(P.titlePosition(""), null);
  assert.equal(P.titlePosition(undefined), null);
});

test("the R| frame gives each team's position only when it checks out", () => {
  const snake = (first, rounds) => {
    const out = [];
    for (let r = 1; r <= rounds; r++) out.push(...(r % 2 ? first : [...first].reverse()));
    return out.map(String);
  };
  const league = [10, 2, 9, 5, 8, 4, 1, 7, 6, 3];
  assert.deepEqual(P.orderSeats(snake(league, 13), 13), {
    teams: 10,
    seats: league.map((t, i) => [t, i + 1]),
    owners: snake(league, 13).map(Number),
    traded: 0,
  });
  assert.equal(P.orderSeats(snake([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], 13), 13).teams, 12);
  assert.match(P.orderSeats(["a", "b", "c"], 13).error, /3 entries/);
  assert.match(P.orderSeats([], 13).error, /0 entries/);
  assert.match(P.orderSeats(snake([1], 13), 13).error, /1 teams/);
  assert.match(P.orderSeats(snake(league, 13).slice(1), 13).error, /129 entries/);
  assert.match(P.orderSeats(snake([1, 2, 3, 3], 13), 13).error, /3 teams in 4 x 13 entries/);
  const stray = snake(league, 13);
  stray[50] = "11";
  assert.match(P.orderSeats(stray, 13).error, /11 teams in 10 x 13 entries/);
  const text = snake(league, 13);
  text[0] = "t10";
  assert.match(P.orderSeats(text, 13).error, /integers/);
});

// The shape of the 2026-10-14 draft (tests/fixtures/traded_picks_12.json): 12 teams, 13 rounds,
// ten picks on another position's snake slot. Position -> team id is a fixed shuffle.
const TEAM_OF = [null, 7, 3, 12, 1, 9, 5, 11, 2, 10, 4, 8, 6];
const TRADES = { 28: 1, 45: 1, 144: 4, 145: 4, 55: 10, 106: 7, 36: 5, 68: 12, 122: 6, 88: 3 };
const tradedOrder = (teamOf = TEAM_OF, trades = TRADES, teams = 12, rounds = 13) => {
  const out = [];
  for (let k = 1; k <= teams * rounds; k++) out.push(String(teamOf[trades[k] || P.pickOwner(teams, k).slot]));
  return out;
};

test("the R| frame of a league with traded picks: a round repeats a team, every pick has its owner", () => {
  const r = P.orderSeats(tradedOrder(), 13);
  assert.equal(r.error, undefined);
  assert.equal(r.teams, 12);
  assert.equal(r.traded, 10);
  assert.deepEqual(r.seats, TEAM_OF.slice(1).map((t, i) => [t, i + 1]), "positions by each team's usual slot");
  assert.equal(r.owners.length, 156);
  assert.equal(r.owners[27], TEAM_OF[1], "pick 28 is position 1's");
  assert.equal(r.owners[144], TEAM_OF[4], "pick 145 is position 4's");
  assert.equal(r.owners[3], TEAM_OF[4]);
  // Round 3 names team TEAM_OF[1] twice (picks 25 and 28) and team TEAM_OF[4] not at all.
  const round3 = r.owners.slice(24, 36);
  assert.equal(round3.filter((t) => t === TEAM_OF[1]).length, 2);
  assert.equal(round3.includes(TEAM_OF[4]), false);
});

test("the R| frame is refused when a team has no usual slot, or two teams share one", () => {
  // 2 teams x 2 rounds: team 1 on picks 1 and 3 (slots 1 and 2): a tie.
  assert.match(P.orderSeats(["1", "2", "1", "2"], 2).error, /team 1 has no settled position/);
  // 4 teams x 3 rounds: team 1 mostly on slot 1 (picks 1, 9), team 2 only on pick 8 (slot 1).
  assert.match(P.orderSeats(["1", "3", "4", "1", "3", "4", "3", "2", "1", "3", "4", "3"], 3).error, /position 1 is held by two teams/);
});

test("the hello frame gives the team id and nothing else", () => {
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
