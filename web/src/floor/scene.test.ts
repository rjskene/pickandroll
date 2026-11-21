// The floor's scene (#461) on the sample week: stages, lamps, tokens, one league's roster, the
// belt's knobs, the ledger and the stage links into Explain.
import assert from "node:assert/strict";
import { test } from "node:test";
import { formatHash, parseHash } from "../explain/nav.ts";
import { TRACKS } from "../explain/tracks/index.ts";
import { floorAt, timeline } from "./model.ts";
import { PRIVATE, PUBLIC, sampleRoster, sampleWeek } from "./sample.ts";
import { BELT_Y, FLOW, FLOW_EXPLAIN, H, HUB, RAIL_Y, SITES, W, W_MAX, knobs, layout, ledgerAt, rosterAt, sceneAt, sceneWidth, type LeagueRow } from "./scene.ts";

const w = sampleWeek();
const w0 = w;
const tl = timeline({ runs: w.runs, queues: w.queues, seasons: w.seasons, now: w.liveAt });
const leagues: LeagueRow[] = w.seasons.map((s) => ({ league: s.league, mine: s.league === PRIVATE, adds: { used: 1, limit: 4 }, budget: s.league === PRIVATE ? null : 80 }));
const at = (t: number, one: string | null = null) =>
  sceneAt({ tl, t, age: (x) => (t - x) / 1000, now: 0, leagues, one, executeTime: "09:15", roster: one ? sampleRoster(one) : null, claims: true });

test("every stage number opens an Explain step that exists (#461)", () => {
  assert.equal(FLOW_EXPLAIN.length, FLOW.length);
  for (const [k, x] of FLOW_EXPLAIN.entries()) {
    const track = TRACKS.find((tr) => tr.id === x.track);
    assert.ok(track, x.track);
    const step = track.steps.findIndex((s) => s.id === x.step);
    assert.ok(step >= 0, `stage ${k + 1}: ${x.track}/${x.step}`);
    const hash = formatHash({ track: x.track, step }, TRACKS);
    assert.deepEqual(parseHash(hash, TRACKS), { track: x.track, step }, hash);
  }
});

test("the live moment: the morning pass's last claim out and back, every lamp solved, a dock a league (#461)", () => {
  const s = at(w.liveAt);
  assert.equal(s.stage, 7);
  assert.equal(s.docks.length, w.seasons.length);
  assert.equal(s.court, null);
  assert.ok(s.lamps.every((l) => l.state === "solved"));
  assert.equal(s.now.title, "morning pass");
  assert.equal(s.now.agent, "mover");
  const doing = s.tokens.filter((x) => x.state === "doing");
  assert.equal(doing.length, 1);
  assert.match(doing[0].id, /^2026-11-20:900106:/);
  assert.ok(doing[0].p > 0 && doing[0].p < 1);
  // the day's holds stay at their rules' bays, never on the way out
  assert.ok(s.tokens.filter((x) => x.state === "held").length >= 3);
});

test("before the Thursday pass the floor is at rest and names the next timer (#461)", () => {
  const s = at(w.demoAt);
  assert.equal(s.now.title, "Idle");
  assert.match(s.now.line, /morning pass, Thu Nov 19 09:15/);
  assert.equal(s.days.find((d) => d.on)?.date, "2026-11-19");
  assert.ok(s.days[0].tally.claimed > 0);
});

test("one league: its roster replaces the docks, the claim under way marks its slot, a landed claim takes it (#461)", () => {
  const one = PUBLIC[5];
  const s = at(w.liveAt, one);
  assert.equal(s.docks.length, 0);
  assert.ok(s.court);
  assert.equal(s.court.league, one);
  assert.equal(s.court.tiles.length, 16);
  const e = tl.entries.find((x) => x.league === one && x.date === "2026-11-20");
  assert.ok(e && e.outcomeAt !== null);
  assert.equal(s.court.tiles.find((x) => x.name === e.dropName)?.state, "target");
  // after the claim lands the add stands in the drop's slot
  const later = e.outcomeAt + 1000;
  const f = floorAt(tl, later);
  const tiles = rosterAt(sampleRoster(one), tl.entries.filter((x) => x.league === one), later, (x) => (later - x) / 1000, f.pass, f.unit);
  const slot = sampleRoster(one).findIndex((r) => r.name === e.dropName);
  assert.equal(tiles[slot].name, e.addName);
  assert.equal(tiles[slot].state, "new");
  assert.ok(!tiles.some((x) => x.name === e.dropName));
});

test("the belt's knobs read the leagues' rules: a shared value, one league's, else by league (#461)", () => {
  const rules = w.queues.find((q) => q.date === "2026-11-20")?.settings.rules ?? {};
  const all = knobs(rules, null, null);
  assert.equal(all.day_cap, "2 a day");
  assert.equal(all.recut, "added in 3 days");
  assert.equal(all.no_adds, "the week's limit");
  assert.equal(knobs(rules, PUBLIC[0], { used: 2, limit: 4 }).no_adds, "2 of 4 used");
  const [a, b] = Object.keys(rules);
  const split = { ...rules, [b]: { ...rules[b], recut_days: rules[a].recut_days + 2 } };
  assert.equal(knobs(split, null, null).recut, "by league");
  assert.equal(knobs({}, null, null).recut, "");
});

