// The live floor's reads (#462): the pace of the polling, the week's past days, and a run in
// flight drawn on the floor's scene from a live progress file.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { RoutineLivePayload } from "../api.ts";
import { GLOSSARY, termById } from "../explain/terms.ts";
import { termHash, termOfHash, parseHash } from "../explain/nav.ts";
import { TRACKS } from "../explain/tracks/index.ts";
import { AGENTS, centralDate, timeline } from "./model.ts";
import { POLL, inFlight, livePoll, weekQueueDays } from "./live.ts";
import { FLOW, FLOW_TERMS, sceneAt } from "./scene.ts";

const liveOf = (stale: boolean, progress = true): RoutineLivePayload => ({
  now: "2026-11-21T04:41:00Z",
  live: [
    {
      routine: "evening",
      file: "evening.json",
      written_at: "2026-11-21T04:40:30Z",
      stale,
      reason: null,
      progress: progress
        ? {
            routine: "evening",
            started_at: "2026-11-21T04:40:00Z",
            written_at: "2026-11-21T04:40:30Z",
            current: { name: "moves", after: "fresh_reads", started: "2026-11-21T04:40:30Z" },
            steps: [{ name: "fresh_reads", status: "ok", detail: "3 leagues read", started: "2026-11-21T04:40:00Z", finished: "2026-11-21T04:40:30Z" }],
          }
        : null,
    },
  ],
});

test("the floor polls every few seconds while a run or a pass is in flight, once a minute at rest (#462)", () => {
  assert.equal(livePoll(null, null), POLL.rest);
  assert.equal(livePoll({ now: "", live: [] }, { active: null }), POLL.rest);
  assert.equal(livePoll(liveOf(false), null), POLL.busy);
  // a stale file is a killed run, not one in flight; a file that does not read is none either
  assert.equal(livePoll(liveOf(true), null), POLL.rest);
  assert.equal(livePoll(liveOf(false, false), null), POLL.rest);
  assert.equal(inFlight(null, { active: { id: "p" } as never }), true);
});

