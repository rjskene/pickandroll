import assert from "node:assert/strict";
import { test } from "node:test";
import type { QueueEntry, QueuePayload, QueueReason, RoutineLivePayload, RoutineRunsPayload } from "../api.ts";
import { BELT, CAST, SIGNS, bentClock, castOf, centralDate, entryState, floorAt, holdOf, nextTimer, stepState, timeline } from "./model.ts";
import { NAMES, PRIVATE, PUBLIC, sampleWeek } from "./sample.ts";

const ct = (s: string) => Date.parse(`${s}-06:00`);

/** One day of runs: the daily run, two steps, and a morning pass with a moves step. */
function runsDay(): RoutineRunsPayload {
  return {
    date: "2026-11-20",
    days: 1,
    by_day: [
      {
        date: "2026-11-20",
        unread: [],
        runs: {
          daily: {
            routine: "daily",
            started_at: "2026-11-20T11:00:00Z",
            finished_at: "2026-11-20T11:30:00Z",
            refused: null,
            stopped: false,
            failed: false,
            alerts: [],
            exports: {},
            steps: [
              { name: "refresh", status: "ok", detail: "2 leagues refreshed", started: "2026-11-20T11:00:00Z", finished: "2026-11-20T11:20:00Z", data: { codes: { "900101": 200, "900102": 200 } } },
              { name: "queue_build", status: "ok", detail: "1 queued", started: "2026-11-20T11:20:00Z", finished: "2026-11-20T11:30:00Z" },
            ],
          },
        },
      },
    ],
  };
}

function entry(over: Partial<QueueEntry>): QueueEntry {
  return {
    id: "2026-11-20:900101:7001:7002",
    date: "2026-11-20",
    league: "900101",
    scoring: "categories",
    set: "three",
    decision: null,
    add: 7001,
    drop: 7002,
    from: null,
    availability: "W",
    judged: "three",
    gain: 0.4,
    value: 0.4,
    season: 0.1,
    season_costly: false,
    flag: null,
    floor: { plan: 0.15, scored: null, moves: 0, needs: 20, applies: "plan", below: null },
    bid: { amount: 3, reason: "", base: 3, factor: 1, sizing: 1, typical: 2, typical_from: "" },
    queued: true,
    reason: null,
    rank: null,
    queued_at: "2026-11-20T11:30:00Z",
    executes_at: "2026-11-20T15:15:00Z",
    struck: false,
    bid_struck: false,
    outcome: null,
    outcome_reason: null,
    outcome_at: null,
    resolved: null,
    ...over,
  };
}

function queue(entries: QueueEntry[], over: Partial<QueuePayload> = {}): QueuePayload {
  return {
    date: "2026-11-20",
    built: ["2026-11-20T11:30:00Z"],
    execute_time: "09:15",
    leagues: [{ league: "900101", scoring: "categories", mode: "live", status: "queued", reason: null, built_at: "2026-11-20T11:30:00Z" }],
    entries,
    settings: { execute_time: "09:15", at: null, by: null, set: false, sunday_execute_time: null, sunday_at: null, sunday_by: null, in_force: "09:15" },
    stop: false,
    now: "2026-11-20T12:00:00Z",
    names: { "7001": "Ari Vance", "7002": "Bo Lindqvist" },
    ...over,
  };
}

test("every step the routines log has its agent; an unknown step goes to the orchestrator", () => {
  assert.deepEqual(castOf("refresh"), { agent: "scout", from: "yahoo", to: "engine" });
  assert.equal(castOf("solve").agent, "solver");
  assert.equal(castOf("lineup").agent, "setter");
  assert.equal(castOf("start_active").agent, "starter");
  assert.equal(castOf("moves").agent, "mover");
  assert.equal(castOf("queue_build").agent, "orchestrator");
  assert.deepEqual(castOf("a_step_added_later"), { agent: "orchestrator", from: "desk", to: "desk" });
  assert.deepEqual(castOf(null), { agent: "orchestrator", from: "desk", to: "desk" });
  for (const name of ["bbm", "exports", "private_pages", "lineup_pages", "fresh_reads", "claim_page", "resolve", "resolve_comebacks", "comebacks", "placed_il", "cancel", "due"]) {
    assert.ok(CAST[name], name);
  }
});

