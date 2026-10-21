// Node's own test runner with its built-in type stripping (`npm test`), as format.test.ts.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { AvailableRow, BestMove, FlagConfig, FlagSignal, MoveCandidate, PlayerFlag, Rates, RosterRow, SeasonPlayer, SeasonSummary, TradePlayer, TradeSide } from "./api";
import {
  addsLeft,
  addsNote,
  bestGain,
  bestLine,
  flagCounts,
  gridOrder,
  placeLabel,
  scoreLabel,
  ageLabel,
  availabilityLabel,
  bestMove,
  catValue,
  changeLabel,
  comebackText,
  dayLabel,
  effectiveNote,
  gainLabel,
  marginText,
  movedGames,
  movedGamesTitle,
  rosterNote,
  tradeVerdict,
  weekResult,
  weekTone,
  gainTone,
  horizonGames,
  MOVE_HORIZON,
  openingDrop,
  oddsLabel,
  oddsTone,
  projectedTotals,
  DEFAULT_AVAILABLE_SORT,
  filterAvailable,
  FLAG_SHORT,
  flagged,
  flagInputsNote,
  flagOf,
  flagBreakdown,
  flagExplainer,
  flagSignals,
  flagTitle,
  levelsLine,
  isStale,
  NO_FILTER,
  ordinal,
  pctLabel,
  playersById,
  playsPosition,
  recordLabel,
  refreshNote,
  sortAvailable,
  statusTitle,
  statusTone,
  weekDates,
  weekLabel,
  YAHOO_SORT,
} from "./season.ts";

const player = (name: string, positions: string[], extra: Partial<SeasonPlayer> = {}): SeasonPlayer => ({
  yahoo_id: name.length,
  name,
  nba_team: "PHX",
  positions,
  status: null,
  status_full: null,
  note: null,
  ...extra,
});

const row = (p: SeasonPlayer, extra: Partial<AvailableRow> = {}): AvailableRow => ({
  player: p,
  availability: "FA",
  clears: null,
  pct_rostered: null,
  pct_rostered_change: null,
  pct_started: null,
  pct_started_change: null,
  adds: null,
  drops: null,
  seen_at: null,
  games_left: null,
  ...extra,
});

test("a snapshot's age reads in minutes, hours, then days, and goes stale after a day", () => {
  const now = Date.parse("2026-10-21T18:00:00Z");
  assert.equal(ageLabel(null, now), "never read");
  assert.equal(ageLabel("2026-10-21T17:59:30Z", now), "just now");
  assert.equal(ageLabel("2026-10-21T17:56:00Z", now), "4 min ago");
  assert.equal(ageLabel("2026-10-21T12:00:00Z", now), "6 h ago");
  assert.equal(ageLabel("2026-10-18T12:00:00Z", now), "3 days ago");
  assert.equal(ageLabel("soon", now), "soon");
  assert.equal(isStale("2026-10-21T12:00:00Z", now), false);
  assert.equal(isStale("2026-10-20T12:00:00Z", now), true);
  assert.equal(isStale(null, now), true);
});

test("ownership reads as Yahoo shows it, with the day's change signed", () => {
  assert.equal(pctLabel(46), "46%");
  assert.equal(pctLabel(null), "");
  assert.equal(changeLabel(3), "+3");
  assert.equal(changeLabel(-1), "−1");
  assert.equal(changeLabel(0), "");
  assert.equal(changeLabel(null), "");
});

test("a waiver player shows the day he clears", () => {
  assert.equal(availabilityLabel({ availability: "FA", clears: null }), "FA");
  assert.equal(availabilityLabel({ availability: "W", clears: "2026-10-22" }), "W · Oct 22");
  assert.equal(availabilityLabel({ availability: "W", clears: null }), "W");
});

test("a status is red when it keeps him off the floor and amber when it is a doubt", () => {
  assert.equal(statusTone(player("A", ["C"], { status: "O" })), "bad");
  assert.equal(statusTone(player("A", ["C"], { status: "INJ" })), "bad");
  assert.equal(statusTone(player("A", ["C"], { status: "Q" })), "accent");
  assert.equal(statusTone(player("A", ["C"], { status: "GTD" })), "accent");
  assert.equal(statusTone(player("A", ["C"])), null);
  assert.equal(statusTitle(player("A", ["C"], { status: "O", status_full: "Out", note: "Hamstring" })), "Out: Hamstring");
  assert.equal(statusTitle(player("A", ["C"], { status: "Q" })), "Q");
  assert.equal(statusTitle(player("A", ["C"])), undefined);
});