test("the floor reads every day of the Central week to today that the page's queue (the NBA day) does not cover (#468)", () => {
  const ct = (s: string) => Date.parse(`${s}-06:00`);
  // the page's queue is the NBA (Eastern) day: from 23:00 Central it is already tomorrow's
  const nbaDay = (t: number) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date(t));
  const days = (at: string) => {
    const t = ct(at);
    return weekQueueDays(centralDate(t), nbaDay(t));
  };
  // Friday 22:59: the page's queue is Friday's, the floor reads Monday to Thursday
  assert.deepEqual(days("2026-11-20T22:59"), ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"]);
  // Friday 23:01: the page's queue is Saturday's, so the floor reads Friday too
  assert.equal(nbaDay(ct("2026-11-20T23:01")), "2026-11-21");
  assert.deepEqual(days("2026-11-20T23:01"), ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]);
  // Sunday 22:59: Monday to Saturday; Sunday 23:01, the page on next Monday: the whole week
  assert.deepEqual(days("2026-11-22T22:59"), ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"]);
  assert.deepEqual(days("2026-11-22T23:01"), ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"]);
  // Monday 23:01 starts the next week: Monday's own queue only
  assert.deepEqual(days("2026-11-23T23:01"), ["2026-11-23"]);
  // before the page's queue answers, only the days before today
  assert.deepEqual(weekQueueDays("2026-11-20", null), ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"]);
  assert.deepEqual(weekQueueDays("2026-11-16", null), []);
});

test("at 23:01 Central Friday's moves stay on the floor: its tally, its ledger and the hub (#468)", () => {
  const ct = (s: string) => Date.parse(`${s}-06:00`);
  const t = ct("2026-11-20T23:01");
  const settings = { execute_time: "09:00", at: null, by: null, set: false, sunday_execute_time: null, sunday_at: null, sunday_by: null, in_force: "09:00" };
  const base = { execute_time: "09:00", leagues: [], settings, stop: false, now: "2026-11-21T05:01:00Z", names: { "7001": "Ari Vance", "7002": "Bo Lindqvist" } };
  const e = (id: string, over: Record<string, unknown>) => ({
    id, date: "2026-11-20", league: "900101", scoring: "categories", set: "three", decision: null, add: 7001, drop: 7002, from: null, availability: "W", judged: "three",
    gain: 0.4, value: 0.4, season: 0.1, season_costly: false, flag: null, floor: null, bid: { amount: 2 }, queued: true, reason: null, rank: null,
    queued_at: "2026-11-21T03:20:08Z", executes_at: "2026-11-21T04:20:08Z", struck: false, bid_struck: false, outcome: null, outcome_reason: null, outcome_at: null, resolved: null, ...over,
  });
  const friday = { ...base, date: "2026-11-20", built: ["2026-11-20T11:42:07Z"], entries: [e("a", { outcome: "claimed", outcome_at: "2026-11-21T04:40:51Z" }), e("b", { executes_at: "2026-11-21T15:00:00Z" })] } as never;
  const saturday = { ...base, date: "2026-11-21", built: [], entries: [] } as never;
  const scene = (queues: unknown[]) => sceneAt({ tl: timeline({ queues: queues as never, now: t }), t, age: (x) => (t - x) / 1000, now: 0, leagues: [], one: null, executeTime: "09:00" });
  const fixed = scene([friday, saturday]);
  assert.equal(fixed.days.find((d) => d.date === "2026-11-20")?.tally.claimed, 1);
  assert.match(fixed.ledger[0].text, /^claimed · 900101/);
  assert.equal(fixed.hub.text, "1 waiting · 0 held");
  // the page's queue alone (what 3cb39ef read): Friday gone, the hub empty
  const broken = scene([saturday]);
  assert.equal(broken.days.find((d) => d.date === "2026-11-20")?.tally.claimed, 0);
  assert.equal(broken.hub.text, "queue empty");
});

test("a run in flight plays on the floor: the panel names the run and its step, its agent at work (#462)", () => {
  const now = Date.parse("2026-11-21T04:41:00Z");
  const tl = timeline({ live: liveOf(false), now });
  const s = sceneAt({ tl, t: now, age: (x) => (now - x) / 1000, now: 0, leagues: [], one: null, executeTime: "22:40" });
  assert.equal(s.now.agent, "mover");
  assert.match(s.now.title, /evening/i);
  assert.ok(s.now.steps.some((x) => x.name === "fresh_reads" && x.state === "done"));
  assert.ok(s.now.steps.some((x) => x.name === "moves" && x.state === "running"));
});

test("the floor's names and stage titles each open a glossary term by its hash (#462)", () => {
  assert.equal(FLOW_TERMS.length, FLOW.length);
  for (const id of [...FLOW_TERMS, ...Object.keys(AGENTS), "the-floor", "demo"]) assert.ok(termById(id), id);
  assert.equal(new Set(GLOSSARY.map((t) => t.id)).size, GLOSSARY.length);
  assert.equal(termOfHash(termHash("out-and-back")), "out-and-back");
  assert.equal(termOfHash("#moves/2"), null);
  // a term hash is no place: Explain stays where it opens
  assert.deepEqual(parseHash(termHash("scout"), TRACKS), parseHash("", TRACKS));
});

test("the panel names the pass's step when the live file has not: the moves chip runs, the Mover at work (#462)", () => {
  const now = Date.parse("2026-11-21T04:40:45Z");
  const live: RoutineLivePayload = { ...liveOf(false) };
  const p = live.live[0].progress;
  assert.ok(p);
  live.live[0] = { ...live.live[0], progress: { ...p, current: { name: null, after: "fresh_reads", started: "2026-11-21T04:40:30Z" } } };
  const active = { id: "p", kind: "moves" as const, trigger: "routine_evening" as const, started: "2026-11-21T04:40:38Z", updated: null, ended: null, end: null, leagues: { done: 0, total: 1, order: ["900101"] }, entries: { done: 0, total: 1 }, current: null, results: {}, summary: null };
  const q = { date: "2026-11-20", built: [], execute_time: "09:00", leagues: [], entries: [], settings: { execute_time: "09:00", at: null, by: null, set: false, sunday_execute_time: null, sunday_at: null, sunday_by: null, in_force: "09:00" }, stop: false, now: "2026-11-21T04:40:45Z", active } as never;
  const tl = timeline({ live, queues: [q], now });
  const s = sceneAt({ tl, t: now, age: (x) => (now - x) / 1000, now: 0, leagues: [], one: null, executeTime: "09:00" });
  assert.equal(s.now.agent, "mover");
  assert.ok(s.now.steps.some((x) => x.name === "moves" && x.state === "running"));
  assert.ok(!s.now.steps.some((x) => x.name.startsWith("after ")));
});