test("a day at rest: no run, the next timer, every entry where it rests", () => {
  const q = queue([entry({}), entry({ id: "h", queued: false, reason: "below the noise floor", queued_at: null })]);
  const tl = timeline({ runs: runsDay(), queues: [q], now: Date.parse("2026-11-20T13:00:00Z") });
  const t = Date.parse("2026-11-20T13:00:00Z"); // 07:00 CT
  const f = floorAt(tl, t);
  assert.equal(f.run, null);
  assert.equal(f.step, null);
  assert.deepEqual(f.next, { routine: "pretip", label: "pre-tip", at: ct("2026-11-20T09:00:00") });
  assert.equal(entryState(tl.entries[0], t), "queued");
  assert.equal(entryState(tl.entries[1], t), "held");
  assert.equal(entryState(tl.entries[0], Date.parse("2026-11-20T11:00:00Z")), "unbuilt");
});

test("the next timer: Monday's run only on a Monday, and past the evening pass the next day's", () => {
  assert.equal(nextTimer(ct("2026-11-16T05:30:00")).routine, "monday");
  assert.equal(nextTimer(ct("2026-11-17T05:30:00")).routine, "watchdog");
  assert.deepEqual(nextTimer(ct("2026-11-20T23:00:00")), { routine: "signin", label: "sign-in check", at: ct("2026-11-21T04:50:00") });
  assert.equal(centralDate(ct("2026-11-20T23:59:00")), "2026-11-20");
});

test("the pre-tip check ticks every five minutes from 09:00 to 20:55, giving way to a timer on its minute", () => {
  assert.deepEqual(nextTimer(ct("2026-11-20T17:02:00")), { routine: "pretip", label: "pre-tip", at: ct("2026-11-20T17:05:00") });
  assert.deepEqual(nextTimer(ct("2026-11-20T20:57:00")), { routine: "evening-build", label: "evening build", at: ct("2026-11-20T21:00:00") });
  assert.deepEqual(nextTimer(ct("2026-11-20T20:52:00")).at, ct("2026-11-20T20:55:00"));
  // Before the window the first tick is 09:00; on 09:15 and 15:00 the passes take the minute.
  assert.deepEqual(nextTimer(ct("2026-11-20T08:00:00")), { routine: "pretip", label: "pre-tip", at: ct("2026-11-20T09:00:00") });
  assert.deepEqual(nextTimer(ct("2026-11-20T09:12:00")), { routine: "morning", label: "morning pass", at: ct("2026-11-20T09:15:00") });
  assert.deepEqual(nextTimer(ct("2026-11-20T14:58:00")).routine, "late");
  assert.deepEqual(nextTimer(ct("2026-11-20T15:00:00")), { routine: "pretip", label: "pre-tip", at: ct("2026-11-20T15:05:00") });
});

test("an entry a later solve superseded is left off the floor: no hold, no state, only a count", () => {
  const gone = entry({ id: "s1", queued: false, reason: "superseded by a later solve", superseded_at: "2026-11-20T03:10:00Z", executes_at: null });
  const marked = entry({ id: "s2", queued: false, reason: "superseded by a later solve", executes_at: null });
  const kept = entry({ id: "k" });
  assert.equal(holdOf(gone), null);
  assert.equal(holdOf(marked), null);
  const tl = timeline({ queues: [queue([gone, marked, kept])], now: Date.parse("2026-11-20T12:00:00Z") });
  assert.deepEqual(tl.entries.map((e) => e.id), ["k"]);
  assert.equal(tl.superseded, 2);
  assert.equal(timeline({ queues: [queue([kept])], now: 0 }).superseded, 0);
});

test("a logged run: its steps in order, their agents, their units by league", () => {
  const tl = timeline({ runs: runsDay(), now: Date.parse("2026-11-20T12:00:00Z") });
  assert.equal(tl.runs.length, 1);
  const r = tl.runs[0];
  assert.equal(r.state, "done");
  assert.equal(r.label, "daily");
  assert.deepEqual(r.steps.map((s) => [s.name, s.cast.agent]), [["refresh", "scout"], ["queue_build", "orchestrator"]]);
  const [a, b] = r.steps[0].units;
  assert.deepEqual([a.league, b.league], ["900101", "900102"]);
  assert.equal(a.end, b.start);
  assert.equal(b.end, Date.parse("2026-11-20T11:20:00Z"));
  const f = floorAt(tl, Date.parse("2026-11-20T11:15:00Z"));
  assert.equal(f.run?.routine, "daily");
  assert.equal(f.step?.name, "refresh");
  assert.equal(f.unit?.league, "900102");
  assert.equal(stepState(r.steps[1], Date.parse("2026-11-20T11:15:00Z")), "todo");
  assert.equal(stepState(r.steps[0], Date.parse("2026-11-20T11:25:00Z")), "done");
});