test("a team's record carries its rank, and the week its count", () => {
  assert.equal(recordLabel({ team_id: 4, name: "Team 4", record: "3-1-0", rank: 2 }), "3-1-0 · 2nd");
  assert.equal(recordLabel({ team_id: 4, name: "Team 4", record: null, rank: null }), "no record");
  assert.equal(recordLabel(null), "");
  assert.deepEqual([1, 2, 3, 4, 11, 12, 13, 21, 22, 101, 111].map(ordinal), ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st", "111th"]);
  assert.equal(weekDates({ start: "2026-10-19", end: "2026-10-25" }), "Oct 19 – 25");
  assert.equal(weekDates({ start: "2027-02-15", end: "2027-02-28" }), "Feb 15 – 28");
  assert.equal(weekDates({ start: "2027-03-29", end: "2027-04-04" }), "Mar 29 – Apr 4");
  assert.equal(weekLabel({ week: 1, end_week: 22 }), "Week 1 of 22");
  assert.equal(weekLabel({ week: 3, end_week: null }), "Week 3");
  assert.equal(weekLabel({ week: null, end_week: 22 }), "week unknown");
});

test("a refresh says how far it has read, and why it failed", () => {
  const base = { started_at: "", finished_at: null, error: null };
  assert.equal(refreshNote(null), "");
  assert.equal(refreshNote({ ...base, status: "done", step: "done", done: 19, total: 19 }), "");
  assert.equal(refreshNote({ ...base, status: "running", step: "team 4", done: 7, total: 29 }), "refreshing 7/29 · team 4");
  assert.equal(refreshNote({ ...base, status: "running", step: "starting", done: 0, total: 0 }), "refreshing");
  assert.equal(refreshNote({ ...base, status: "failed", step: "settings", done: 0, total: 29, error: "HTTP 503" }), "HTTP 503");
});

test("a G or F position filter takes either guard or either forward", () => {
  assert.equal(playsPosition(["SG", "SF"], "G"), true);
  assert.equal(playsPosition(["SG", "SF"], "F"), true);
  assert.equal(playsPosition(["SG", "SF"], "C"), false);
  assert.equal(playsPosition(["PG"], "SG"), false);
  assert.equal(playsPosition(["PG"], ""), true);
});

test("the available table filters by name, team, position, waivers and health", () => {
  const rows = [
    row(player("Kristaps Porziņģis", ["C"], { nba_team: "GSW", status: "O" }), { availability: "W", clears: "2026-10-22" }),
    row(player("Dillon Brooks", ["SF", "PF"])),
    row(player("Jalen Smith", ["PF", "C"], { nba_team: "CHI", status: "Q" })),
  ];
  const names = (f: Partial<typeof NO_FILTER>) => filterAvailable(rows, { ...NO_FILTER, ...f }).map((r) => r.player.name);
  assert.deepEqual(names({}), ["Kristaps Porziņģis", "Dillon Brooks", "Jalen Smith"]);
  assert.deepEqual(names({ search: "porzingis" }), ["Kristaps Porziņģis"]);
  assert.deepEqual(names({ search: "chi" }), ["Jalen Smith"]);
  assert.deepEqual(names({ position: "C" }), ["Kristaps Porziņģis", "Jalen Smith"]);
  assert.deepEqual(names({ position: "F" }), ["Dillon Brooks", "Jalen Smith"]);
  assert.deepEqual(names({ availability: "W" }), ["Kristaps Porziņģis"]);
  assert.deepEqual(names({ availability: "FA" }), ["Dillon Brooks", "Jalen Smith"]);
  // A questionable player stays; an out one goes.
  assert.deepEqual(names({ healthy: true }), ["Dillon Brooks", "Jalen Smith"]);
});

test("the available table filters by NBA team, games this week and percent rostered", () => {
  const rows = [
    row(player("Kristaps Porziņģis", ["C"], { nba_team: "GSW" }), { pct_rostered: 43, games_left: 0 }),
    row(player("Dillon Brooks", ["SF", "PF"]), { pct_rostered: 46, games_left: 3 }),
    row(player("Jalen Smith", ["PF", "C"], { nba_team: "CHI" }), { pct_rostered: null, games_left: null }),
  ];
  const names = (f: Partial<typeof NO_FILTER>, games?: (r: (typeof rows)[number]) => number | null) =>
    filterAvailable(rows, { ...NO_FILTER, ...f }, games).map((r) => r.player.name);
  assert.deepEqual(names({ nbaTeam: "CHI" }), ["Jalen Smith"]);
  // The games floor reads the row's own count by default, or the projection's when given one.
  assert.deepEqual(names({ minGames: 1 }), ["Dillon Brooks"]);
  assert.deepEqual(names({ minGames: 2 }, (r) => (r.player.name === "Jalen Smith" ? 2 : 0)), ["Jalen Smith"]);
  // A row with no ownership figure fails a floor above zero.
  assert.deepEqual(names({ minRostered: 44 }), ["Dillon Brooks"]);
  assert.deepEqual(names({ minRostered: 0 }).length, 3);
});

test("the available table sorts most rostered first, missing values last, ties in Yahoo's order", () => {
  const rows = [
    row(player("A", ["C"]), { pct_rostered: 12, adds: 5 }),
    row(player("B", ["C"]), { pct_rostered: null, adds: 9 }),
    row(player("C", ["C"]), { pct_rostered: 40, adds: 5, availability: "W", clears: "2026-10-23" }),
    row(player("D", ["C"]), { pct_rostered: 12, adds: null, availability: "W", clears: "2026-10-22" }),
  ];
  const order = (key: Parameters<typeof sortAvailable>[1]["key"], dir: "asc" | "desc") => sortAvailable(rows, { key, dir }).map((r) => r.player.name).join("");
  assert.equal(order(YAHOO_SORT.key, YAHOO_SORT.dir), "CADB");
  assert.equal(order("pct_rostered", "asc"), "ADCB");
  assert.equal(order("adds", "desc"), "BACD");
  assert.equal(order("name", "desc"), "DCBA");
  // Free agents first, then waivers by the day they clear.
  assert.equal(order("availability", "asc"), "ABDC");
});

test("the available table sorts by a column from outside the row", () => {
  const rows = [row(player("A", ["C"])), row(player("B", ["C"])), row(player("C", ["C"]))];
  const games: Record<string, number | null> = { A: 2, B: null, C: 4 };
  const extra = (r: AvailableRow, key: string) => (key === "games" ? games[r.player.name] : undefined);
  assert.equal(sortAvailable(rows, { key: "games", dir: "desc" }, extra).map((r) => r.player.name).join(""), "CAB");
  // A key nobody gives sorts nothing: Yahoo's order stands.
  assert.equal(sortAvailable(rows, { key: "pts", dir: "desc" }).map((r) => r.player.name).join(""), "ABC");
});

const RATES: Rates = { pts: 12.6, threes: 1, reb: 5, ast: 3, stl: 1, blk: 0.5, tov: 2, fgm: 5, fga: 10, ftm: 1.6, fta: 2 };

test("a horizon's games: this week, or the next three weeks together", () => {
  assert.equal(horizonGames([3, 4, 3, 4], "week"), 3);
  assert.equal(horizonGames([3, 4, 3, 4], "next3"), 11);
  assert.equal(horizonGames([2], "next3"), null);
  assert.equal(horizonGames([], "week"), null);
  assert.equal(horizonGames(undefined, "week"), null);
});

test("projected totals multiply the rates out; percentages are makes over attempts", () => {
  const nine = ["fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov"] as const;
  const t = projectedTotals(RATES, 3, nine);
  assert.ok(t);
  assert.ok(Math.abs((t.pts ?? 0) - 37.8) < 1e-9);
  assert.equal(t.reb, 15);
  assert.equal(t.fg_pct, 0.5);
  assert.equal(t.ft_pct, 0.8);
  assert.equal(projectedTotals(RATES, 0, nine)?.fg_pct, null);
  assert.equal(projectedTotals(RATES, 0, nine)?.pts, 0);
  assert.equal(projectedTotals(null, 3, nine), null);
  assert.equal(projectedTotals(RATES, null, nine), null);
  // A points league: weights over the rates.
  const fp = projectedTotals(RATES, 2, ["fpts"], { pts: 1, reb: 1.2, ast: 1.5, blk: 3, stl: 3, tov: -1 });
  assert.ok(fp && Math.abs((fp.fpts ?? 0) - 2 * (12.6 + 6 + 4.5 + 1.5 + 3 - 2)) < 1e-9);
});

test("category cells and odds labels", () => {
  assert.equal(catValue("fg_pct", 0.4861), ".486");
  assert.equal(catValue("pts", 37.84), "37.8");
  assert.equal(catValue("pts", null), "");
  assert.equal(oddsLabel(0.737), "74%");
  assert.equal(oddsLabel(0.001), "<1%");
  assert.equal(oddsLabel(0.999), ">99%");
  assert.equal(oddsTone(0.7), "good");
  assert.equal(oddsTone(0.2), "bad");
  assert.equal(oddsTone(0.5), "");
});

test("the table opens on the three-week gain; until the moves are valued Yahoo's order stands", () => {
  const rows = [row(player("A", ["C"])), row(player("B", ["C"])), row(player("C", ["C"]))];
  const gains: Record<string, number | null> = { A: 0.2, B: null, C: 1.1 };
  const extra = (r: AvailableRow, key: string) => (key === "gain_three" ? gains[r.player.name] : undefined);
  assert.deepEqual(DEFAULT_AVAILABLE_SORT, { key: "gain_three", dir: "desc" });
  assert.equal(sortAvailable(rows, DEFAULT_AVAILABLE_SORT, extra).map((r) => r.player.name).join(""), "CAB");
  assert.equal(sortAvailable(rows, DEFAULT_AVAILABLE_SORT).map((r) => r.player.name).join(""), "ABC");
});

test("a gain reads signed, to two places, and is toned against the move's floor", () => {
  assert.equal(gainLabel(0.4249), "+0.42");
  assert.equal(gainLabel(-0.1), "−0.10");
  assert.equal(gainLabel(-0.001), "0.00");
  assert.equal(gainLabel(null), "");
  assert.equal(gainLabel(1.23456, 3), "+1.235");
  assert.equal(gainTone(0.5, 0.01), "good");
  assert.equal(gainTone(0.005, 0.01), "");
  assert.equal(gainTone(-0.2, 0.01), "bad");
  assert.equal(gainTone(undefined, 0.01), "");
  assert.equal(dayLabel("2026-10-22"), "Oct 22");
  assert.equal(dayLabel(null), "");
});

test("a candidate's drawer opens on his best drop for the table's horizon, else the other's", () => {
  const c: MoveCandidate = {
    from: "2026-10-22",
    week: { gain: 0.3, drop: 7, next_drop: 8, next_price: 0.1 },
    three: { gain: 0.9, drop: 8, next_drop: null, next_price: null },
  };
  assert.equal(MOVE_HORIZON.next3, "three");
  assert.equal(bestMove(c, "week")?.gain, 0.3);
  assert.equal(openingDrop(c, MOVE_HORIZON.week), 7);
  assert.equal(openingDrop(c, MOVE_HORIZON.next3), 8);
  assert.equal(openingDrop({ ...c, week: null }, "week"), 8);
  // No move fits on either horizon: the drawer opens on an open spot.
  assert.equal(openingDrop({ ...c, week: null, three: null }, "week"), null);
  assert.equal(openingDrop(undefined, "three"), null);
});

test("the add limit reads as a floor when the transactions page may not reach the week's start", () => {
  const weeks = [{ start: "2026-10-20", end: "2026-10-26", adds: 3 }];
  assert.equal(addsNote({ limit: 4, used: 1, complete: true, left: 3, weeks }), "4 adds a week · 1 used this week · 3 left");
  assert.equal(addsNote({ limit: 4, used: 1, complete: false, left: 3, weeks }), "4 adds a week · at least 1 used this week · at most 3 left");
  assert.equal(addsNote({ limit: null, used: 0, complete: true, left: null, weeks }), "no weekly add limit");
});

test("the view's players by id: the pool, my roster and every roster", () => {
  const slot = (p: SeasonPlayer, s = "BN"): RosterRow => ({ slot: s, player: p, games_left: null });
  const a = player("Pool Guy", ["PG"], { yahoo_id: 1 });
  const b = player("Mine", ["C"], { yahoo_id: 2 });
  const c = player("Theirs", ["SF"], { yahoo_id: 3 });
  const byId = playersById({ available: [row(a)], roster: [slot(b)], rosters: { "4": [slot(c)], "1": [slot(b)] } });
  assert.deepEqual([...byId.keys()].sort(), [1, 2, 3]);
  assert.equal(byId.get(3)?.name, "Theirs");
});

const signal = (score: number, reason: string | null = null): FlagSignal => ({ score, reason, facts: {} });
const flag = (level: PlayerFlag["level"], surge: number, minutes = 0, value = 0, opportunity = 0): PlayerFlag => ({
  level,
  score: surge + minutes + value + opportunity,
  signals: {
    surge: signal(surge, surge ? "7,206 adds today, #1 by adds on Yahoo's buzz index" : null),
    minutes: signal(minutes, minutes ? "34.0 min over the last 7 days (3 games) against 26.0 projected" : null),
    value: signal(value),
    opportunity: signal(opportunity, opportunity ? "Cade Cunningham (G) out, est. return Nov 12" : null),
  },
});

// The season view's flag_config as the API sends it today; a retune changes the numbers, not the code.
const CONFIG: FlagConfig = {
  levels: [
    { level: "must-add", floor: 2.2 },
    { level: "add", floor: 1.5 },
    { level: "watch", floor: 0.8 },
  ],
  max: 4,
  opportunity_needs_another: true,
  past_days_max_days: 3,
  signals: {
    surge: { name: "adds surge", jump_full: 2.5, jump_floor: 1, history_days: 3, adds_full: 8, adds_floor: 25, buzz_rows: 50, buzz_last: 0.3 },
    minutes: { name: "minutes up", minutes_full: 8, usage_full: 5, usage_weight: 0.5, min_games: { "14": 4, "7": 2 } },
    value: { name: "value gap", rank: 120, pct: 50, rank_scale: 240 },
    opportunity: { name: "opportunity", out_days: 14, full: 30, unknown_mpg: 15 },
  },
};

test("a flag's tag, its signals loudest first and its evidence on hover", () => {
  const f = flag("add", 1, 0.75);
  assert.equal(FLAG_SHORT.add, "A");
  assert.equal(FLAG_SHORT["must-add"], "M+");
  assert.deepEqual(flagSignals(flag("watch", 0.3, 0, 0, 0.5)), ["opportunity", "surge"]);
  // The thresholds are the API's, so the hover follows a retune; without them it names none.
  assert.equal(levelsLine(CONFIG), "watch 0.8, add 1.5, must-add 2.2");
  assert.equal(flagTitle(f).split("\n")[0], "add · 1.75");
  assert.equal(flagTitle(f, { ...CONFIG, levels: [{ level: "add", floor: 1.2 }] }).split("\n")[0], "add · 1.75 of 4 (add 1.2)");
  assert.equal(
    flagTitle(f, CONFIG),
    "add · 1.75 of 4 (watch 0.8, add 1.5, must-add 2.2)\n" +
      "adds surge 1.00: 7,206 adds today, #1 by adds on Yahoo's buzz index\n" +
      "minutes up 0.75: 34.0 min over the last 7 days (3 games) against 26.0 projected",
  );
  assert.ok(flagTitle(flag(null, 0.3, 0, 0, 0.4), CONFIG).startsWith("under watch · 0.70"));
  // Opportunity alone: the server scores it 0, the hover says why and keeps the evidence.
  const alone = { ...flag(null, 0, 0, 0, 0.5), score: 0 };
  assert.equal(
    flagTitle(alone, CONFIG),
    "not flagged: opportunity counts only beside another signal\nopportunity 0.50: Cade Cunningham (G) out, est. return Nov 12",
  );
});

test("a flag's breakdown: every signal in order with its evidence, a silent one says why, the sum against the levels", () => {
  const b = flagBreakdown(flag("add", 1, 0.75), CONFIG, { value: "no rest-of-season export: no rank on the league's scoring" });
  assert.deepEqual(
    b.signals.map((x) => [x.key, x.score, x.reason !== null, x.silent, x.counted]),
    [
      ["surge", 1, true, null, true],
      ["minutes", 0.75, true, null, true],
      ["value", 0, false, "no rest-of-season export: no rank on the league's scoring", true],
      ["opportunity", 0, false, null, true],
    ],
  );
  assert.equal(b.line, "1.75 of 4: add (from 1.5); must-add at 2.2, 0.45 more");
  assert.deepEqual(
    b.levels.map((l) => [l.level, l.reached]),
    [
      ["watch", true],
      ["add", true],
      ["must-add", false],
    ],
  );
  // The top level has nothing above it; under watch names the first level.
  assert.equal(flagBreakdown(flag("must-add", 1, 1, 0.5), CONFIG).line, "2.50 of 4: must-add (from 2.2)");
  assert.equal(flagBreakdown(flag(null, 0.3, 0, 0, 0.4), CONFIG).line, "0.70 of 4: not flagged; watch at 0.8, 0.10 more");
  // A signal that spoke is never silent, whatever the inputs say about the league.
  assert.equal(flagBreakdown(flag("add", 1, 0.75), CONFIG, { minutes: "no past-days export within 3 days" }).signals[1].silent, null);
  // Opportunity alone: shown with its evidence, not counted, and the line says why.
  const alone = flagBreakdown({ ...flag(null, 0, 0, 0, 0.5), score: 0 }, CONFIG);
  assert.deepEqual([alone.signals[3].score, alone.signals[3].counted, alone.signals[3].reason !== null], [0.5, false, true]);
  assert.equal(alone.line, "0.00 of 4: not flagged, opportunity counts only beside another signal; watch from 0.8");
  // Without the view's config: no thresholds to show.
  assert.deepEqual([flagBreakdown(flag("add", 1, 0.75)).levels, flagBreakdown(flag("add", 1, 0.75)).line], [[], "1.75 of 4: add"]);
});

test("the flag's explainer takes every number from the API and names the signals left silent", () => {
  const x = flagExplainer(CONFIG, { minutes: "no past-days export within 3 days" });
  assert.deepEqual(
    x.signals.map((sg) => [sg.key, sg.name, sg.silent]),
    [
      ["surge", "adds surge", null],
      ["minutes", "minutes up", "no past-days export within 3 days"],
      ["value", "value gap", null],
      ["opportunity", "opportunity", null],
    ],
  );
  assert.equal(x.levels, "Each signal scores from 0 to 1 and the level comes from their sum, at most 4: watch from 0.8, add from 1.5, must-add from 2.2.");
  assert.ok(x.signals[1].text.includes("(2 in 7 days, 4 in 14 days)") && x.signals[1].text.includes("last 3 days"));
  assert.ok(x.signals[2].text.startsWith("ranked inside the top 120") && x.signals[2].text.includes("under 50%"));
  assert.ok(x.signals[3].text.endsWith("It counts toward the level only beside another signal."));
  assert.ok(x.caveat.includes("first guess"));
  // A retune shows at once.
  const tuned = flagExplainer({ ...CONFIG, opportunity_needs_another: false, signals: { ...CONFIG.signals, value: { ...CONFIG.signals.value, rank: 150 } } });
  assert.ok(tuned.signals[2].text.startsWith("ranked inside the top 150"));
  assert.ok(!tuned.signals[3].text.includes("beside another signal"));
});

test("the flagged players have a level, the highest first; a signal alone is not a flag", () => {
  const a = row(player("Andre Drummond", ["C"], { yahoo_id: 5015 }));
  const b = row(player("Keldon Johnson", ["SF", "PF"], { yahoo_id: 6217 }));
  const c = row(player("Duncan Robinson", ["SG", "SF"], { yahoo_id: 6073 }));
  const s = { available: [a, b, c], flags: { "5015": flag("watch", 1), "6217": flag("watch", 0.94, 0, 0, 0.5), "6073": flag(null, 0, 0, 0, 0.5) } };
  assert.deepEqual(
    flagged(s).map((x) => x.row.player.name),
    ["Keldon Johnson", "Andre Drummond"],
  );
  assert.equal(flagOf(s, 6073)?.level, null);
  assert.equal(flagOf({ flags: undefined }, 6073), undefined);
  // The table's Flag column sorts on the score, unflagged players last.
  const sorted = sortAvailable([c, a, b, row(player("Nobody", ["C"], { yahoo_id: 1 }))], { key: "flag", dir: "desc" }, (r, key) =>
    key === "flag" ? (flagOf(s, r.player.yahoo_id)?.score ?? null) : undefined,
  );
  assert.deepEqual(
    sorted.map((r) => r.player.name),
    ["Keldon Johnson", "Andre Drummond", "Duncan Robinson", "Nobody"],
  );
});

test("the flags card says what its inputs were read from, and what is missing", () => {
  const now = Date.parse("2026-10-21T18:00:00Z");
  const note = flagInputsNote(
    {
      buzz: { today: "2026-10-21T17:55:00+00:00", rows: 50, earlier_days: 0 },
      injuries: { read_at: "2026-10-21T17:55:00+00:00", players: 81 },
      projection: null,
      past_days: { "7d": { file: "bbm_actual_7d_totals_20261021-1500.xls", as_of: "2026-10-21T15:00:00+00:00" }, "14d": null },
    },
    now,
  );
  assert.equal(note, "buzz index read 5 min ago · 81 on the injury report · past 7 days 2026-10-21 · no past 14 days · no rest-of-season export");
  assert.equal(flagInputsNote({ error: "KeyError: x" }, now), "no flags: KeyError: x");
  assert.equal(flagInputsNote(undefined, now), "no flag inputs yet");
});

test("a trade reads as no worse or worse on our model, never as accepted", () => {
  assert.equal(tradeVerdict(0.42), "no worse on our model");
  assert.equal(tradeVerdict(-0.004), "no worse on our model");
  assert.equal(tradeVerdict(-0.2), "worse on our model");
});

test("the trade margin names the share of the projection, or the end it falls past", () => {
  const m = { horizon: "three" as const, change: 0.99, max: 3 };
  assert.equal(marginText({ ...m, neutral: 0.608, reading: "crosses" }), "neutral if what I receive produces 61% of its projection");
  assert.equal(marginText({ ...m, neutral: 1.185, reading: "crosses" }), "neutral if what I receive produces 119% of its projection");
  assert.equal(marginText({ ...m, neutral: null, reading: "wins_at_zero" }), "no worse for me even if what I receive produces nothing");
  assert.equal(marginText({ ...m, neutral: null, reading: "loses_at_max" }), "worse for me even if what I receive produces 300% of its projection");
  assert.equal(marginText(null), "");
});

test("the trade's date says whether it is the review's or the one asked", () => {
  assert.equal(effectiveNote({ effective: "2026-10-23", effective_rule: "review", review_days: 2 }), "takes effect Oct 23 if accepted today, after the league's 2-day review");
  assert.equal(effectiveNote({ effective: "2026-10-21", effective_rule: "review", review_days: 0 }), "takes effect Oct 21 if accepted today (the league does not review trades)");
  assert.equal(effectiveNote({ effective: "2026-10-26", effective_rule: "requested", review_days: 2 }), "takes effect Oct 26, the date asked");
});

test("a side's roster after the trade: fits, opens a spot, or is not valid as entered", () => {
  const name = (id: number) => `P${id}`;
  const roster = (over: Partial<TradeSide["roster"]>): TradeSide["roster"] => ({ spots: 13, active: 13, open: 0, valid: true, held_moves: [], drops: [], ...over });
  assert.equal(rosterNote(roster({}), name), "fits");
  assert.equal(rosterNote(roster({ active: 12, open: 1 }), name), "1 spot open");
  const drop = { player: 7, name: "Paul Reed", nba_team: "DET", positions: ["C"], status: null };
  assert.equal(
    rosterNote(roster({ active: 14, valid: false, drops: [drop] }), name),
    "not valid in Yahoo as entered: 14 players for 13 spots, so Paul Reed would go (least missed)",
  );
  assert.equal(rosterNote(roster({ held_moves: [{ player: 3, slot: "IL" }] }), name), "fits; P3 to IL");
});

test("a traded player's games: his old team's until the date, then his new one's", () => {
  const g = (games: number, started: number) => ({ games, started });
  const p: TradePlayer = {
    player: 1,
    name: "Cooper Flagg",
    nba_team: "DAL",
    positions: ["SF"],
    status: null,
    from: 10,
    to: 4,
    games: { week: { before: g(3, 3), old: g(1, 1), new: g(2, 2) }, three: { before: g(11, 10), old: g(0, 0), new: g(11, 11) } },
  };
  assert.equal(movedGames(p, "week"), "1 + 2");
  assert.equal(movedGamesTitle(p, "week", "Team 10", "me"), "1 games (1 started) for Team 10, then 2 (2 started) for me; 3 games without the trade");
});

test("a recorded week's result reads as categories or points, with its outcome", () => {
  assert.equal(weekResult({ won: 5, lost: 3, tied: 1, outcome: "W" }), "5-3-1 W");
  assert.equal(weekResult({ points: 810.5, against: 790.25, outcome: "W" }), "810.5–790.3 W");
  assert.equal(weekResult(null), "");
  assert.equal(weekTone({ won: 3, lost: 5, tied: 1, outcome: "L" }), "bad");
  assert.equal(weekTone({ won: 4, lost: 4, tied: 1, outcome: "T" }), "");
});

test("a held player's return names the drop it forces, the earliest day per player", () => {
  const name = (id: number) => `P${id}`;
  assert.equal(comebackText([undefined, []], name), null);
  const three = [
    { player: 5, slot: "IL", from: "2026-11-02", drop: 3 },
    { player: 7, slot: "IL+", from: "2026-11-02", drop: 7 },
  ];
  const week = [{ player: 7, slot: "IL+", from: "2026-10-28", drop: 7 }];
  assert.equal(
    comebackText([week, three], name),
    "From Oct 28, P7 goes on return; from Nov 2, P3 goes when P5 returns.",
  );
});

// ---------------------------------------------------------------- landing grid (#108)
const card = (league: string, extra: Partial<SeasonSummary> = {}) =>
  ({ league, name: `League ${league}`, scoring: "categories", num_teams: 12, has_snapshot: true, my_team: null, ...extra }) as SeasonSummary;
const solved = (league: string, gain: number | null): BestMove => ({
  league,
  status: "solved",
  system: "bbm",
  horizon: "three",
  label: "weeks 2-4 against the field",
  move: gain == null ? null : { add: 1, add_name: "Add One", drop: 2, drop_name: "Drop Two", from: "2026-10-22", gain },
  moves: gain == null ? 0 : 1,
  gain: gain ?? 0,
  min_gain: 0.01,
});

test("a league card reads its score mine first, its place, its adds and its flags", () => {
  assert.equal(scoreLabel(card("1", { score: [5, 3] })), "5-3");
  assert.equal(scoreLabel(card("1", { scoring: "points", score: [93.24, 101.9] })), "93.2–101.9");
  assert.equal(scoreLabel(card("1", { score: null })), "no score yet");
  assert.equal(placeLabel(card("1", { my_team: { team_id: 4, name: "Team 4", record: "0-0-0", rank: 2 } })), "2nd of 12");
  assert.equal(placeLabel(card("1")), "no place yet");
  assert.equal(addsLeft({ limit: 4, used: 1, complete: true, left: 3 }), "3 of 4 adds left");
  assert.equal(addsLeft({ limit: 4, used: 0, complete: false, left: 4 }), "at most 4 of 4 adds left");
  assert.equal(addsLeft({ limit: null, used: 0, complete: true, left: null }), "no add limit");
  assert.equal(flagCounts({ watch: 11, add: 1 }), "1 add · 11 watch");
  assert.equal(flagCounts({}), "no flags");
  assert.equal(flagCounts(null), "");
});

test("the best move reads as an add for a drop, an add to an open spot, or no move", () => {
  const b = solved("1", 0.4) as Extract<BestMove, { status: "solved" }>;
  assert.equal(bestLine(b), "Add Add One for Drop Two");
  assert.equal(bestLine({ ...b, move: { ...b.move!, drop: null, drop_name: null } }), "Add Add One");
  assert.equal(bestLine(solved("1", null) as Extract<BestMove, { status: "solved" }>), "no move gains 0.01");
  assert.equal(bestGain(b), 0.4);
  assert.equal(bestGain(solved("1", null)), null);
  assert.equal(bestGain({ league: "1", status: "not_solved", system: "bbm" }), null);
  assert.equal(bestGain(undefined), null);
});

test("the grid puts most to gain first, then the leagues not solved, no move, and not read", () => {
  const seasons = [card("none"), card("cold"), card("small"), card("unread", { has_snapshot: false }), card("big"), card("broken", { error: "no folder" })];
  const best = new Map<string, BestMove | undefined>([
    ["none", solved("none", null)],
    ["small", solved("small", 0.1)],
    ["big", solved("big", 0.5)],
    ["cold", { league: "cold", status: "not_solved", system: "bbm" }],
  ]);
  assert.deepEqual(
    gridOrder(seasons, best, "gain").map((s) => s.league),
    ["big", "small", "cold", "none", "broken", "unread"],
  );
  assert.deepEqual(
    gridOrder(seasons, best, "name").map((s) => s.league),
    ["big", "cold", "none", "small", "broken", "unread"],
  );
});
