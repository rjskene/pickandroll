import assert from "node:assert/strict";
import { test } from "node:test";
import type { QueueEntry, QueuePayload, RoutineLivePayload, RoutinePretipDay, RoutineRunLog, RoutineRunsPayload, RoutineStepLog } from "../api.ts";
import { FROM_MIN, GRACE_MS, LANES, gateTip, gatesOf, stepGateDay, tipCenter } from "./gates.ts";
import type { Gate } from "./gates.ts";
import { CAST, DESK_STEPS, ROUTINES, ROUTINE_AGENTS, bentClock, centralAt, centralDate, timeline } from "./model.ts";
import { sampleWeek } from "./sample.ts";

const ct = (s: string) => Date.parse(`${s}-06:00`);
const FRI = "2026-11-20";
const MON = "2026-11-23";

const step = (name: string, status: RoutineStepLog["status"], detail: string, from: string, to: string): RoutineStepLog => ({
  name,
  status,
  detail,
  started: `${FRI}T${from}:00-06:00`,
  finished: `${FRI}T${to}:00-06:00`,
});

function log(routine: string, from: string, to: string, steps: RoutineStepLog[], over: Partial<RoutineRunLog> = {}): RoutineRunLog {
  return {
    routine,
    started_at: `${FRI}T${from}:00-06:00`,
    finished_at: `${FRI}T${to}:00-06:00`,
    refused: null,
    stopped: false,
    failed: false,
    alerts: [],
    exports: {},
    steps,
    ...over,
  };
}

/** Friday: the sign-in check and the daily reported, the morning pass failed a step. */
function friday(pretip?: RoutinePretipDay, extra: Record<string, RoutineRunLog> = {}): RoutineRunsPayload {
  return {
    date: FRI,
    days: 1,
    by_day: [
      {
        date: FRI,
        unread: [],
        pretip,
        runs: {
          signin: log("signin", "04:50", "04:52", [step("bbm", "ok", "signed in", "04:50", "04:51"), step("yahoo", "ok", "signed in", "04:51", "04:52")]),
          daily: log("daily", "05:00", "05:40", [
            step("exports", "ok", "5 of 5 due saved", "05:00", "05:05"),
            step("refresh", "ok", "9 leagues refreshed", "05:05", "05:25"),
            step("solve", "ok", "9 leagues solved", "05:25", "05:35"),
            step("lineup_pages", "ok", "nothing needed", "05:35", "05:36"),
            step("queue_build", "ok", "4 queued", "05:36", "05:40"),
          ]),
          morning: log(
            "morning",
            "09:15",
            "09:30",
            [step("due", "ok", "2 entries due in 2 leagues", "09:15", "09:16"), step("moves", "failed", "1 of 2 placed", "09:16", "09:30")],
            { failed: ["moves"] },
          ),
          ...extra,
        },
      },
    ],
  };
}

const by = (gs: Gate[], key: string) => gs.find((g) => g.key === key || g.routine === key);

test("the gates' table: every routine on a timer has its steps, each step one CAST names or the orchestrator's own", () => {
  assert.deepEqual(Object.keys(ROUTINE_AGENTS).sort(), Object.keys(ROUTINES).sort());
  const desk = new Set<string>(DESK_STEPS);
  for (const [routine, steps] of Object.entries(ROUTINE_AGENTS)) {
    for (const s of steps) {
      assert.ok(s in CAST !== desk.has(s), `${routine}: ${s} is in CAST or the desk's, not both and not neither`);
    }
  }
  // And every step CAST names is one a routine logs.
  const logged = new Set(Object.values(ROUTINE_AGENTS).flat());
  for (const s of Object.keys(CAST)) assert.ok(logged.has(s), `${s} is in no routine`);
  assert.deepEqual(LANES, ["scout", "solver", "orchestrator", "setter", "starter", "mover"]);
});

test("Central times on a day: 04:30 and the next midnight", () => {
  assert.equal(centralAt(FRI, FROM_MIN), ct(`${FRI}T04:30:00`));
  assert.equal(centralAt(FRI, 24 * 60), ct("2026-11-21T00:00:00"));
  assert.equal(centralAt("2026-07-01", 0), Date.parse("2026-07-01T00:00:00-05:00"));
});