test("a run in flight: its finished steps and the step under way, named or not", () => {
  const started = "2026-11-20T11:00:00Z";
  const live = (current: { name: string | null; after: string | null; started: string }, stale = false): RoutineLivePayload => ({
    now: "2026-11-20T11:25:00Z",
    live: [
      {
        routine: "daily",
        file: "daily.json",
        written_at: "2026-11-20T11:21:00Z",
        stale,
        reason: null,
        progress: {
          routine: "daily",
          started_at: started,
          written_at: "2026-11-20T11:21:00Z",
          current,
          steps: [{ name: "refresh", status: "ok", detail: "2 leagues refreshed", started, finished: "2026-11-20T11:20:00Z", data: { codes: { "900101": 200 } } }],
        },
      },
    ],
  });
  const now = Date.parse("2026-11-20T11:25:00Z");
  const named = timeline({ live: live({ name: "solve_all", after: "refresh", started: "2026-11-20T11:21:00Z" }), now });
  const r = named.runs[0];
  assert.equal(r.state, "running");
  assert.equal(r.end, null);
  assert.equal(r.steps.length, 2);
  const f = floorAt(named, now);
  assert.equal(f.run, r);
  assert.equal(f.step?.status, "running");
  assert.equal(f.step?.name, "solve_all");
  assert.equal(f.step && stepState(f.step, now), "doing");
  // Between hooked steps the run says only what it follows: the orchestrator holds the floor.
  const between = timeline({ live: live({ name: null, after: "refresh", started: "2026-11-20T11:20:00Z" }), now });
  const s = floorAt(between, now).step;
  assert.equal(s?.name, null);
  assert.equal(s?.after, "refresh");
  assert.equal(s?.cast.agent, "orchestrator");
  // A stale file (a killed run) ends at its last write, with no step under way.
  const stale = timeline({ live: live({ name: "solve_all", after: "refresh", started: "2026-11-20T11:21:00Z" }, true), now });
  assert.equal(stale.runs[0].state, "stale");
  assert.equal(stale.runs[0].end, Date.parse("2026-11-20T11:21:00Z"));
  assert.equal(stale.runs[0].steps.length, 1);
  // Once the run logs, its log is the run and the file is left out.
  const both = timeline({ runs: runsDay(), live: live({ name: null, after: "refresh", started: started }), now });
  assert.equal(both.runs.length, 1);
  assert.equal(both.runs[0].state, "done");
});

test("a pass in flight: the entry under way is doing, the next queued, the landed one its outcome", () => {
  const a = entry({ id: "a", outcome: "claimed", outcome_at: "2026-11-20T15:16:00Z" });
  const b = entry({ id: "b", league: "900102" });
  const c = entry({ id: "c", league: "900103" });
  const active = {
    id: "p1",
    kind: "moves" as const,
    trigger: "routine" as const,
    started: "2026-11-20T15:15:00Z",
    updated: "2026-11-20T15:16:30Z",
    ended: null,
    end: null,
    leagues: { done: 1, total: 3, order: ["900101", "900102", "900103"] },
    entries: { done: 1, total: 3 },
    current: { league: "900102", entry: "b", since: "2026-11-20T15:16:10Z" },
    results: { claimed: 1 },
    summary: null,
  };
  const tl = timeline({ queues: [queue([a, b, c], { active })], now: Date.parse("2026-11-20T15:16:30Z") });
  const t = Date.parse("2026-11-20T15:16:30Z");
  const f = floorAt(tl, t);
  assert.equal(f.pass?.id, "p1");
  assert.equal(f.pass?.current?.entry, "b");
  const [ea, eb, ec] = tl.entries;
  assert.equal(entryState(ea, t, f.pass), "claimed");
  assert.equal(entryState(eb, t, f.pass), "doing");
  assert.equal(entryState(ec, t, f.pass), "queued");
  assert.equal(entryState(ea, Date.parse("2026-11-20T15:15:30Z"), f.pass), "queued");
  assert.equal(tl.entries[0].addName, "Ari Vance");
  assert.equal(tl.entries[0].dropName, "Bo Lindqvist");
});

