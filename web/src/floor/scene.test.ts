// The floor's scene (#461) on the sample week: stages, lamps, tokens, one league's roster, the
// belt's knobs, the ledger and the stage links into Explain.
import assert from "node:assert/strict";
import { test } from "node:test";
import { formatHash, parseHash } from "../explain/nav.ts";
import { TRACKS } from "../explain/tracks/index.ts";
import { floorAt, timeline } from "./model.ts";
import { PRIVATE, PUBLIC, sampleRoster, sampleWeek } from "./sample.ts";
import { FLOW, FLOW_EXPLAIN, knobs, ledgerAt, rosterAt, sceneAt, type LeagueRow } from "./scene.ts";

const w = sampleWeek();
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