test("the ledger: the seven latest results and holds by the moment, newest first, one league's alone (#461)", () => {
  const rows = ledgerAt(tl, w.liveAt, null);
  assert.equal(rows.length, 7);
  assert.match(rows[0].text, /^claimed · /);
  assert.ok(rows.some((r) => r.cls === "held"));
  const one = ledgerAt(tl, w.liveAt, PUBLIC[0]);
  assert.ok(one.length > 0 && one.every((r) => r.text.includes(PUBLIC[0])));
  // nothing from after the moment
  assert.ok(!ledgerAt(tl, w.demoAt, null).some((r) => r.at.startsWith("Fri")));
});

test("the layout at 1280 is the mock-up's geometry exactly (#470)", () => {
  const L = layout(1280);
  assert.equal(L.w, 1280);
  assert.deepEqual(L.gate, { x: 850, y: 250 });
  assert.equal(L.dockX, 1046);
  assert.equal(L.rackX, 888);
  assert.deepEqual(L.room, { rest: 36, y: 526, line: 556, up: 540, over: 424, gx: 868, ledger: 552 });
  for (let k = 0; k < 7; k++) {
    assert.equal(L.ruleX(k), 344 + k * 66);
    assert.equal(L.dayX(k), 14 + k * 179.3);
    assert.equal(L.flowX(k), 20 + k * 141);
  }
  assert.equal(L.dayW, 172);
  assert.deepEqual(L.pins, [[94, 445], [192, 374], [231, 221], [317, 272], [808, 231], [880, 200], [902, 268]]);
  assert.deepEqual([L.courtX, L.laneOne, L.subMax, L.chipX], [1000, 994, 1180, 650]);
  assert.deepEqual([W, H, HUB, BELT_Y, RAIL_Y], [1280, 612, { x: 262, y: 250 }, 250, 374]);
  // and below 1280 the scene stays 1280 (it scales to a narrower box), above the cap it stops
  assert.equal(layout(900).w, 1280);
  assert.equal(layout(3000).w, W_MAX);
});

test("wider, the belt stretches, the docks stay pinned right and nothing leaves the drawing (#470)", () => {
  const base = layout(1280);
  for (const w of [1600, 2000]) {
    const L = layout(w);
    assert.equal(L.w, w);
    // the docks' and the card's right margin is unchanged
    assert.equal(L.w - (L.dockX + 220), 1280 - (base.dockX + 220));
    assert.equal(L.w - (L.courtX + 266), 1280 - (base.courtX + 266));
    // the week strip spans the width, at the same margins
    assert.equal(L.dayX(0), 14);
    assert.ok(Math.abs(L.w - (L.dayX(6) + L.dayW) - (1280 - (base.dayX(6) + base.dayW))) < 1e-9);
    // every box inside [0, w]
    for (const x of [L.gate.x, L.rackX, L.room.gx, L.room.ledger + 300, L.dockX + 220, L.courtX + 266, L.subMax, L.flowX(6) + 141, ...L.pins.map((p) => p[0])]) {
      assert.ok(x > 0 && x <= L.w, `${w}: ${x}`);
    }
    // the rules spread, never closer than at 1280, and the gate stands clear of the last one
    for (let k = 1; k < 7; k++) assert.ok(L.ruleX(k) - L.ruleX(k - 1) >= 66);
    assert.ok(L.gate.x - L.ruleX(6) >= base.gate.x - base.ruleX(6));
    // the gate, the rack and the ledger move with the belt; the lanes keep room to the docks
    assert.ok(L.gate.x > base.gate.x && L.rackX - L.gate.x === base.rackX - base.gate.x);
    assert.ok(L.dockX - L.gate.x >= base.dockX - base.gate.x);
    assert.ok(L.room.ledger + 300 < L.dockX);
    // the left column is unmoved
    assert.equal(L.ruleX(0), base.ruleX(0));
    assert.deepEqual(L.pins.slice(0, 4), base.pins.slice(0, 4));
    assert.deepEqual([L.room.rest, L.room.y, L.room.line, L.room.up, L.room.over], [36, 526, 556, 540, 424]);
    assert.deepEqual(SITES.map((x) => x.x0), [56, 232, 374]);
  }
});

test("the scene's width follows the stage box: never under 1280, capped at 2048 (#470)", () => {
  assert.equal(sceneWidth(1000, 700), 1280);
  assert.equal(sceneWidth(1952, 700), Math.round((612 * 1952) / 700));
  assert.equal(sceneWidth(4000, 600), W_MAX);
  assert.equal(sceneWidth(0, 0), 1280);
});

test("a wide scene keeps the agents and entries on the drawing: the lanes end at the pinned docks (#470)", () => {
  for (const w of [1600, 2000]) {
    const t = w === 1600 ? w0.liveAt : w0.demoAt;
    const s = sceneAt({ tl, t, age: (x) => (t - x) / 1000, now: 0, leagues, one: null, w, executeTime: "09:15" });
    assert.equal(s.L.w, w);
    assert.ok(s.lanes.every((l) => l.x1 === s.L.dockX - 8));
    for (const p of [...s.tokens, ...s.agents, ...s.chips, ...s.steps3]) assert.ok(p.x >= 0 && p.x <= w, `${w}: ${p.x}`);
    assert.ok(s.gates.every((g, k) => g.x === s.L.ruleX(k)));
  }
  const one = sceneAt({ tl, t: w0.liveAt, age: (x) => (w0.liveAt - x) / 1000, now: 0, leagues, one: PUBLIC[5], w: 2000, executeTime: "09:15", roster: sampleRoster(PUBLIC[5]), claims: true });
  assert.ok(one.tokens.every((p) => p.x <= 2000));
  assert.equal(one.L.courtX + 266, 2000 - 14);
});