test("done ok and done failed: a reported run's steps are bars on their agents' lanes, colored by status", () => {
  const tl = timeline({ runs: friday(), now: ct(`${FRI}T12:00:00`) });
  const day = gatesOf(tl, FRI, ct(`${FRI}T12:00:00`));
  assert.equal(day.when, "today");
  assert.equal(day.now, ct(`${FRI}T12:00:00`));
  const daily = by(day.gates, "daily") as Gate;
  assert.equal(daily.state, "done");
  assert.equal(daily.start, ct(`${FRI}T05:00:00`));
  assert.equal(daily.end, ct(`${FRI}T05:40:00`));
  assert.deepEqual(daily.lanes, ["scout", "solver", "orchestrator"]);
  const refresh = daily.bars.find((b) => b.start === ct(`${FRI}T05:05:00`));
  assert.deepEqual(refresh, { agent: "scout", start: ct(`${FRI}T05:05:00`), end: ct(`${FRI}T05:25:00`), state: "ok" });
  // Nothing needed is grey.
  assert.equal(daily.bars.find((b) => b.start === ct(`${FRI}T05:35:00`))?.state, "idle");
  const morning = by(day.gates, "morning") as Gate;
  assert.equal(morning.state, "failed");
  assert.equal(morning.bars.find((b) => b.agent === "mover")?.state, "failed");
  // The hover: label and time, the run, the status, the lane's steps with their detail.
  assert.deepEqual(gateTip(morning, "mover"), ["morning pass · 09:15", "ran 09:15 to 09:30", "done, a step failed", "Mover · moves: 1 of 2 placed"]);
});

test("running: a run in flight from its live file is a running gate, its bars to now", () => {
  const now = ct(`${FRI}T15:05:00`);
  const live: RoutineLivePayload = {
    now: new Date(now).toISOString(),
    live: [
      {
        routine: "late",
        file: "late.json",
        written_at: new Date(now - 60_000).toISOString(),
        stale: false,
        reason: null,
        progress: {
          routine: "late",
          started_at: `${FRI}T15:00:00-06:00`,
          written_at: new Date(now - 60_000).toISOString(),
          current: { name: "moves", after: "due", started: `${FRI}T15:02:00-06:00` },
          steps: [step("due", "ok", "1 entry due", "15:00", "15:02")],
        },
      },
    ],
  };
  const tl = timeline({ runs: friday(), live, now });
  const late = by(gatesOf(tl, FRI, now).gates, "late") as Gate;
  assert.equal(late.state, "running");
  assert.equal(late.end, null);
  const moving = late.bars.find((b) => b.agent === "mover");
  assert.deepEqual(moving, { agent: "mover", start: ct(`${FRI}T15:02:00`), end: now, state: "running" });
});

test("still to come and missed after the 20-minute grace; a past day keeps no gate still to come", () => {
  const tl = timeline({ runs: friday(), now: ct(`${FRI}T15:10:00`) });
  // 15:10: the late pass is ten minutes due, inside the grace; the evening build is to come.
  const at10 = gatesOf(tl, FRI, ct(`${FRI}T15:10:00`)).gates;
  assert.equal(by(at10, "late")?.state, "todo");
  assert.equal(by(at10, "evening-build")?.state, "todo");
  // 15:21: past the grace with no report and nothing running: missed, "not run".
  const at21 = gatesOf(tl, FRI, ct(`${FRI}T15:00:00`) + GRACE_MS + 60_000).gates;
  const late = by(at21, "late") as Gate;
  assert.equal(late.state, "missed");
  assert.equal(late.note, "not run");
  assert.deepEqual(late.lanes, ["scout", "solver", "orchestrator", "setter", "starter", "mover"]);
  assert.equal(gateTip(late, null)[1], "not run");
  // The next day looking back: what ran and what was missed, nothing still to come.
  const past = gatesOf(tl, FRI, ct("2026-11-21T12:00:00"));
  assert.equal(past.when, "past");
  assert.equal(past.now, null);
  assert.ok(past.gates.every((g) => g.state !== "todo"));
  assert.equal(by(past.gates, "evening-pass")?.state, "missed");
  // A future day: only gates still to come, no bars.
  const future = gatesOf(tl, "2026-11-22", ct(`${FRI}T12:00:00`));
  assert.equal(future.when, "future");
  assert.ok(future.gates.every((g) => g.state === "todo" || g.state === "plain"));
  assert.ok(future.gates.every((g) => !g.bars.length));
  // The pre-tip window as one faint band, no slates; on no other day.
  assert.deepEqual(
    future.bands.map((b) => [b.start, b.end, b.lanes]),
    [[ct("2026-11-22T09:00:00"), ct("2026-11-22T20:55:00"), ["scout", "solver", "orchestrator", "setter"]]],
  );
  assert.deepEqual(past.bands, []);
  assert.deepEqual(gatesOf(tl, FRI, ct(`${FRI}T15:10:00`)).bands, []);
});

