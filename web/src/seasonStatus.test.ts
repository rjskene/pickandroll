// Node's own test runner with its built-in type stripping (`npm test`), as format.test.ts.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { BuiltRow, StatusLeague, StatusPayload, YahooRow } from "./api";
import { jobText, lightOf, recsReason, sheetSections, statusLine, when, worstOf } from "./seasonStatus.ts";

// The viewer's clock is the Mac's: every time below reads on it.
process.env.TZ = "America/Chicago";
const NOW = new Date("2026-10-23T18:00:00Z"); // 13:00 on the Mac
const T = (hhmm: string, day = "2026-10-23") => new Date(`${day}T${hhmm}:00-05:00`).toISOString();

function built(kind: string, at: string | null, state: BuiltRow["state"] = "green", reason = "on today's inputs"): BuiltRow {
  return { kind, built_at: at, system: "bbm", projection_file: "bbm_projections.csv", state, reason };
}

function recs(over: Partial<Record<string, BuiltRow>> = {}): NonNullable<StatusLeague["recommendations"]> {
  const rows = [
    over.moves ?? built("moves", T("06:02")),
    over.plan ?? built("plan", T("06:02")),
    built("strategy", null, null, "run on request"),
    { kind: "trades", built_at: null, inputs: { projection: T("05:14"), "Yahoo read": T("05:40") }, state: null, reason: "evaluated on request, from the inputs above" },
  ];
  return { state: worstOf(rows.map((r) => r.state)), rows, inputs: { projection: T("05:14"), "Yahoo read": T("05:40") } };
}

function refresh(over: Partial<YahooRow> = {}): YahooRow {
  return {
    kind: "refresh",
    read_at: T("05:40"),
    status: "done",
    started_at: T("05:39"),
    finished_at: T("05:40"),
    step: "done",
    done: 47,
    total: 47,
    warnings: {},
    logged: false,
    snapshot_at: T("05:40"),
    state: "green",
    reason: "today",
    ...over,
  };
}

function payload(over: { routine?: Partial<StatusPayload["routine"]>; leagues?: StatusLeague[] } = {}): StatusPayload {
  const exports = ["ros", "week_this", "week_next", "actual_7d", "actual_14d"].map((kind) => ({
    kind,
    label: kind,
    file: `${kind}.xls`,
    as_of: T("05:14"),
    state: "green" as const,
    reason: "today",
  }));
  const pub: StatusLeague = {
    league: "100001",
    name: "League one",
    public: true,
    state: "green",
    yahoo: { state: "green", rows: [refresh()] },
    recommendations: recs(),
  };
  return {
    generated_at: NOW.toISOString(),
    today: "2026-10-23",
    due_at: T("06:30"),
    state: "green",
    routine: { kind: "routine", started_at: T("05:00"), finished_at: T("05:52"), steps: { refresh: { status: "ok", detail: "13 leagues" } }, state: "green", reason: "ran today", ...over.routine },
    exports: { state: "green", rows: exports },
    leagues: over.leagues ?? [pub],
  };
}

test("the worst state wins, and none has no say", () => {
  assert.equal(worstOf(["green", "amber", null]), "amber");
  assert.equal(worstOf(["red", "green"]), "red");
  assert.equal(worstOf([]), "green");
});

test("a time reads on the viewer's clock, with its day when it is not today's", () => {
  assert.equal(when(T("05:14"), NOW), "05:14");
  assert.equal(when(T("23:05", "2026-10-22"), NOW), "Oct 22 23:05");
  assert.equal(when(null, NOW), "—");
  assert.equal(when("soon", NOW), "—");
});

test("a league's light is its own state and the daily run's", () => {
  const p = payload();
  assert.equal(lightOf(p, "100001"), "green");
  assert.equal(lightOf(payload({ routine: { state: "red", reason: "no run recorded today" } }), "100001"), "red");
  // A league the status does not list yet; no status read yet.
  assert.equal(lightOf(p, "999"), "amber");
  assert.equal(lightOf(undefined, "100001"), null);
});