test("a moves step's units are the entries that landed inside it, each ending at its outcome", () => {
  const runs = runsDay();
  runs.by_day[0].runs.morning = {
    routine: "morning",
    started_at: "2026-11-20T15:15:00Z",
    finished_at: "2026-11-20T15:18:00Z",
    refused: null,
    stopped: false,
    failed: false,
    alerts: [],
    exports: {},
    steps: [{ name: "moves", status: "ok", detail: "2 pages opened", started: "2026-11-20T15:15:00Z", finished: "2026-11-20T15:18:00Z" }],
  };
  const q = queue([
    entry({ id: "x", outcome: "claimed", outcome_at: "2026-11-20T15:17:00Z" }),
    entry({ id: "y", league: "900102", outcome: "failed", outcome_at: "2026-11-20T15:16:00Z" }),
  ]);
  const tl = timeline({ runs, queues: [q], now: Date.parse("2026-11-20T16:00:00Z") });
  const moves = tl.runs[1].steps[0];
  assert.equal(moves.cast.agent, "mover");
  assert.deepEqual(moves.units.map((u) => [u.entry, u.start, u.end]), [
    ["y", Date.parse("2026-11-20T15:15:00Z"), Date.parse("2026-11-20T15:16:00Z")],
    ["x", Date.parse("2026-11-20T15:16:00Z"), Date.parse("2026-11-20T15:17:00Z")],
  ]);
});

test("an entry is held at the rule that held it: the belt's seven in order, the Solver's two signs", () => {
  assert.deepEqual(BELT.map((r) => r.key), ["waiver_days", "noise_floor", "reserve", "recut", "week_plan", "no_adds", "day_cap"]);
  assert.deepEqual(SIGNS.map((r) => r.key), ["keep", "guard"]);
  const at = (reason: QueueReason) => holdOf({ queued: false, reason });
  assert.deepEqual(at("the add is a player this queue drops today or dropped within the waiver days"), { at: "belt", rule: "waiver_days", reason: "the add is a player this queue drops today or dropped within the waiver days" });
  assert.equal(at("below the noise floor")?.at, "belt");
  const rule = (reason: QueueReason) => {
    const h = at(reason);
    return h?.at === "belt" ? h.rule : null;
  };
  assert.equal(rule("below the noise floor"), "noise_floor");
  assert.equal(rule("held for the week's reserve"), "reserve");
  assert.equal(rule("added within the re-cut days"), "recut");
  assert.equal(rule("a later step of the week plan: queued at its day's build"), "week_plan");
  assert.equal(rule("an earlier step of the week plan is not queued"), "week_plan");
  assert.equal(rule("no adds left this week"), "no_adds");
  assert.equal(rule("over the day's cap"), "day_cap");
  const sign = (reason: QueueReason) => {
    const h = at(reason);
    return h?.at === "sign" ? h.sign : null;
  };
  assert.equal(sign("the drop is protected"), "keep");
  assert.equal(sign("season-costly"), "guard");
  assert.equal(at("a claim on the add is already placed")?.at, "desk");
  assert.equal(at("its drop is on a claim already placed")?.at, "desk");
  assert.equal(at("the private league is never touched")?.at, "league");
  assert.equal(at("the moves executor is off in this league")?.at, "league");
  assert.equal(holdOf({ queued: false, reason: null })?.at, "desk");
  assert.equal(holdOf({ queued: true, reason: null }), null);
});