test("Monday's gate only on a Monday; the watchdog a plain tick with no state", () => {
  const tl = timeline({ now: ct(`${FRI}T12:00:00`) });
  assert.equal(by(gatesOf(tl, FRI, ct(`${FRI}T12:00:00`)).gates, "monday"), undefined);
  const mon = gatesOf(tl, MON, ct(`${FRI}T12:00:00`)).gates;
  assert.equal(by(mon, "monday")?.at, ct(`${MON}T06:00:00`));
  for (const d of [FRI, MON]) {
    const w = by(gatesOf(tl, d, ct(`${FRI}T12:00:00`)).gates, "watchdog") as Gate;
    assert.equal(w.kind, "watchdog");
    assert.equal(w.state, "plain");
    assert.deepEqual(w.lanes, []);
  }
  // No pre-tip tick every five minutes: without slates the check draws nothing.
  assert.ok(gatesOf(tl, FRI, ct(`${FRI}T12:00:00`)).gates.every((g) => g.routine !== "pretip"));
});

test("pre-tip: planned slates still to come, a done slate's attempt drawn by its run report, an earlier one by its stamps", () => {
  const block = (over: Partial<RoutinePretipDay["slates"][number]>[]): RoutinePretipDay => ({
    enabled: true,
    lead_min: 60,
    slates: [
      { slate: "first", tip: `${FRI}T18:00:00-06:00`, start_at: `${FRI}T17:00:00-06:00`, until: `${FRI}T17:45:00-06:00`, done: false, missed: false, attempts: [], ...over[0] },
      { slate: "late", tip: `${FRI}T21:30:00-06:00`, start_at: `${FRI}T20:30:00-06:00`, until: `${FRI}T21:15:00-06:00`, done: false, missed: false, attempts: [], ...over[1] },
    ],
  });
  // Planned: at noon both slates are still to come, at their starts, on the pre-tip's lanes.
  const planned = timeline({ runs: friday(block([{}, {}])), now: ct(`${FRI}T12:00:00`) });
  const [first, late] = gatesOf(planned, FRI, ct(`${FRI}T12:00:00`)).gates.filter((g) => g.kind === "slate");
  assert.equal(first.state, "todo");
  assert.equal(first.at, ct(`${FRI}T17:00:00`));
  assert.equal(first.note, "tip-off 18:00");
  assert.equal(late.at, ct(`${FRI}T20:30:00`));
  assert.deepEqual(first.lanes, ["scout", "solver", "orchestrator", "setter"]);
  // The knob off: no slate is planned.
  const off = timeline({ runs: friday({ ...block([{}, {}]), enabled: false }), now: ct(`${FRI}T12:00:00`) });
  assert.equal(gatesOf(off, FRI, ct(`${FRI}T12:00:00`)).gates.filter((g) => g.kind === "slate").length, 0);
  // Done: the first slate by its stamps (the day's report is the late pass's), the late one by its report.
  const attempt = (at: string, over = {}) => ({ started_at: `${FRI}T${at}:00-06:00`, outcome: "done" as const, reason: null, solved_at: null, pushed_at: null, unchanged: false, lineups_at: null, ...over });
  const pretipLog = log("pretip", "20:30", "20:42", [
    step("pretip_due", "ok", "late slate", "20:30", "20:30"),
    step("solve", "ok", "1 league solved", "20:31", "20:36"),
    step("lineup", "ok", "9 pages opened", "20:36", "20:42"),
  ]);
  const done = timeline({
    runs: friday(
      block([
        { done: true, attempts: [attempt("17:00", { solved_at: `${FRI}T17:05:00-06:00`, pushed_at: `${FRI}T17:05:01-06:00`, lineups_at: `${FRI}T17:11:00-06:00` })] },
        { done: true, attempts: [attempt("20:30", { unchanged: true })] },
      ]),
      { pretip: pretipLog },
    ),
    now: ct(`${FRI}T22:00:00`),
  });
  const [d1, d2] = gatesOf(done, FRI, ct(`${FRI}T22:00:00`)).gates.filter((g) => g.kind === "slate");
  assert.equal(d1.state, "done");
  assert.equal(d1.start, ct(`${FRI}T17:00:00`));
  assert.equal(d1.end, ct(`${FRI}T17:11:00`));
  assert.deepEqual(d1.bars.map((b) => b.agent), ["scout", "solver", "orchestrator", "setter"]);
  assert.ok(gateTip(d1, "solver").includes("Orchestrator · attempt 17:00: done · solved 17:05 · pushed 17:05 · lineups 17:11 · from the day file"));
  // The slate the run report holds says no such thing.
  assert.ok(gateTip(d2, null).includes("Orchestrator · attempt 20:30: done · nothing to push"));
  assert.equal(d2.state, "done");
  assert.deepEqual(
    d2.bars.map((b) => [b.agent, b.state]),
    [["orchestrator", "ok"], ["solver", "ok"], ["setter", "ok"]],
  );
  // A slate past its window with no attempt is missed; a failed attempt fails it.
  const missed = timeline({ runs: friday(block([{ attempts: [attempt("17:00", { outcome: "failed", reason: "push failed" })] }, {}])), now: ct(`${FRI}T23:00:00`) });
  const [m1, m2] = gatesOf(missed, FRI, ct(`${FRI}T23:00:00`)).gates.filter((g) => g.kind === "slate");
  assert.equal(m1.state, "failed");
  assert.equal(m2.state, "missed");
  assert.equal(m2.note, "tip-off 21:30 · not run");
});