test("the landing table names why the recommendations are not up to date, and nothing when they are", () => {
  // Green, and the rows made on request (no state), say nothing.
  assert.equal(recsReason(payload(), "100001"), null);
  const late: StatusLeague = {
    ...payload().leagues[0],
    recommendations: recs({
      moves: built("moves", T("06:02"), "amber", "Yahoo read newer; re-solved on open"),
      plan: built("plan", null, "red", "not built today"),
    }),
  };
  assert.equal(recsReason(payload({ leagues: [late] }), "100001"), "Yahoo read newer; re-solved on open; not built today");
  // The moves and the plan late for one reason say it once.
  const both: StatusLeague = {
    ...late,
    recommendations: recs({ moves: built("moves", null, "amber", "expected by 06:30"), plan: built("plan", null, "amber", "expected by 06:30") }),
  };
  assert.equal(recsReason(payload({ leagues: [both] }), "100001"), "expected by 06:30");
  assert.equal(recsReason(payload(), "999"), null);
  assert.equal(recsReason(undefined, "100001"), null);
});

test("the hover line says when everything landed, or what to look at, red first", () => {
  assert.equal(statusLine(payload(), "100001", NOW), "all updates landed 05:52; recommendations 06:02");
  const failed: StatusLeague = {
    ...payload().leagues[0],
    state: "red",
    yahoo: { state: "red", rows: [refresh({ status: "failed", error: "HTTP 502", state: "red", reason: "refresh failed" })] },
    recommendations: recs({ moves: built("moves", T("06:02"), "amber", "Yahoo read newer; re-solved on open") }),
  };
  const p = payload({ leagues: [failed], routine: { state: "amber", reason: "refresh skipped" } });
  assert.equal(statusLine(p, "100001", NOW), "3 to look at: last refresh: refresh failed; daily run: refresh skipped; 1 more");
  assert.equal(statusLine(p, "999", NOW), "no status for this league yet");
  const broken = payload({ leagues: [{ league: "100003", state: "red", error: "settings.json: no scoring" }] });
  assert.equal(statusLine(broken, "100003", NOW), "settings.json: no scoring");
});

test("the sheet lists the run, the exports, the league's Yahoo reads and its recommendations", () => {
  const sections = sheetSections(payload(), "100001", NOW);
  assert.deepEqual(
    sections.map((s) => s.title),
    ["Daily run", "Basketball Monster", "Yahoo", "Recommendations"],
  );
  const [run, exports, yahoo, rec] = sections;
  assert.equal(run.rows[0].detail, "refresh ok");
  assert.deepEqual(
    exports.rows.map((r) => [r.time, r.detail]),
    ["ros", "week_this", "week_next", "actual_7d", "actual_14d"].map((k) => ["05:14", `${k}.xls`]),
  );
  assert.equal(yahoo.rows[0].detail, "last job done 47/47, 05:39 to 05:40 · snapshot 05:40");
  const trades = rec.rows.find((r) => r.key === "trades")!;
  assert.deepEqual([trades.state, trades.time, trades.detail], [null, "—", "projection 05:14 · Yahoo read 05:40"]);
  assert.equal(rec.rows.find((r) => r.key === "moves")!.detail, "bbm, bbm_projections.csv");
  // The private league's pages, read by the extension.
  const pages: StatusLeague = {
    league: "100002",
    name: null,
    public: false,
    state: "red",
    yahoo: { state: "red", rows: [{ kind: "lineup", read_at: T("23:05", "2026-10-22"), state: "red", reason: "not read today" }] },
    recommendations: recs(),
  };
  const priv = sheetSections(payload({ leagues: [pages] }), "100002", NOW)[2];
  assert.equal(priv.title, "Yahoo, read by the extension");
  assert.deepEqual([priv.rows[0].label, priv.rows[0].time], ["lineup page", "Oct 22 23:05"]);
});

test("a refresh job says how far it got, and when it is read from the log", () => {
  assert.equal(jobText(refresh(), NOW), "last job done 47/47, 05:39 to 05:40");
  const failed = refresh({ status: "failed", step: "players", done: 12, finished_at: T("05:41") });
  assert.equal(jobText(failed, NOW), "last job failed at players 12/47, 05:39 to 05:41");
  const lost = refresh({ status: "running", step: "pairs", done: 47, finished_at: null, logged: true });
  assert.equal(jobText(lost, NOW), "last job running at pairs 47/47, since 05:39 (from its log)");
  assert.equal(jobText({ kind: "refresh", read_at: null, state: "red", reason: "not refreshed today" }, NOW), null);
});