test("the sample week end to end", () => {
  const w = sampleWeek();
  const tl = timeline({ runs: w.runs, queues: w.queues, seasons: w.seasons, now: w.liveAt });
  // Made up: no league, team or player from a real league.
  assert.ok([PRIVATE, ...PUBLIC].every((l) => l.startsWith("9001")));
  assert.ok(Object.keys(NAMES).every((k) => Number(k) >= 7001));
  assert.ok(w.seasons.every((s) => s.name === null && s.my_team === null));
  // Seven days of routines, Monday's once, each run's steps back to back inside it.
  const per = (routine: string) => tl.runs.filter((r) => r.routine === routine).length;
  assert.equal(per("daily"), 7);
  assert.equal(per("monday"), 1);
  assert.equal(per("evening-pass"), 7);
  assert.equal(tl.runs.length, 7 * 8 + 1);
  for (const r of tl.runs) {
    assert.equal(r.state, "done");
    for (const s of r.steps) assert.ok(s.start >= r.start && (s.end ?? 0) <= (r.end ?? 0), `${r.key} ${s.name}`);
  }
  // Every queued entry lands inside its pass's moves step; every hold the queue has is there.
  const queued = tl.entries.filter((e) => e.queued);
  for (const e of queued) {
    const step = tl.runs.flatMap((r) => r.steps).find((s) => s.name === "moves" && s.units.some((u) => u.entry === e.id && u.end === e.outcomeAt));
    assert.ok(step, e.id);
    assert.ok(e.builtAt < (e.outcomeAt ?? 0), e.id);
  }
  const rules = new Set(tl.entries.map((e) => e.hold).map((h) => (h?.at === "belt" ? h.rule : h?.at === "sign" ? h.sign : h?.at)));
  for (const k of [...BELT.map((r) => r.key), ...SIGNS.map((r) => r.key), "desk", "league"]) assert.ok(rules.has(k), k);
  assert.ok(tl.rules[PUBLIC[0]]);
  assert.equal(tl.leagues.find((l) => l.league === PRIVATE)?.mode, "off");
  // Live: Friday's morning pass, the Mover halfway through a claim.
  const f = floorAt(tl, w.liveAt);
  assert.equal(centralDate(w.liveAt), "2026-11-20");
  assert.equal(f.run?.routine, "morning");
  assert.equal(f.step?.name, "moves");
  assert.equal(f.step?.cast.agent, "mover");
  assert.equal(f.unit?.league, PUBLIC[5]);
  // The Demo starts at rest just before Thursday's morning pass.
  const d = floorAt(tl, w.demoAt);
  assert.equal(d.run, null);
  assert.equal(d.next?.routine, "morning");
  assert.equal(centralDate(w.demoAt), "2026-11-19");
});

test("the Demo's bent clock: wall seconds and time map both ways, the idle hours skipped", () => {
  const w = sampleWeek();
  const tl = timeline({ runs: w.runs, queues: w.queues, now: w.liveAt });
  const c = bentClock(tl);
  assert.ok(c.wallEnd > 60 && c.wallEnd < 600, String(c.wallEnd));
  for (const r of tl.runs.slice(0, 12)) {
    assert.ok(Math.abs(c.toTime(c.toWall(r.start)) - r.start) < 1000, r.key);
  }
  let prev = -Infinity;
  for (let x = 0; x <= c.wallEnd; x += 0.5) {
    const t = c.toTime(x);
    assert.ok(t >= prev);
    prev = t;
  }
  // A whole idle night costs at most the gap between days.
  const evening = tl.runs.find((r) => r.routine === "evening-pass");
  const nextSignin = tl.runs.find((r) => r.routine === "signin" && r.date === "2026-11-17");
  assert.ok(evening?.end && nextSignin);
  assert.ok(c.toWall(nextSignin.start) - c.toWall(evening.end) <= 1.4 + 0.2 + 1e-9);
});

test("a finished pass read back names no current entry: the unit under way marks its entry as doing (#461)", () => {
  const w = sampleWeek();
  const tl = timeline({ runs: w.runs, queues: w.queues, seasons: w.seasons, now: w.liveAt });
  const f = floorAt(tl, w.liveAt);
  assert.equal(f.pass?.current, null);
  assert.ok(f.unit?.entry);
  const e = tl.entries.find((x) => x.id === f.unit?.entry);
  assert.ok(e);
  assert.equal(entryState(e, w.liveAt, f.pass), "queued");
  assert.equal(entryState(e, w.liveAt, f.pass, f.unit), "doing");
  assert.equal(entryState(e, (e.outcomeAt ?? 0) + 1, f.pass, f.unit), e.outcome);
});