test("pre-tip: a slate that would start past the latest start is grey, not run by design, never missed", () => {
  const block: RoutinePretipDay = {
    enabled: true,
    lead_min: 60,
    latest_start: "20:40",
    slates: [
      { slate: "late", tip: `${FRI}T21:45:00-06:00`, start_at: `${FRI}T20:45:00-06:00`, until: `${FRI}T21:30:00-06:00`, past_latest: true, done: false, missed: false, attempts: [] },
    ],
  };
  const tl = timeline({ runs: friday(block), now: ct(`${FRI}T21:30:00`) });
  for (const at of ["21:30:00", "23:30:00"]) {
    const [late] = gatesOf(tl, FRI, ct(`${FRI}T${at}`)).gates.filter((g) => g.kind === "slate");
    assert.equal(late.state, "idle");
    assert.equal(late.note, "tip-off 21:45 · starts past 20:40: not run by design");
    assert.equal(gateTip(late, null)[1], "no run · tip-off 21:45 · starts past 20:40: not run by design");
  }
  assert.ok(gatesOf(tl, FRI, ct(`${FRI}T21:30:00`)).gates.every((g) => g.kind !== "slate" || g.state !== "missed"));
});

test("the execute times sit on the Mover's lane with their counts", () => {
  const e = (id: string, over: Partial<QueueEntry> = {}): QueueEntry => ({
    id,
    date: FRI,
    league: id.split(":")[1],
    scoring: "categories",
    set: "three",
    decision: null,
    add: 7001,
    drop: null,
    from: null,
    availability: "W",
    judged: "three",
    gain: 0.4,
    value: 0.4,
    season: 0.1,
    season_costly: false,
    flag: null,
    floor: { plan: 0.15, scored: null, moves: 0, needs: 20, applies: "plan", below: null },
    bid: null,
    queued: true,
    reason: null,
    rank: null,
    queued_at: `${FRI}T05:40:00-06:00`,
    executes_at: `${FRI}T09:15:00-06:00`,
    struck: false,
    bid_struck: false,
    outcome: null,
    outcome_reason: null,
    outcome_at: null,
    resolved: null,
    ...over,
  });
  const q: QueuePayload = {
    date: FRI,
    built: [`${FRI}T05:40:00-06:00`],
    execute_time: "09:15",
    leagues: [],
    entries: [
      e(`${FRI}:900101:7001:0`, { outcome: "claimed", outcome_at: `${FRI}T09:20:00-06:00` }),
      e(`${FRI}:900102:7001:0`, { outcome: "claimed", outcome_at: `${FRI}T09:25:00-06:00` }),
      e(`${FRI}:900103:7001:0`, { executes_at: `${FRI}T22:40:00-06:00` }),
      e(`${FRI}:900104:7001:0`, { queued: false, reason: "below the noise floor", executes_at: null }),
    ],
    settings: { execute_time: "09:15", at: null, by: null, set: false, sunday_execute_time: null, sunday_at: null, sunday_by: null, in_force: "09:15" },
    stop: false,
    now: `${FRI}T12:00:00-06:00`,
    names: { "7001": "Ari Vance" },
  };
  const tl = timeline({ runs: friday(), queues: [q], now: ct(`${FRI}T12:00:00`) });
  const marks = gatesOf(tl, FRI, ct(`${FRI}T12:00:00`)).gates.filter((g) => g.kind === "execute");
  assert.deepEqual(
    marks.map((g) => [g.at, g.count, g.state, g.lanes]),
    [
      [ct(`${FRI}T09:15:00`), 2, "done", ["mover"]],
      [ct(`${FRI}T22:40:00`), 1, "todo", ["mover"]],
    ],
  );
  assert.equal(marks[0].note, "2 queued entries");
});

test("a Demo frame: the sample week's Friday mid-claim, its gates on the bent clock", () => {
  const w = sampleWeek();
  const tl = timeline({ runs: w.runs, queues: w.queues, seasons: w.seasons, now: w.liveAt });
  const clock = bentClock(tl);
  const t = clock.toTime(clock.toWall(w.liveAt));
  const day = gatesOf(tl, centralDate(t), t);
  assert.equal(day.date, "2026-11-20");
  assert.equal(day.when, "today");
  assert.equal(day.now, t);
  // Done by then: the sign-in check, the daily; the morning pass under way; the rest to come.
  assert.equal(by(day.gates, "daily")?.state, "done");
  assert.equal(by(day.gates, "morning")?.state, "running");
  assert.equal(by(day.gates, "late")?.state, "todo");
  assert.equal(by(day.gates, "evening-pass")?.state, "todo");
  const slates = day.gates.filter((g) => g.kind === "slate");
  assert.deepEqual(slates.map((g) => [g.label, g.state]), [["pre-tip, first slate", "todo"], ["pre-tip, late slate", "todo"]]);
  // Later in the Demo the first slate is done from the sample's day file.
  const evening = gatesOf(tl, "2026-11-20", ct("2026-11-20T23:59:00"));
  assert.deepEqual(evening.gates.filter((g) => g.kind === "slate").map((g) => g.state), ["done", "done"]);
  assert.ok(evening.gates.filter((g) => g.kind !== "watchdog").every((g) => g.state !== "todo"));
});

test("live, the arrows move the gates' day through the week, stopping at Monday and at today", () => {
  const week = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"];
  const today = "2026-11-20";
  assert.equal(stepGateDay(week, today, today, -1), "2026-11-19");
  assert.equal(stepGateDay(week, today, "2026-11-19", 1), null); // back to today: nothing picked
  assert.equal(stepGateDay(week, today, today, 1), null); // never past today
  assert.equal(stepGateDay(week, today, "2026-11-16", -1), "2026-11-16"); // stops at Monday
  // A future day picked by a click: ← comes back to today, → stays at today.
  assert.equal(stepGateDay(week, today, "2026-11-22", -1), null);
  assert.equal(stepGateDay(week, today, "2026-11-22", 1), null);
});

test("a tooltip of any width stays inside the strip's box (#474)", () => {
  // 1600 px box, the daily's 440 px tip hovered at 05:00 (x 60): kept 228 px in, not 180.
  assert.equal(tipCenter(1600, 440, 60), 228);
  assert.equal(tipCenter(1600, 440, 1590), 1372); // the right edge mirrors it
  assert.equal(tipCenter(1600, 200, 800), 800); // in the middle the pointer stands
  assert.equal(tipCenter(1600, 120, 30), 68); // a short tip comes closer to the edge than the old 180
  assert.equal(tipCenter(300, 460, 10), 150); // wider than the box: centered in it
  for (const w of [80, 240, 360, 460]) {
    for (const x of [-50, 0, 40, 800, 1560, 1700]) {
      const c = tipCenter(1600, w, x);
      assert.ok(c - w / 2 >= 8 && c + w / 2 <= 1592, `w ${w} x ${x}`);
    }
  }
});
