// Node's own test runner with its built-in type stripping (`npm test`), as format.test.ts.
import assert from "node:assert/strict";
import { test } from "node:test";
import type {
  AutopilotView,
  AvailableRow,
  BestMove,
  BestSetLine,
  FlagConfig,
  FlagSignal,
  KeepRule,
  KeptPlayer,
  LineupDay,
  LineupRunLog,
  MoveCandidate,
  MoveRos,
  MovesPassLog,
  MovesView,
  PlayerFlag,
  QueueEntry,
  PassTally,
  QueueLeague,
  QueuePass,
  QueuePayload,
  Rates,
  RosterRow,
  MovesSummary,
  SeasonGuard,
  ScorecardMove,
  ScorecardToDate,
  ScorecardWeek,
  SeasonPlayer,
  SeasonSummary,
  Stash,
  StrategyPoint,
  StreamPlan,
  TradePlayer,
  TradeSide,
} from "./api";
import {
  axisRange,
  axisTicks,
  defaultWeight,
  firstOrderLists,
  frontierMarks,
  isSolving,
  milpLabel,
  guardSteps,
  planNote,
  planRosText,
  planShortLine,
  planStepRosTitle,
  playerRosTitle,
  rosGames,
  rosHeadTitle,
  rosLabel,
  rosTitle,
  rosTone,
  sideRosTitle,
  seasonGuardLine,
  seasonGuardMoves,
  valueUnits,
  shownPlan,
  sourceText,
  stepDay,
  strategySettingsChanged,
  strategyUnits,
  addsLeft,
  addsNote,
  bestGain,
  bestLine,
  flagCounts,
  gridOrder,
  isExpanded,
  landingRows,
  leaguesLabel,
  bestNamer,
  placeTone,
  setLine,
  setSummary,
  toggleExpanded,
  placeLabel,
  scoreLabel,
  daysLeftLabel,
  chipTone,
  defaultWeek,
  outlookSummary,
  leanTone,
  matchupRecord,
  oddsGainLabel,
  ageLabel,
  availabilityLabel,
  bestMove,
  catValue,
  changeLabel,
  comebackText,
  dayLabel,
  effectiveNote,
  forText,
  gainLabel,
  keepLine,
  keepPhrase,
  keepRuleNote,
  keptPlayers,
  keptWhy,
  benchPlaying,
  executorText,
  bidLabel,
  countdownLabel,
  movesExecutorText,
  movesLiveText,
  passLine,
  queueFloorLine,
  queueFlagWord,
  queueFoldLine,
  queueMoveText,
  queueNamer,
  queueOrder,
  queueStateText,
  queueStateTone,
  passTally,
  passTitle,
  addsThisWeek,
  centralClock,
  notQueued,
  stripOrder,
  switchRows,
  switchScope,
  modesWord,
  commonMode,
  liveSplit,
  allLiveLine,
  allLiveTitle,
  keptLines,
  stripReason,
  addBasis,
  basisPhrase,
  roomNote,
  heldEligibleText,
  liveText,
  runLine,
  stepText,
  lineupAlertText,
  lineupGrid,
  lineupSummary,
  ruleText,
  weekdayLabel,
  marginText,
  movedGames,
  movedGamesTitle,
  rosterNote,
  stashText,
  tradeVerdict,
  weekResult,
  weekTone,
  MATCH_WORDS,
  movesSummaryLine,
  moveWhat,
  realizedLabel,
  realizedTitle,
  scorecardToDateLine,
  scorecardWeekLine,
  unitsLabel,
  gainTone,
  horizonGames,
  MOVE_HORIZON,
  openingDrop,
  oddsLabel,
  oddsTone,
  projectedTotals,
  DEFAULT_AVAILABLE_SORT,
  filterAvailable,
  FLAG_MEANS,
  FLAG_READS,
  FLAG_SHORT,
  FLAG_TONE,
  FLAG_UNDER_MEANS,
  flagged,
  flagMeter,
  flagScore,
  flagTag,
  readWatch,
  WATCH_KEY,
  writeWatch,
  flagInputsNote,
  flagLegend,
  flagLevels,
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
  waiversNote,
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
  assert.equal(FLAG_SHORT.add, "add");
  assert.equal(FLAG_SHORT["must-add"], "must-add");
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
  assert.ok(x.signals[3].text.endsWith("nothing while he is out himself."));
  assert.equal(x.alone, "Alone, opportunity flags no one: it counts toward the level only beside another signal.");
  assert.ok(x.caveat.includes("first guess"));
  // A retune shows at once.
  const tuned = flagExplainer({ ...CONFIG, opportunity_needs_another: false, signals: { ...CONFIG.signals, value: { ...CONFIG.signals.value, rank: 150 } } });
  assert.ok(tuned.signals[2].text.startsWith("ranked inside the top 150"));
  assert.equal(tuned.alone, null);
});

// A retuned config: every floor and threshold differs from today's, so a number written into the
// web would show here.
const TUNED: FlagConfig = {
  levels: [
    { level: "must-add", floor: 3.1 },
    { level: "add", floor: 2.05 },
    { level: "watch", floor: 1.15 },
  ],
  max: 5,
  opportunity_needs_another: true,
  past_days_max_days: 6,
  signals: {
    surge: { name: "adds surge", jump_full: 3.5, jump_floor: 2, history_days: 5, adds_full: 9, adds_floor: 35, buzz_rows: 60, buzz_last: 0.4 },
    minutes: { name: "minutes up", minutes_full: 7, usage_full: 6, usage_weight: 0.6, min_games: { "14": 5, "7": 3 } },
    value: { name: "value gap", rank: 130, pct: 45, rank_scale: 260 },
    opportunity: { name: "opportunity", out_days: 12, full: 28, unknown_mpg: 14 },
  },
};

test("the flags legend: the levels lowest first with their floors and what each recommends, every number the API's", () => {
  const now = Date.parse("2026-10-25T15:00:00Z");
  const inputs = { buzz: { today: "2026-10-25T14:55:00Z", rows: 50, earlier_days: 2 }, injuries: { read_at: "2026-10-25T14:50:00Z", players: 81 }, silent: { minutes: "no past-days export within 6 days" } };
  const x = flagLegend(TUNED, inputs, now);
  assert.deepEqual(
    x.levels.map((l) => [l.level, l.floor]),
    [
      ["watch", 1.15],
      ["add", 2.05],
      ["must-add", 3.1],
    ],
  );
  assert.deepEqual(
    x.levels.map((l) => l.means),
    [FLAG_MEANS.watch, FLAG_MEANS.add, FLAG_MEANS["must-add"]],
  );
  assert.equal(x.scale, "Each signal scores from 0 to 1; the level comes from their sum, at most 5.");
  assert.deepEqual(
    x.signals.map((sg) => [sg.key, sg.name, sg.reads, sg.silent]),
    [
      ["surge", "adds surge", FLAG_READS.surge, null],
      ["minutes", "minutes up", FLAG_READS.minutes, "no past-days export within 6 days"],
      ["value", "value gap", FLAG_READS.value, null],
      ["opportunity", "opportunity", FLAG_READS.opportunity, null],
    ],
  );
  // Each rule carries the tuned numbers.
  assert.ok(x.signals[0].rule.includes("3.5×") && x.signals[0].rule.includes("the 60th 0.4"));
  assert.ok(x.signals[1].rule.includes("(3 in 7 days, 5 in 14 days)") && x.signals[1].rule.includes("last 6 days"));
  assert.ok(x.signals[2].rule.startsWith("ranked inside the top 130") && x.signals[2].rule.includes("under 45%"));
  assert.ok(x.signals[3].rule.includes("at least 12 more days") && x.signals[3].rule.includes("28 minutes"));
  assert.equal(x.alone, "Alone, opportunity flags no one: it counts toward the level only beside another signal.");
  assert.equal(flagLegend({ ...TUNED, opportunity_needs_another: false }, inputs, now).alone, null);
  assert.equal(x.read, flagInputsNote(inputs, now));
  assert.ok(x.caveat.includes("first guess"));
  // Every level has its tag, its tone and its words; the wording recommends, never claims the best.
  for (const l of x.levels) assert.ok(FLAG_SHORT[l.level] && FLAG_TONE[l.level] && FLAG_MEANS[l.level]);
  const text = JSON.stringify(x);
  assert.ok(text.includes("recommended") && !/optimal/i.test(text));
});

test("the Flags card counts the flagged players by level, the highest first", () => {
  const p = (n: number) => row(player(`Player ${n}`, ["G"], { yahoo_id: n }));
  const s = {
    available: [p(1), p(2), p(3), p(4), p(5), p(6)],
    flags: { "1": flag("must-add", 2.4), "2": flag("add", 1.6), "3": flag("watch", 0.9), "4": flag("watch", 0.85), "5": flag(null, 0.3), "6": flag(null, 0, 0, 0, 0.5) },
  };
  assert.deepEqual(flagLevels(s), { "must-add": 1, add: 1, watch: 2 });
  assert.equal(flagCounts(flagLevels(s)), "1 must-add · 1 add · 2 watch");
  // An empty level is left out.
  assert.equal(flagCounts(flagLevels({ available: [p(3)], flags: { "3": flag("watch", 0.9) } })), "1 watch");
});

test("the tag reads the level and the score cut to one decimal; under watch only with the toggle on", () => {
  assert.deepEqual(flagTag(flag("add", 1, 0.73)), { label: "add", score: "1.7", level: "add" });
  assert.deepEqual(flagTag(flag("must-add", 1, 1, 0.4)), { label: "must-add", score: "2.4", level: "must-add" });
  // A 1.46 is a watch under the 1.5 floor: it never reads as 1.5.
  assert.equal(flagScore(1.46), "1.4");
  assert.equal(flagScore(1.5), "1.5");
  assert.equal(flagScore(0.3 + 0.2), "0.5");
  // Under watch: a dimmed "under" with the toggle on, nothing without it.
  const under = flag(null, 0.42, 0.2);
  assert.equal(flagTag(under), null);
  assert.deepEqual(flagTag(under, true), { label: "under", score: "0.6", level: null });
  // Opportunity alone: the server scores it 0, so never a tag, toggle or not.
  assert.equal(flagTag({ ...flag(null, 0, 0, 0, 0.5), score: 0 }, true), null);
  assert.equal(flagTag(undefined, true), null);
});

test("the tag's meter fills the score's share of the most and ticks each floor, the API's numbers", () => {
  // TUNED: floors 1.15, 2.05, 3.1 of 5.
  const m = flagMeter(2.4, TUNED);
  assert.equal(m.fill, 2.4 / 5);
  assert.equal(m.max, 5);
  assert.deepEqual(
    m.ticks.map((t) => [t.level, t.floor, t.at, t.reached]),
    [
      ["watch", 1.15, 1.15 / 5, true],
      ["add", 2.05, 2.05 / 5, true],
      ["must-add", 3.1, 3.1 / 5, false],
    ],
  );
  // At a floor exactly, the tick is reached; the fill is clamped to the bar.
  assert.equal(flagMeter(2.05, TUNED).ticks[1].reached, true);
  assert.equal(flagMeter(6, TUNED).fill, 1);
  assert.equal(flagMeter(-0.2, TUNED).fill, 0);
  // Without the config: the four signals' most, and no ticks.
  assert.deepEqual(flagMeter(1, undefined), { fill: 0.25, max: 4, ticks: [] });
});

test("the legend shows the levels' tags, a dimmed under-watch sample and a meter at the second floor", () => {
  const x = flagLegend(TUNED, undefined, 0);
  assert.deepEqual(x.under, { below: 1.15, means: FLAG_UNDER_MEANS });
  assert.deepEqual(x.sample, { level: "add", score: 2.05 });
  assert.deepEqual(
    x.levels.map((l) => FLAG_SHORT[l.level]),
    ["watch", "add", "must-add"],
  );
});

test("the show-under-watch toggle is kept per browser, off by default and when storage fails", () => {
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
  assert.equal(readWatch(store), false);
  writeWatch(store, true);
  assert.equal(kept.get(WATCH_KEY), "1");
  assert.equal(readWatch(store), true);
  writeWatch(store, false);
  assert.equal(readWatch(store), false);
  kept.set(WATCH_KEY, "junk");
  assert.equal(readWatch(store), false);
  // A browser that refuses storage: off, and a write that throws is swallowed.
  const refuses = {
    getItem: (): string | null => {
      throw new Error("SecurityError");
    },
    setItem: () => {
      throw new Error("QuotaExceededError");
    },
  };
  assert.equal(readWatch(refuses), false);
  assert.doesNotThrow(() => writeWatch(refuses, true));
  assert.equal(readWatch(null), false);
});

test("the Flags card orders by level, then score, then name; under watch follows with the toggle on", () => {
  const p = (n: number, name: string) => row(player(name, ["G"], { yahoo_id: n }));
  const s = {
    available: [p(1, "Ann"), p(2, "Bea"), p(3, "Cal"), p(4, "Dee"), p(5, "Eve"), p(6, "Fay"), p(7, "Gus")],
    flags: {
      "1": flag("watch", 0.9),
      "2": flag("must-add", 2.3),
      "3": flag("add", 1.6),
      "4": flag("add", 1.9),
      "5": flag(null, 0.5),
      "6": flag("add", 1.6),
      "7": { ...flag(null, 0, 0, 0, 0.5), score: 0 },
    },
  };
  const names = (opts?: { watch?: boolean }) => flagged(s, opts).map((x) => x.row.player.name);
  assert.deepEqual(names(), ["Bea", "Dee", "Cal", "Fay", "Ann"]);
  assert.deepEqual(names({ watch: true }), ["Bea", "Dee", "Cal", "Fay", "Ann", "Eve"]);
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

test("an add goes in for his drop, the held move that makes room, or an open spot", () => {
  const name = (id: number | null) => (id == null ? "an open spot" : `P${id}`);
  assert.equal(forText({ drop: 4 }, name), "P4");
  assert.equal(forText({ drop: null, held: { player: 6, slot: "IL" } }, name), "P6 to IL");
  assert.equal(forText({ drop: null, held: null }, name), "an open spot");
});

test("an add's basis reads as an open spot, a held move or a drop, the For cell a drop's name alone", () => {
  const name = (id: number) => `P${id}`;
  const open = addBasis({ drop: null, held: null }, name);
  assert.deepEqual([open.kind, open.text, open.cell], ["open", "free: open spot", "free: open spot"]);
  assert.match(open.title, /active spot is open/);
  assert.equal(basisPhrase(open), "(free: open spot)");
  const held = addBasis({ drop: null, held: { player: 5, slot: "IL" } }, name);
  assert.deepEqual([held.kind, held.text, held.cell], ["held", "after P5 to IL", "after P5 to IL"]);
  assert.match(held.title, /P5's status fits the open IL slot/);
  assert.match(held.title, /his return sends the weakest active player/);
  assert.equal(basisPhrase(held), "after P5 to IL");
  const drop = addBasis({ drop: 4, held: null }, name);
  assert.deepEqual([drop.kind, drop.text, drop.cell], ["drop", "for P4", "P4"]);
  assert.match(drop.title, /priced against every drop/);
  assert.equal(basisPhrase(drop), "for P4");
  // A drop is a drop, whatever a stale held field says; held absent is an open spot.
  assert.equal(addBasis({ drop: 4, held: { player: 5, slot: "IL" } }, name).kind, "drop");
  assert.equal(addBasis({ drop: null }, name).kind, "open");
});

test("the Moves card names the room: what is open, else what is full and who waits", () => {
  const name = (id: number) => `P${id}`;
  assert.equal(roomNote({ open_spots: 1, held_open: { IL: 1 }, eligible: [5] }, name), "1 open spot · IL open: 1");
  assert.equal(roomNote({ open_spots: 2, held_open: { IL: 0 }, eligible: [] }, name), "2 open spots");
  assert.equal(roomNote({ open_spots: 0, held_open: { IL: 1, "IL+": 0 }, eligible: [5] }, name), "IL open: 1");
  assert.equal(roomNote({ open_spots: 0, held_open: { IL: 0 }, eligible: [] }, name), "roster full, IL full");
  assert.equal(roomNote({ open_spots: 0, held_open: { IL: 0 }, eligible: [5] }, name), "roster full, IL full (P5 waits)");
  assert.equal(roomNote({ open_spots: 0, held_open: { IL: 0, "IL+": 0 }, eligible: [6, 5] }, name), "roster full, IL full, IL+ full (P6, P5 wait)");
  assert.equal(roomNote({ open_spots: 0, held_open: {}, eligible: [] }, name), "roster full, no held slots");
});

const streamPlan = (over: Partial<StreamPlan> = {}): StreamPlan => ({
  base: [],
  steps: [
    { add: 10, drop: 3, from: "2026-10-22", spot: 3, marginal: { week: 0.2, three: 0 } },
    { add: 11, drop: 10, from: "2026-10-24", spot: 3, marginal: { week: 0.1, three: 0.05 } },
  ],
  spots: [{ player: 3, steps: 2 }],
  games: { none: 24, set: 27, plan: 29 },
  held: [],
  comebacks: {},
  adds: { set: 3, plan: 4 },
  value: { none: { week: 4, three: 20 }, set: { week: 4.5, three: 21 }, plan: { week: 4.8, three: 21.05 } },
  gain: { week: 0.3, three: 0.05 },
  recommended: true,
  short: null,
  floor: 0.1,
  reason: null,
  guard: null,
  ...over,
});

test("a streaming plan is shown only when recommended, its steps by day", () => {
  assert.equal(shownPlan(undefined), null);
  assert.equal(shownPlan(null), null);
  assert.equal(shownPlan(streamPlan({ recommended: false, short: 0.04 })), null);
  assert.equal(shownPlan(streamPlan({ steps: [] })), null);
  const plan = streamPlan();
  assert.equal(shownPlan(plan), plan);
  assert.equal(stepDay("2026-10-22"), "Thu Oct 22");
  assert.equal(stepDay("2026-10-24"), "Sat Oct 24");
});

test("a plan's note gives the games and adds against the set, and the set's moves it keeps", () => {
  const name = (id: number | null) => (id == null ? "an open spot" : `P${id}`);
  assert.equal(planNote(streamPlan(), name), "29 started games against 27 with the set (24 with no move), on 4 adds against 3.");
  const kept = streamPlan({
    base: [
      { add: 5, drop: 6, from: "2026-10-22", marginal: { week: 0.4, three: 0.2 } },
      { add: 7, drop: null, from: "2026-10-22", held: { player: 8, slot: "IL" }, marginal: { week: 0.3, three: 0.1 } },
      { add: 9, drop: null, from: "2026-10-22", marginal: { week: 0.1, three: 0 } },
    ],
    adds: { set: 3, plan: 1 },
  });
  assert.equal(
    planNote(kept, name),
    "29 started games against 27 with the set (24 with no move), on 1 add against 3. It keeps the set's add P5 for P6, add P7 for P8 to IL, add P9.",
  );
});

test("a plan under the floor is one line saying what it would have bought", () => {
  const name = (id: number) => `P${id}`;
  assert.equal(planShortLine(undefined, name), null);
  assert.equal(planShortLine(streamPlan(), name), null);
  const short = { recommended: false, short: 0.06, gain: { week: 0.04, three: 0 }, reason: "short" as const };
  assert.equal(
    planShortLine(streamPlan(short), name),
    "Streaming P3's spot buys 2 more started games for +0.04 this week, under the 0.10 floor.",
  );
  const two = streamPlan({ ...short, spots: [{ player: 3, steps: 1 }, { player: 4, steps: 1 }], games: { none: 20, set: 25, plan: 25 } });
  assert.equal(planShortLine(two, name), "Streaming the spots of P3 and P4 buys +0.04 this week, under the 0.10 floor.");
  // A points league's floor is on the win odds; a plan that buys nothing says so.
  const none = streamPlan({ recommended: false, short: 0.01, gain: { week: 0, three: 0 }, floor: 0.01 });
  assert.equal(planShortLine(none, name), "No streaming plan beats the set this week (floor 0.01).");
  assert.equal(guardSteps(streamPlan(short), name), null);
});

test("a plan the three-week guard refused says what it buys and what it costs, and its steps", () => {
  const name = (id: number | null) => `P${id}`;
  const refused = streamPlan({
    recommended: false,
    short: 0.1,
    gain: { week: 0, three: 0 },
    reason: "guard",
    guard: {
      steps: [
        { add: 10, drop: 3, from: "2026-10-22", spot: 3 },
        { add: 11, drop: 10, from: "2026-10-24", spot: 3 },
      ],
      spots: [3],
      games: 29,
      gain: { week: 0.15, three: -0.47 },
    },
  });
  assert.equal(
    planShortLine(refused, name),
    "Streaming P3's spot buys 2 more started games for +0.15 this week but costs 0.47 over three weeks; not recommended.",
  );
  assert.equal(guardSteps(refused, name), "Thu Oct 22: add P10 for P3; Sat Oct 24: add P11 for P10");
  // The season guard's refusal (#164): what it buys and what it costs the season.
  const costly = streamPlan({ ...refused, reason: "season", guard: { ...refused.guard!, gain: { week: 0.15, three: 0.2 }, ros: { value: -12.44 } } });
  assert.equal(
    planShortLine(costly, name, "categories"),
    "Streaming P3's spot buys 2 more started games for +0.15 this week but costs the season −12.4; the season guard holds it back.",
  );
  assert.equal(guardSteps(costly, name), "Thu Oct 22: add P10 for P3; Sat Oct 24: add P11 for P10");
});

test("a set the season guard changed says what it held back and what this one forgoes (#164)", () => {
  const name = (id: number | null) => `P${id}`;
  const guard: SeasonGuard = {
    held_back: true,
    moves: [
      { add: 10, drop: 3, from: "2026-10-26", marginal: { week: 1.497, three: -6.392 }, ros: null, season_costly: true },
      { add: 12, drop: null, from: "2026-10-26", held: { player: 5, slot: "IL" }, marginal: { week: 0.1, three: 0 }, ros: null, season_costly: null },
    ],
    gain: { week: 1.497, three: -6.392 },
    ros: { value: -95, partial: true },
    forgone: { week: 1.146, three: -6.56 },
    saved: { value: 116, partial: true },
  };
  assert.equal(
    seasonGuardLine(guard, "week", "categories"),
    "The season guard held back a set that gains +1.50 on the week but costs the season −95.0 (a partial total: a move without a season line counts as zero); this one forgoes 1.15.",
  );
  assert.match(seasonGuardLine({ ...guard, ros: { value: -95, partial: false } }, "three", "categories")!, /gains −6\.39 over the three weeks but costs the season −95\.0; this one forgoes 6\.56\.$/);
  assert.equal(seasonGuardMoves(guard, name, "categories"), "add P10 for P3 (season-costly); add P12 for P5 to IL");
  assert.equal(seasonGuardLine({ held_back: false }, "week", "categories"), null);
  assert.equal(seasonGuardLine(null, "week", "categories"), null);
  assert.equal(seasonGuardMoves({ held_back: false }, name, "categories"), null);
});

const keepRule = (players: Partial<KeptPlayer>[]): KeepRule => ({
  floor: 0,
  average: 0,
  best: { player: 9, value: 0.5 },
  players: players.map((k) => ({ player: 0, value: 1, back: null, net_positive: true, beats_best: true, returns: true, protected: false, bench: false, ...k })),
});

test("the keep rule names whom it keeps and benches, and why", () => {
  const name = (id: number) => `P${id}`;
  assert.equal(keepLine(undefined, name), null);
  assert.equal(keepLine(keepRule([{ player: 1, beats_best: false }]), name), null);
  const rule = keepRule([
    { player: 1, protected: true },
    { player: 2, bench: true, net_positive: false, back: "2026-10-25" },
    { player: 3, protected: true },
  ]);
  assert.deepEqual(
    keptPlayers(rule).map((k) => k.player),
    [1, 3, 2],
  );
  assert.equal(
    keepLine(rule, name),
    "The keep rule keeps P1 and P3 (better than the best add, P9, over the rest of the season) and benches P2 (back Oct 25): no move drops them.",
  );
  assert.equal(keptWhy(rule.players[0]), "protected");
  assert.equal(keptWhy(rule.players[1]), "bench, back Oct 25");
  assert.equal(
    keepRuleNote({ ...rule, floor: 0.1 }, name),
    "Protected: above the pool's average (0.00 a game), better than the best add (P9, 0.50) minus 0.1 over the rest of the season, and back this season; benched: better than the best add (P9, 0.50) minus 0.1 and back within a week. No move drops either.",
  );
});

test("the keep rule's header is one phrase, its names in the tooltip (#153)", () => {
  assert.equal(keepPhrase(undefined), null);
  assert.equal(keepPhrase(keepRule([{ player: 1, beats_best: false }])), null);
  const five = keepRule([1, 2, 3, 4, 5].map((player) => ({ player, protected: true })));
  assert.deepEqual(keepPhrase(five), { lead: "Keep rule protects ", count: 5, tail: "" });
  const both = keepRule([{ player: 1, protected: true }, { player: 2, bench: true, back: "2026-10-25" }]);
  const p = keepPhrase(both)!;
  assert.equal(`${p.lead}${p.count}${p.tail}`, "Keep rule protects 1 and benches 1");
  assert.deepEqual(keepPhrase(keepRule([{ player: 2, bench: true }])), { lead: "Keep rule benches ", count: 1, tail: "" });
});

test("the Waivers header is one phrase, every other clause in its tooltip unchanged (#153)", () => {
  const moves = "+1wk and +3wk: what his best move adds in expected categories; click a row for the move · 4 with no line to value";
  const a = {
    label: "Basketball Monster",
    players: 392,
    file: "bbm_projections_2026-10-23.csv",
    asOf: "2026-10-23T10:14:00Z",
    horizon: "next3" as const,
    other: "Yahoo",
    shown: 120,
    total: 150,
    moves,
  };
  const note = waiversNote(a);
  assert.equal(note.phrase, "392 players · next 3 weeks");
  // Today's line, clause by clause: each one is in the tooltip.
  const before =
    "Basketball Monster: 392 players · bbm_projections_2026-10-23.csv, 2026-10-23 · totals over the next 3 weeks, every game he plays counted · " +
    `hover a total for Yahoo's · 120 of the 150 most rostered available players · ${moves}`;
  for (const clause of before.split(" · ")) assert.ok(note.detail.includes(clause), clause);
  assert.equal(note.detail.length, before.split(" · ").length);
  const unread = waiversNote({ ...a, players: 0, file: null, asOf: null, shown: 150, horizon: "week", moves: null });
  assert.equal(unread.phrase, "no projection read · rest of this week");
  assert.deepEqual(unread.detail, [
    "Basketball Monster: nothing read yet",
    "totals over the rest of this week, every game he plays counted",
    "hover a total for Yahoo's",
    "the 150 most rostered available players",
  ]);
  assert.equal(waiversNote({ ...a, file: null }).detail[1], "read 2026-10-23");
});

const stash = (x: Partial<Stash>): Stash => ({
  player: 1,
  status: "O",
  back: "2026-11-02",
  slots: ["IL", "IL+"],
  slot: null,
  protected: true,
  bench: false,
  net: 12.34,
  advice: "bench",
  leave: null,
  add: null,
  ...x,
});

test("a player who is out reads as a stash, a full slot's leaver, bench or droppable", () => {
  const name = (id: number | null) => (id == null ? "an open spot" : `P${id}`);
  assert.equal(
    stashText(stash({ advice: "stash", slot: "IL", add: { week: { player: 5, gain: 0.1 }, three: { player: 6, gain: 0.42 } } }), name),
    "P1 (O, back Nov 2): move to IL, which frees a spot for P6 (+0.42 over the three weeks); 12.3 net of return.",
  );
  assert.equal(stashText(stash({ advice: "stash", slot: "IL", add: { week: { player: 5, gain: 0.1 }, three: null } }), name).includes("P5 (+0.10 this week)"), true);
  // The freed spot's add carries his rest of the season (#151).
  const ros: MoveRos = { value: 8.4, add_games: 50, drop_games: null, extrapolated: { add: 0, drop: null }, from: "2026-10-24", to: "2027-04-12" };
  assert.ok(stashText(stash({ advice: "stash", slot: "IL", add: { week: null, three: { player: 6, gain: 0.42, ros } } }), name, "categories").includes("P6 (+0.42 over the three weeks, ROS +8.4)"));
  assert.equal(
    stashText(stash({ advice: "il_full", leave: { player: 7, slot: "IL", how: "activate", drop: 8, net: null, protected: false } }), name),
    "P1 (O, back Nov 2): eligible, IL or IL+ full; activate P7 (cleared) from IL, dropping P8; 12.3 net of return.",
  );
  assert.equal(
    stashText(stash({ advice: "il_full", net: null, leave: { player: 7, slot: "IL+", how: "drop", drop: 7, net: 3.21, protected: true } }), name),
    "P1 (O, back Nov 2): eligible, IL or IL+ full; P7 should leave IL+, the least value net of return (3.2), though protected: advice only.",
  );
  assert.equal(stashText(stash({ advice: "il_full", slots: ["IL"], net: null }), name), "P1 (O, back Nov 2): eligible, IL full.");
  assert.equal(stashText(stash({ status: "GTD", back: "2026-10-24", protected: false, bench: true }), name), "P1 (GTD, back Oct 24): bench, back Oct 24.");
  assert.equal(stashText(stash({ status: "OFS", back: null, protected: false, advice: "droppable" }), name), "P1 (OFS, no return date): droppable, the moves may take him.");
});

// ---------------------------------------------------------------- lineup view (#107)
const lineupDay = (x: Partial<LineupDay>): LineupDay => ({
  date: "2026-10-22",
  past: false,
  recommended: null,
  bench: null,
  yahoo: null,
  games: { recommended: null, yahoo: null },
  lost: null,
  start: [],
  sit: [],
  playing: [],
  ...x,
});

test("the lineup grid takes each slot's recommended starter, or a past day's Yahoo starter of its kind in turn", () => {
  const slots = ["PG", "C", "C", "Util"];
  const past = lineupDay({
    date: "2026-10-20",
    past: true,
    yahoo: {
      read_at: "x",
      page: "dated page",
      stale: false,
      slots: [
        { slot: "C", player: 3 },
        { slot: "PG", player: 1 },
        { slot: "C", player: 4 },
        { slot: "BN", player: 9 },
      ],
    },
    playing: [1, 3, 9],
  });
  const ahead = lineupDay({
    recommended: [
      { slot: "PG", player: 1 },
      { slot: "C", player: 3 },
      { slot: "C", player: 5 },
      { slot: "Util", player: null },
    ],
    bench: [4, 9],
    start: [5],
    playing: [1, 3, 5, 9],
  });
  const grid = lineupGrid({ slots, days: [past, ahead, lineupDay({ date: "2026-10-23" })] });
  assert.deepEqual(
    grid.map((r) => r.cells[0].player),
    [1, 3, 4, null],
  );
  assert.deepEqual(grid[2].cells[1], { player: 5, source: "recommended", start: true });
  assert.deepEqual(grid[3].cells[1], { player: null, source: "recommended", start: false });
  assert.deepEqual(grid[0].cells[2], { player: null, source: null, start: false });
  // The bench players who play: the recommended bench, or a past day's Yahoo bench.
  assert.deepEqual(benchPlaying(ahead), [9]);
  assert.deepEqual(benchPlaying(past), [9]);
  assert.equal(weekdayLabel("2026-10-22"), "Thu 22");
});

test("the lineup view says the rule, the week, the held slots and the alerts in words", () => {
  const name = (id: number) => `P${id}`;
  assert.equal(ruleText({ changes: "daily", from: "today", deadline: "Daily - Today", source: "settings page" }), "daily lineups, a change counts today (settings page)");
  assert.equal(ruleText({ changes: "weekly", from: null, deadline: null, source: "v3 settings" }), "weekly lineups (v3 settings)");
  assert.equal(ruleText({ changes: null, from: null, deadline: null, source: null }), "the lineup rule is not read: daily lineups assumed");
  assert.equal(
    lineupSummary({ summary: { lost: 2, differ: ["2026-10-23"], unread: ["2026-10-24", "2026-10-25"] }, days: [lineupDay({ date: "2026-10-23" }), lineupDay({ date: "2026-10-24" }), lineupDay({ date: "2026-10-25" })] }),
    "Yahoo's lineup as set loses 2 games (Oct 23) · not read: Oct 24, Oct 25",
  );
  assert.equal(lineupSummary({ summary: { lost: 0, differ: [], unread: [] }, days: [lineupDay({ date: "2026-10-23" })] }), "no game lost on the days read");
  // A later week, none of its days read: said once, not day by day.
  assert.equal(
    lineupSummary({ summary: { lost: 0, differ: [], unread: ["2026-10-26", "2026-10-27"] }, days: [lineupDay({ date: "2026-10-26" }), lineupDay({ date: "2026-10-27" })] }),
    "Yahoo's lineup is not read for these days: the recommended lineups alone",
  );
  // Eligible with a slot open, or with the IL full: the user decides whom to swap.
  assert.equal(heldEligibleText(["IL"], { IL: 1 }), "eligible, 1 open");
  assert.equal(heldEligibleText(["IL"], { IL: 0 }), "eligible, IL full");
  assert.equal(heldEligibleText(["IL", "IL+"], { IL: 0, "IL+": 2 }), "eligible, IL full, IL+ 2 open");
  assert.equal(
    lineupAlertText({ kind: "cleared", player: 1, slot: "IL", status: "Q", from: "2026-10-22", drop: 2 }, name),
    "P1's status cleared (Q) in IL: Yahoo takes no add until he is activated; activating him drops P2.",
  );
  assert.equal(
    lineupAlertText({ kind: "cleared", player: 1, slot: "IL", status: null, from: "2026-10-22", drop: 1 }, name),
    "P1's status cleared (healthy) in IL: Yahoo takes no add until he is activated; activating him, he is the one to drop.",
  );
  assert.equal(
    lineupAlertText({ kind: "held_lower_bound", slots: { IL: 2 } }, name),
    "The held slots are at least 2 IL, the most any roster read fills: the league's settings page is not read yet.",
  );
  assert.equal(lineupAlertText({ kind: "rule_unknown" }, name), "The lineup rule is not read: the lineups assume daily changes.");
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

// ---------------------------------------------------------------- landing table (#191)
test("the private league is pinned first under either sort, even with the least to gain", () => {
  const seasons = [card("big", { public: true }), card("mine", { public: false }), card("small", { public: true }), card("cold", { public: true })];
  const best = new Map<string, BestMove | undefined>([
    ["big", solved("big", 0.5)],
    ["mine", solved("mine", 0.05)],
    ["small", solved("small", 0.1)],
    ["cold", { league: "cold", status: "not_solved", system: "bbm" }],
  ]);
  const ids = (r: ReturnType<typeof landingRows>) => [r.pinned.map((s) => s.league), r.rest.map((s) => s.league)];
  assert.deepEqual(ids(landingRows(seasons, best, "gain", false)), [["mine"], ["big", "small", "cold"]]);
  assert.deepEqual(ids(landingRows(seasons, best, "name", false)), [["mine"], ["big", "cold", "small"]]);
});

test("the points leagues are hidden and counted, and shown sort with the rest", () => {
  const seasons = [
    card("mine", { public: false }),
    card("cats", { public: true }),
    card("pts1", { public: true, scoring: "points" }),
    card("pts2", { public: true, scoring: "points" }),
    card("unread", { public: true, has_snapshot: false }),
  ];
  const best = new Map<string, BestMove | undefined>([
    ["cats", solved("cats", 0.2)],
    ["pts1", solved("pts1", 0.9)],
    ["pts2", solved("pts2", null)],
  ]);
  const hidden = landingRows(seasons, best, "gain", false);
  assert.deepEqual(hidden.rest.map((s) => s.league), ["cats", "unread"]);
  assert.equal(hidden.hidden, 2);
  const shown = landingRows(seasons, best, "gain", true);
  assert.deepEqual(shown.pinned.map((s) => s.league), ["mine"]);
  assert.deepEqual(shown.rest.map((s) => s.league), ["pts1", "cats", "pts2", "unread"]);
  assert.equal(shown.hidden, 0);
  // A private points league is pinned, never hidden.
  const privatePoints = landingRows([card("mine", { public: false, scoring: "points" })], best, "gain", false);
  assert.deepEqual([privatePoints.pinned.length, privatePoints.hidden], [1, 0]);
});

test("the head counts the leagues shown", () => {
  const cats = Array.from({ length: 9 }, () => ({ scoring: "categories" as const }));
  const points = Array.from({ length: 3 }, () => ({ scoring: "points" as const }));
  assert.equal(leaguesLabel(cats), "9 categories leagues");
  assert.equal(leaguesLabel([...cats, ...points]), "12 leagues: 9 categories, 3 points");
  assert.equal(leaguesLabel(points.slice(0, 1)), "1 points league");
});

test("the set reads in a line: together, one move, none, or not solved", () => {
  const b = solved("1", 0.25) as Extract<BestMove, { status: "solved" }>;
  assert.equal(setSummary({ ...b, moves: 3, gain: 0.6 }), "3 moves recommended together add +0.60 over weeks 2-4 against the field");
  assert.equal(setSummary(b), "1 move recommended adds +0.25 over weeks 2-4 against the field");
  assert.equal(setSummary(solved("1", null)), "no move gains 0.01 over weeks 2-4 against the field");
  assert.equal(setSummary({ league: "1", status: "not_solved", system: "bbm" }), "not solved yet");
  assert.equal(setSummary(undefined), "");
});

test("a set's move reads by its basis, with the kind for the panel's last column", () => {
  const b = { ...(solved("1", 0.4) as Extract<BestMove, { status: "solved" }>), names: { "10": "Brooks", "3": "Reed", "5": "Hurt" } };
  const name = bestNamer(b);
  const line = (m: Partial<BestSetLine>) => setLine({ add: 10, drop: null, from: "2026-10-26", gain: 0.4, basis: "open", held: null, ...m }, name);
  const drop = line({ drop: 3, basis: "drop" });
  assert.deepEqual([drop.text, drop.kind, drop.basis.kind], ["Add Brooks for Reed", "drop", "drop"]);
  const held = line({ basis: "held", held: { player: 5, slot: "IL" } });
  assert.deepEqual([held.text, held.kind], ["Add Brooks after Hurt to IL", "IL move"]);
  assert.match(held.basis.title, /Hurt's status fits the open IL slot/);
  const open = line({});
  assert.deepEqual([open.text, open.kind], ["Add Brooks (free: open spot)", "open spot"]);
  // A player the route does not name reads by id.
  assert.equal(name(99), "player 99");
});

test("my place is good in the top two and bad when last", () => {
  const at = (rank: number) => card("1", { my_team: { team_id: 1, name: "T", record: "0-0-0", rank } });
  assert.deepEqual([1, 2, 3, 11, 12].map((r) => placeTone(at(r))), ["good", "good", "", "", "bad"]);
  assert.equal(placeTone(card("1")), "");
});

test("the private league's panel starts open, the others closed, and a toggle wins either way", () => {
  const mine = card("mine", { public: false });
  const other = card("other", { public: true });
  const none = new Map<string, boolean>();
  assert.deepEqual([isExpanded(mine, none), isExpanded(other, none)], [true, false]);
  const once = toggleExpanded(mine, toggleExpanded(other, none));
  assert.deepEqual([isExpanded(mine, once), isExpanded(other, once)], [false, true]);
  const twice = toggleExpanded(mine, once);
  assert.equal(isExpanded(mine, twice), true);
  // The toggles are a new map each time: the old one is untouched.
  assert.equal(none.size, 0);
});

// ---------------------------------------------------------------- strategy (#110)
const point = (key: StrategyPoint["key"], over: Partial<StrategyPoint> = {}): StrategyPoint => ({
  key,
  label: key,
  lambda: 0.5,
  natural: key === "natural",
  stage: "done",
  source: "search",
  gain: { week: 0.2, three: 0.3, season: 2.2, weighted: 1.2 },
  moves: [],
  ...over,
});

test("a strategy run polls while it solves, and opens on the natural weight", () => {
  assert.equal(isSolving({ status: "solving" }), true);
  assert.equal(isSolving({ status: "solved" }), false);
  assert.equal(isSolving(undefined), false);
  assert.equal(defaultWeight([point("week"), point("natural"), point("season")]), "natural");
  assert.equal(defaultWeight([point("week")]), "week");
  assert.equal(defaultWeight([]), null);
  // The knob file's recommended weight (#152) wins over the natural one.
  assert.equal(defaultWeight([point("week"), point("natural"), point("season", { recommended: true })]), "season");
  assert.deepEqual(strategyUnits("categories"), { week: "categories", season: "category-weeks" });
  assert.deepEqual(strategyUnits("points"), { week: "matchups", season: "matchups" });
});

test("the program's status reads solved, time-limited, no set or running, never optimal", () => {
  assert.equal(milpLabel({ status: "optimal" }, 10), "solved");
  assert.equal(milpLabel({ status: "time_limited" }, 10), "time-limited at 10 s");
  assert.equal(milpLabel({ status: "failed" }, 10), "no set");
  assert.equal(milpLabel({ status: "pending" }, 10), "running");
  assert.equal(milpLabel(null, 10), "running");
  for (const status of ["optimal", "time_limited", "failed"] as const) {
    for (const source of ["search", "milp", "both"] as const) {
      const text = sourceText({ stage: "done", source, ahead: 0.1, milp: { status } }, 10);
      assert.match(text, /^Recommended/);
      assert.doesNotMatch(text, /optimal/i);
    }
  }
});

test("a point's source names the solver whose set is shown and by how much it leads", () => {
  assert.match(sourceText({ stage: "searched" }, 10), /exact search; the linear program is still running/);
  assert.equal(sourceText({ stage: "done", source: "both", milp: { status: "optimal" } }, 10), "Recommended by both: the exact search and the linear program (solved) found the same set.");
  assert.equal(sourceText({ stage: "done", source: "milp", ahead: 0.43, milp: { status: "optimal" } }, 10), "Recommended by the linear program (solved), ahead of the search's set by +0.43.");
  assert.equal(
    sourceText({ stage: "done", source: "search", ahead: 1.2, milp: { status: "time_limited" } }, 10),
    "Recommended by the exact search, ahead of the linear program's set (time-limited at 10 s) by +1.20.",
  );
  assert.equal(sourceText({ stage: "done", source: "search", ahead: 0, milp: { status: "optimal" } }, 10), "Recommended by the exact search; the linear program (solved) found nothing better.");
  assert.equal(sourceText({ stage: "done", source: "search", ahead: null, milp: { status: "failed" } }, 10), "Recommended by the exact search; the linear program found no set.");
  assert.match(sourceText({ stage: "done", source: "search", note: "a re-solve of the linear program's set", ahead: 0.02, milp: { status: "optimal" } }, 10), /exact search, from a re-solve of the linear program's set, ahead of the linear program's set \(solved\) by \+0\.02/);
  // The season guard refused the program's set (#164).
  const held = { held_back: true as const, moves: [], gain: {}, ros: { value: -3, partial: false }, forgone: {}, saved: { value: 3, partial: false }, program: true };
  assert.equal(
    sourceText({ stage: "done", source: "search", ahead: -0.4, milp: { status: "optimal" }, season_guard: held }, 10),
    "Recommended by the exact search: the season guard held back the linear program's set (solved), which costs the season.",
  );
});

test("weights whose sets land on the same gains share a frontier mark", () => {
  const marks = frontierMarks([
    point("week", { gain: { week: 0.5, three: 0, season: 0, weighted: 0.5 }, source: "both" }),
    point("even", { gain: { week: 0.5, three: 0, season: 0, weighted: 0.48 } }),
    point("natural", { stage: "priced", source: undefined }),
    point("season", { gain: undefined }),
  ]);
  assert.deepEqual(
    marks.map((m) => [m.keys, m.source, m.natural]),
    [
      [["week", "even"], "both", false],
      [["natural"], "pending", true],
    ],
  );
});

test("the frontier's axes always take in no move and tick at round steps", () => {
  const [lo, hi] = axisRange([0.4, 1.2]);
  assert.ok(lo < 0 && hi > 1.2);
  const [nlo, nhi] = axisRange([-0.3, -0.1]);
  assert.ok(nlo < -0.3 && nhi > 0);
  assert.deepEqual(axisTicks(0, 1), [0, 0.2, 0.4, 0.6, 0.8, 1]);
  assert.deepEqual(axisTicks(-0.1, 3.4), [0, 1, 2, 3]);
  const t = axisTicks(-0.06, 0.62);
  assert.ok(t.length >= 3 && t.length <= 6, String(t));
  assert.ok(t.includes(0));
});

test("the first-order lists rank the pool off the set high and my players not dropped low", () => {
  const fo = { "1": 0.9, "2": 0.4, "3": 1.5, "10": 0.2, "11": -0.1, "12": 0.6 };
  const set = [{ add: 3, drop: 11 }];
  const { adds, mine } = firstOrderLists(fo, [1, 2, 3, 4], [10, 11, 12], set, 2);
  assert.deepEqual(adds, [
    [1, 0.9],
    [2, 0.4],
  ]);
  assert.deepEqual(mine, [
    [10, 0.2],
    [12, 0.6],
  ]);
  assert.deepEqual(firstOrderLists(undefined, [1], [10], []), { adds: [], mine: [] });
});

test("a changed lock or switch asks for a re-solve; the same locks in any order do not", () => {
  const run = { pool: 30, weights: ["week" as const], keep: [5, 3], program_only: false };
  assert.equal(strategySettingsChanged(run, [3, 5], false), false);
  assert.equal(strategySettingsChanged(run, [3], false), true);
  assert.equal(strategySettingsChanged(run, [3, 5], true), true);
  assert.equal(strategySettingsChanged(undefined, [3], true), false);
});

test("the matchup view's lines, odds gains, record and days left (#116)", () => {
  assert.deepEqual([0.6, 0.59, 0.41, 0.4].map(leanTone), ["good", "", "", "bad"]);
  assert.equal(oddsGainLabel(0.0461), "+4.6%");
  assert.equal(oddsGainLabel(-0.003), "−0.3%");
  assert.equal(oddsGainLabel(0), "0.0%");
  assert.equal(oddsGainLabel(null), "");
  assert.equal(matchupRecord({ score: [5, 3], tied: 1 }, "categories"), "5-3-1");
  assert.equal(matchupRecord({ score: [93.24, 101.9], tied: null }, "points"), "93.2–101.9");
  assert.equal(matchupRecord({ score: null, tied: null }, "categories"), "no score yet");
  assert.deepEqual([0, 1, 3].map(daysLeftLabel), ["no day left", "1 day left", "3 days left"]);
});

test("the season view's chips, the week it opens and its summary (#116)", () => {
  assert.deepEqual(
    [0.6, 0.5, 0.4].map((win) => chipTone({ opponent: 7, win })),
    ["good", "warn", "bad"],
  );
  assert.equal(chipTone({ opponent: null, win: 0.7 }), "field");
  assert.equal(chipTone({ opponent: 7, win: null }), "unread");
  const weeks = [
    { week: 3, this_week: true },
    { week: 4, this_week: false },
  ];
  assert.equal(defaultWeek(weeks), 4);
  assert.equal(defaultWeek(weeks.slice(0, 1)), 3);
  assert.equal(defaultWeek([{ week: 5, this_week: false }]), 5);
  assert.equal(defaultWeek([]), null);
  const summary = { weeks: 19, expected_wins: 7.33, expected_cats: 78.2, favoured: 4, toss_up: 1, underdog: 13, field: 1, unread: 0 };
  assert.deepEqual(outlookSummary(summary), ["7.3 wins expected in the 19 regular weeks left", "4 favoured · 1 toss-up · 13 underdogs", "1 against the field"]);
  assert.deepEqual(outlookSummary({ ...summary, weeks: 2, favoured: 0, toss_up: 0, underdog: 1, field: 1, unread: 1 }), [
    "7.3 wins expected in the 2 regular weeks left",
    "1 underdog",
    "1 against the field",
    "1 without odds, counted as none",
  ]);
  assert.deepEqual(outlookSummary({ ...summary, weeks: 1, unread: 1 }), ["1 regular week left, none with odds yet: no roster faced was read"]);
});

test("the scorecard's week, season and moves lines in the scorer's units (#126)", () => {
  const week: ScorecardWeek = {
    week: 2,
    start: "2026-10-26",
    end: "2026-11-01",
    scoring: "categories",
    projected: { entry: "e1", at: "2026-10-26T12:00:00+00:00", source: "moves", expected: 4.32, matchup: 0.7 },
    actual: { opponent: 2, result: { won: 5, lost: 3, tied: 1, outcome: "W" }, won: 1, categories: 5.5 },
    cats: [],
    standing: { rank: 2, record: "9-7-2", teams: 12 },
    moves: [],
  };
  assert.equal(scorecardWeekLine(week), "projected 70% to win, 4.3 categories · W 5-3-1 · 2nd of 12, 9-7-2");
  const points = { ...week, scoring: "points" as const, projected: null, actual: { opponent: 2, result: { points: 812.4, against: 790.15, outcome: "W" as const }, won: 1, categories: null } };
  assert.equal(scorecardWeekLine(points), "not projected · W 812.4-790.1 · 2nd of 12, 9-7-2");
  const moves: MovesSummary = {
    made: 3,
    as_recommended: 1,
    differently: 0,
    not_recommended: 1,
    no_entry: 1,
    near: 0,
    projected: 1,
    projected_value: { week: 7.25 },
    scored: 1,
    realized_only: 1,
    unscored: 1,
    realized_value: { week: 40 },
    complete: { week: 2 },
    compared: { moves: 1, projected: 7.25, realized: 22, same_way: 1, share: 3.0345, horizons: { week: 1 } },
    unscored_by: { unmatched: 1 },
    gaps: 1,
  };
  const td: ScorecardToDate = { weeks: 2, projected: 1, record: "1-0-1", expected_wins: 0.7, wins: 1, expected_categories: 4.32, categories: 5.5, standing: null, moves };
  assert.equal(scorecardToDateLine(td, 0.09), "1-0-1 · 1 win against 0.70 expected over 1 projected week · 5.5 categories against 4.3 · Brier 0.090");
  assert.equal(scorecardToDateLine({ ...td, projected: 0, expected_wins: null }), "1-0-1");
  assert.equal(
    movesSummaryLine(moves, "categories"),
    "3 moves: 1 scored, 1 realized only, 1 unscored · +40.00 realized on their weeks · scored +22.00 against +7.25 projected (303%) on their horizons, 1 of 1 the projected way",
  );
  assert.equal(movesSummaryLine({ ...moves, made: 0 }, "points"), "no moves");
  assert.equal(unitsLabel(-3.24, "points"), "−3.2");
  assert.equal(unitsLabel(-3.256, "categories"), "−3.26");
});

test("a scorecard move's line, its realized cells and its tooltip (#126)", () => {
  const name = (id: number) => ({ 11: "Brooks", 12: "Grant" })[id] ?? `player ${id}`;
  const span = { from: "2026-10-27", to: "2026-11-01", complete: true, missing: [], add_games: 2, drop_games: 1, add: 30, drop: 8, gaps: 0, value: 22 };
  const move: ScorecardMove = {
    group: "scored",
    day: "2026-10-27",
    at: "2026-10-27T09:00:00-04:00",
    add: 11,
    drop: 12,
    detail: "Free Agent",
    bid: null,
    match: { kind: "as_recommended", entry: "e2", move: { add: 11, drop: 12 }, near: false },
    projected: null,
    realized: {
      valued: true,
      reason: null,
      add: { yahoo: 11, espn: "e11", by: "team" },
      drop: { yahoo: 12, espn: "e12", by: "team" },
      horizons: {
        week: { ...span, through: "2026-11-01" },
        three: { ...span, from: "2026-11-02", to: "2026-11-22", through: null, complete: false, add_games: 0, drop_games: 0, add: 0, drop: 0, value: null },
      },
      scorer: { entry: "e2", own: false },
      lag_days: 1,
    },
  };
  assert.equal(moveWhat(move, name), "Add Brooks for Grant");
  assert.equal(moveWhat({ add: null, drop: 12 }, name), "Drop Grant");
  assert.equal(moveWhat({ add: 11, drop: null }, name), "Add Brooks");
  assert.equal(realizedLabel(move, "week", "categories"), "+22.00");
  assert.equal(realizedLabel(move, "three", "categories"), "−");
  assert.equal(
    realizedTitle(move, "categories"),
    "its week (Oct 27 – Nov 1), 2 games added, 1 given up: +22.00; the three weeks after (Nov 2 – Nov 22, none read yet), 0 games added, 0 given up; " +
      "valued with the nearest solve's scorer: realized only; made 1 day after the first day of the solve it matched",
  );
  const unscored = { ...move, realized: { ...move.realized!, valued: false, reason: "unmatched" as const } };
  assert.equal(realizedLabel(unscored, "week", "categories"), "−");
  assert.ok(realizedTitle(unscored, "categories").startsWith("no realized value: a player not matched to the box scores; "));
  assert.equal(MATCH_WORDS.no_entry, "no solve before it");
});

test("a move's rest of the season reads in the scorer's units, its games and days on hover (#151)", () => {
  const name = (id: number) => ({ 11: "Brooks", 12: "Grant" })[id] ?? `player ${id}`;
  const r: MoveRos = { value: 12.345, add_games: 58, drop_games: 55, extrapolated: { add: 4, drop: 2.5 }, from: "2026-10-24", to: "2027-04-12" };
  assert.equal(rosLabel(r, "categories"), "+12.3");
  assert.equal(rosLabel({ value: 310.46 }, "points"), "+310");
  assert.equal(rosLabel(null, "categories"), "");
  assert.equal(rosLabel({ ...r, value: null }, "categories"), "");
  // Only a season-costly figure is coloured, and only when it reads below zero.
  assert.equal(rosTone(r, "categories"), "");
  assert.equal(rosTone({ value: -0.2 }, "categories"), "bad");
  assert.equal(rosTone({ value: -0.04 }, "categories"), "");
  assert.equal(rosTone(undefined, "categories"), "");
  assert.equal(
    rosGames(r, { add: 11, drop: 12 }, name),
    "Brooks's 58 games less Grant's 55, Oct 24 to Apr 12, 6.5 of them past the schedule read at the team's rate",
  );
  assert.equal(rosGames({ ...r, add_games: 1, drop_games: null, extrapolated: { add: 0, drop: null } }, { add: 11, drop: null }, name), "Brooks's 1 game, Oct 24 to Apr 12");
  assert.equal(
    rosTitle(r, { add: 11, drop: 12 }, name, "points"),
    "to the season's end, playoffs included: Brooks's 58 games less Grant's 55, Oct 24 to Apr 12, 6.5 of them past the schedule read at the team's rate; " +
      "each at his per-game value, in fantasy points. The decision log's figure; nothing ranks on it",
  );
  assert.equal(rosTitle({ ...r, value: null }, { add: 11, drop: null }, name, "categories"), "not valued to the season's end: Brooks has no line");
  assert.equal(rosTitle({ ...r, value: null }, { add: 11, drop: 12 }, name, "categories"), "not valued to the season's end: the add or the drop has no line");
  assert.ok(rosTitle(undefined, { add: 11, drop: 12 }, name, "categories").startsWith("not valued to the season's end: no scorer"));
  assert.ok(rosHeadTitle("categories").startsWith("ROS: the move to the season's end, playoffs included, in the scorer's z-sum, net of an empty line"));
  assert.ok(rosHeadTitle("points", "the step").startsWith("ROS: the step to the season's end, playoffs included, in fantasy points"));
  assert.equal(valueUnits("points"), "fantasy points");
  assert.equal(valueUnits(null), "the scorer's z-sum, net of an empty line");
});

test("a plan step's figure names the later step that drops him; the plan's total sits beside the set's (#151)", () => {
  const name = (id: number) => `P${id}`;
  const ros: MoveRos = { value: 2.5, add_games: 40, drop_games: 38, extrapolated: { add: 0, drop: 0 }, from: "2026-10-22", to: "2027-04-12" };
  const step = { add: 10, drop: 3, ros, dropped_by: { add: 11, from: "2026-10-24" } };
  assert.equal(
    planStepRosTitle(step, name, "categories"),
    `${rosTitle(ros, step, name, "categories")}. Valued as kept there: Sat Oct 24's step drops P10 for P11, so the plan's total counts the two together`,
  );
  assert.equal(planStepRosTitle({ ...step, dropped_by: null }, name, "categories"), rosTitle(ros, step, name, "categories"));
  assert.equal(planRosText(streamPlan(), "categories"), null);
  assert.equal(planRosText(streamPlan({ ros: { set: { value: 12.1 }, plan: { value: 14.2 } } }), "categories"), "ROS +14.2 against the set's +12.1");
  assert.equal(planRosText(streamPlan({ ros: { set: null, plan: { value: 14.2 } } }), "categories"), null);
});

test("a trade's rest of the season: a side's change and a player's games on hover (#151)", () => {
  assert.equal(
    playerRosTitle({ value: 12.18, per_game: 0.21, games: 58, extrapolated: 4 }, "2026-10-24", "categories"),
    "58 games from Oct 24 to the season's end, 4 past the schedule read, at +0.21 a game, in the scorer's z-sum, net of an empty line",
  );
  assert.equal(playerRosTitle({ value: 300, per_game: 30, games: 10, extrapolated: 0 }, "2026-10-24", "points"), "10 games from Oct 24 to the season's end, at +30.0 a game, in fantasy points");
  assert.ok(playerRosTitle(null, "2026-10-24", "categories").startsWith("not valued"));
  const side: NonNullable<TradeSide["ros"]> = { before: 100, after: 104.5, change: 4.5, from: "2026-10-24", unvalued: 1 };
  assert.equal(
    sideRosTitle(side, "categories"),
    "the roster to the season's end from Oct 24, 100.0 → 104.5 in the scorer's z-sum, net of an empty line: what it receives less what it sends and drops; " +
      "1 player without a line counts nothing",
  );
  assert.ok(sideRosTitle({ ...side, unvalued: 0 }, "points").endsWith("what it receives less what it sends and drops"));
  assert.ok(sideRosTitle(null, "categories").startsWith("not valued"));
});

test("the lineup executor's panel says what it does, why live waits, and each run and step (#170)", () => {
  const mode = (m: AutopilotView["mode"]["mode"], priv = false): AutopilotView["mode"] => ({ mode: m, at: null, by: null, set: false, private: priv });
  assert.equal(executorText({ mode: mode("dry_run"), stop: false }), "Dry run: on the team page, the extension logs what it would set and clicks nothing.");
  assert.equal(executorText({ mode: mode("off"), stop: false }), "Off: the extension leaves this league's lineup alone.");
  assert.ok(executorText({ mode: mode("live"), stop: false }).startsWith("Live: on the team page"));
  assert.equal(executorText({ mode: mode("dry_run"), stop: true }), "STOP is on (data/autopilot/STOP): no executor runs.");
  assert.ok(executorText({ mode: mode("off", true), stop: false }).startsWith("The private league is never touched"));
  const needs = { dry_run_days: 7, checked_days: 2 };
  assert.equal(liveText({ ok: false, reason: "a dry run on 7 days first: 3 so far", dry_run_days: 3, checked_days: 1, needs }), "Live waits: a dry run on 7 days first: 3 so far.");
  assert.equal(liveText({ ok: true, reason: null, dry_run_days: 8, checked_days: 2, needs }), "The dry run has passed: 8 days, 2 with steps that passed every check.");
  const step = { player: 1, from_slot: "BN", to_slot: "SF", with: 2, tip: null, group: 0, outcome: "would_set" as const, reason: null };
  const run: LineupRunLog = { at: "2026-10-24T10:02:00+00:00", day: "2026-10-24", mode: "dry_run", trigger: "routine", outcome: "would_set", reason: null, steps: [step, { ...step, player: 3, with: null }], skipped: [] };
  const clock = () => "05:02";
  assert.equal(runLine(run, clock), `05:02 · ${weekdayLabel("2026-10-24")} · routine: would set 2 moves`);
  assert.equal(
    runLine({ ...run, trigger: "panel", outcome: "nothing_to_do", reason: "Yahoo's lineup already starts the recommended players", steps: [], skipped: [{ reason: "tip-off passed", players: [4] }] }, clock),
    `05:02 · ${weekdayLabel("2026-10-24")} · side panel: nothing to do (Yahoo's lineup already starts the recommended players); 1 left out, a game began`,
  );
  const name = (id: number) => `P${id}`;
  assert.equal(stepText(step, name), "P1 BN → SF, P2 to BN: would set");
  assert.equal(stepText({ ...step, with: null, outcome: "skipped", reason: "the page did not match" }, name), "P1 BN → SF: skipped (the page did not match)");
});

test("the Queue card says what the moves executor does, each entry's state and bid, and the passes (#171)", () => {
  const mode = (m: MovesView["mode"]["mode"], priv = false): MovesView["mode"] => ({ mode: m, at: null, by: null, set: false, private: priv, cap: null });
  assert.ok(movesExecutorText({ mode: mode("dry_run"), stop: false }).startsWith("Dry run: each morning's queue is built"));
  assert.equal(movesExecutorText({ mode: mode("off"), stop: false }), "Off: nothing of this league is queued; its moves stay suggestions.");
  assert.equal(movesExecutorText({ mode: mode("live"), stop: true }), "STOP is on (data/autopilot/STOP): no executor runs.");
  assert.ok(movesExecutorText({ mode: mode("dry_run", true), stop: false }).startsWith("The private league is never touched"));
  const needs = { dry_run_days: 7, checked_days: 2 };
  assert.equal(movesLiveText({ ok: true, reason: null, dry_run_days: 7, checked_days: 3, needs }), "The dry run has passed: 7 days, 3 that read the add page.");
  const now = Date.parse("2026-10-24T15:00:00Z");
  assert.equal(countdownLabel("2026-10-24T15:42:10Z", now), "in 43 min");
  assert.equal(countdownLabel("2026-10-24T17:05:00Z", now), "in 2 h 5 min");
  assert.equal(countdownLabel("2026-10-24T17:00:00Z", now), "in 2 h");
  assert.equal(countdownLabel("2026-10-24T14:00:00Z", now), "due");
  assert.equal(countdownLabel(null, now), "");
  const floor = { plan: 0.1, scored: null, moves: 3, needs: 20, applies: "plan" as const };
  const e: QueueEntry = {
    id: "2026-10-24:900001:101:201",
    date: "2026-10-24",
    league: "900001",
    scoring: "categories",
    set: "three",
    decision: null,
    add: 101,
    drop: 201,
    from: "2026-10-25",
    availability: "W",
    judged: "three",
    gain: 0.21,
    value: 410,
    season: 900,
    season_costly: false,
    flag: "add",
    floor: { ...floor, below: null },
    bid: { amount: 4, reason: "$4: gain 2x the typical (the plan floor until 10 moves), x2 for a breakout flag", base: 2, factor: 2, sizing: 1, typical: 0.1, typical_from: "the plan floor until 10 moves" },
    queued: true,
    reason: null,
    rank: 1,
    queued_at: "2026-10-24T10:00:00Z",
    executes_at: "2026-10-24T16:00:00Z",
    struck: false,
    bid_struck: false,
    outcome: null,
    outcome_reason: null,
    outcome_at: null,
    resolved: null,
  };
  const name = (id: number) => `P${id}`;
  assert.equal(queueMoveText(e, name), "P101 for P201");
  // By the move's basis (#187): an open spot, a held move, a drop; an entry logged before the
  // basis with no drop says no more than that.
  assert.equal(queueMoveText({ ...e, drop: null, basis: "open", held_move: null }, name), "P101 (free: open spot)");
  assert.equal(queueMoveText({ ...e, drop: null, basis: "held", held_move: { player: 5, slot: "IL" } }, name), "P101 after P5 to IL");
  assert.equal(queueMoveText({ ...e, basis: "drop", held_move: null }, name), "P101 for P201");
  assert.equal(queueMoveText({ ...e, drop: null }, name), "P101 with no drop");
  assert.equal(queueStateText(e, now), "executes in 1 h");
  assert.equal(queueStateText({ ...e, struck: true }, now), "struck");
  assert.equal(queueStateText(e, now + 3_600_000), "due at the next pass");
  assert.equal(queueStateText({ ...e, outcome: "claimed", resolved: "won" }, now), "claimed, won");
  assert.equal(queueStateText({ ...e, outcome: "gone", outcome_reason: null }, now), "gone: another team had him first");
  assert.equal(queueStateText({ ...e, queued: false, reason: "below the noise floor", floor: { ...floor, below: "scored" } }, now), "below the scored floor");
  assert.equal(queueStateText({ ...e, queued: false, reason: "over the day's cap" }, now), "over the day's cap");
  assert.equal(bidLabel(e), "$4 claim");
  assert.equal(bidLabel({ ...e, bid_struck: true }), "$0 claim (the $4 bid struck)");
  assert.equal(bidLabel({ ...e, availability: "FA" }), "free agent, $0");
  assert.equal(
    queueFloorLine({ scoring: "categories", floor, typical: { value: 0.1, from: "the plan floor until 10 moves" } }),
    "Floor: a gain of 0.1 expected categories over the three weeks; the scorecard's spread joins it once 20 moves are scored (3 so far). Bids scale by a typical gain of 0.1 (the plan floor until 10 moves).",
  );
  assert.ok(queueFloorLine({ scoring: "points", floor: { ...floor, scored: 41.25, moves: 22, applies: "plan and scored" }, typical: { value: 0.02, from: "the fortnight's median" } }).includes("0.1 points over the three weeks and the scorecard's spread of 41.3 in value units over 22 moves"));
  const pass: MovesPassLog = {
    at: "2026-10-24T16:01:00Z",
    day: "2026-10-24",
    mode: "dry_run",
    trigger: "routine",
    outcome: "would_claim",
    reason: null,
    entries: [
      { id: e.id, add: 101, drop: 201, bid: 4, outcome: "would_claim", reason: null },
      { id: "x", add: 102, drop: null, bid: 1, outcome: "gone", reason: null },
    ],
  };
  assert.equal(passLine(pass, () => "9:01 AM"), `9:01 AM · ${weekdayLabel("2026-10-24")} · routine: would claim 1 (1 gone)`);
  assert.equal(passLine({ ...pass, outcome: "nothing_due", entries: [] }, () => "9:01 AM"), `9:01 AM · ${weekdayLabel("2026-10-24")} · routine: nothing due`);
  const settings = { execute_time: "09:00", at: null, by: null, set: false };
  const q: QueuePayload = { date: "2026-10-24", built: [], execute_time: null, leagues: [], entries: [], settings, stop: false, now: "2026-10-24T15:00:00Z" };
  assert.equal(queueFoldLine(q), "no queue built today: the morning routine builds it · executes from 09:00 CT");
  const leagues = [
    { league: "900001", scoring: "categories" as const, mode: "dry_run" as const, status: "queued" as const, reason: null },
    { league: "900002", scoring: "points" as const, mode: "dry_run" as const, status: "not_solved" as const, reason: "not solved today" },
  ];
  const built = { ...q, built: ["2026-10-24T10:00:00Z"], leagues, entries: [e, { ...e, id: "y", struck: true }, { ...e, id: "z", queued: false }] };
  assert.equal(queueFoldLine(built), "1 queued in 1 league · 1 struck · 1 not solved today · executes from 09:00 CT");
  assert.equal(queueFoldLine({ ...built, stop: true }), "STOP is on (data/autopilot/STOP): nothing executes");
});

// The Queue screen's entries (#194, #200): one of league 900002, queued, executing at noon UTC.
const QUEUE_FLOOR = { plan: 0.1, scored: null, moves: 3, needs: 20, applies: "plan" as const, below: null };
const QUEUE_BID = { amount: 2, reason: "$2", base: 2, factor: 1, sizing: 1, typical: 0.1, typical_from: "the plan floor" };
const QUEUE_BASE: QueueEntry = {
  id: "a",
  date: "2026-10-24",
  league: "900002",
  scoring: "categories",
  set: "three",
  decision: null,
  add: 101,
  drop: 201,
  from: "2026-10-25",
  availability: "W",
  judged: "three",
  gain: 0.3,
  value: null,
  season: null,
  season_costly: false,
  flag: null,
  floor: QUEUE_FLOOR,
  bid: QUEUE_BID,
  queued: true,
  reason: null,
  rank: 1,
  queued_at: "2026-10-24T10:00:00Z",
  executes_at: "2026-10-24T12:00:00Z",
  struck: false,
  bid_struck: false,
  outcome: null,
  outcome_reason: null,
  outcome_at: null,
  resolved: null,
};
const queueEntry = (id: string, over: Partial<QueueEntry> = {}): QueueEntry => ({ ...QUEUE_BASE, id, ...over });

test("the Queue screen orders the day's entries across the leagues, says why a league queued none and names from the payload (#194)", () => {
  const floor = QUEUE_FLOOR;
  const at = queueEntry;
  const entries = [
    at("late", { executes_at: "2026-10-24T15:00:00Z" }),
    at("untimed", { executes_at: null }),
    at("b2", { league: "900001", rank: 2 }),
    at("struck", { league: "900001", rank: 1, struck: true }),
    at("done", { league: "900003", outcome: "would_claim" }),
    at("rank2", { rank: 2 }),
    at("left-a", { league: "900002", queued: false, reason: "over the day's cap", gain: 0.2 }),
    at("left-b", { league: "900001", queued: false, reason: "season-costly", gain: 0.1 }),
    at("left-c", { league: "900002", queued: false, reason: "no adds left this week", gain: 0.5 }),
  ];
  // By the time it executes, then the league's rank, then the league; struck and executed keep
  // their place, and an entry with no time goes last.
  assert.deepEqual(
    queueOrder(entries).map((e) => e.id),
    ["struck", "done", "b2", "rank2", "late", "untimed"],
  );
  // The moves left out: by league, then the gain.
  assert.deepEqual(
    notQueued(entries).map((e) => e.id),
    ["left-b", "left-c", "left-a"],
  );
  const row = (status: QueueLeague["status"], over: Partial<QueueLeague> = {}): QueueLeague => ({ league: "900004", scoring: "categories", mode: "dry_run", status, reason: null, ...over });
  // A league that did not build says its row's reason, or the status in words without one.
  assert.equal(stripReason(row("not_solved", { reason: "not solved today: the build reads the decision log and never solves" }), entries), "not solved today: the build reads the decision log and never solves");
  assert.equal(stripReason(row("off", { reason: "the moves executor is off in this league" }), entries), "the moves executor is off in this league");
  assert.equal(stripReason(row("private", { reason: "the private league is never touched" }), entries), "the private league is never touched");
  assert.equal(stripReason(row("failed"), entries), "not read");
  // A league that built: none when it queued; else the reason most of its entries share.
  assert.equal(stripReason(row("queued", { league: "900002" }), entries), "");
  const none = [
    at("x1", { league: "900004", queued: false, reason: "below the noise floor", floor: { ...floor, below: "plan" } }),
    at("x2", { league: "900004", queued: false, reason: "below the noise floor", floor: { ...floor, below: "plan" } }),
    at("x3", { league: "900004", queued: false, reason: "the drop is protected" }),
  ];
  assert.equal(stripReason(row("queued"), none), "below the plan floor");
  assert.equal(stripReason(row("queued"), []), "nothing queued");
  // The adds left in the week holding the day; null for an unread week or no limit.
  const weeks = { adds_left: [{ start: "2026-10-20", end: "2026-10-26", adds: 3 }, { start: "2026-10-27", end: "2026-11-02", adds: null }] };
  assert.equal(addsThisWeek(weeks, "2026-10-24"), 3);
  assert.equal(addsThisWeek(weeks, "2026-10-28"), null);
  assert.equal(addsThisWeek({}, "2026-10-24"), null);
  // The strip: the private league first, then by name.
  const names: Record<string, string> = { "900001": "Bravo", "900002": "Alpha", "900003": "Charlie" };
  const strip = stripOrder([row("queued", { league: "900001" }), row("queued", { league: "900002" }), row("private", { league: "900003" })], (l) => names[l]);
  assert.deepEqual(strip.map((r) => r.league), ["900003", "900002", "900001"]);
  // Names from the payload, "player N" without one.
  const name = queueNamer({ names: { "101": "P101" } });
  assert.equal(name(101), "P101");
  assert.equal(name(7), "player 7");
  assert.equal(queueNamer({})(7), "player 7");
  // The Queue card's flag words, and a time on the Central clock (CDT on the day).
  assert.deepEqual(([null, "watch", "add", "must-add"] as const).map(queueFlagWord), ["", "", "breakout", "strong breakout"]);
  assert.equal(centralClock("2026-10-24T12:00:00Z"), "7:00 AM CT");
  assert.equal(centralClock("2026-12-01T13:00:00Z"), "7:00 AM CT");
  assert.equal(centralClock(null), "");
});

test("the Queue screen's one switch covers every public league, the points ones too, and says what live does to each (#205)", () => {
  const ok = { ok: true, reason: null, dry_run_days: 2, checked_days: 2, needs: { dry_run_days: 1, checked_days: 1 } };
  const wait = { ...ok, ok: false, reason: "a dry run on 1 day first: 0 so far" };
  const row = (league: string, over: Partial<QueueLeague> = {}): QueueLeague => ({ league, scoring: "categories", mode: "dry_run", status: "queued", reason: null, user_cap: null, live: ok, ...over });
  const priv = row("900000", { status: "private", mode: "off", live: undefined });
  const rows = [priv, row("900001"), row("900002", { scoring: "points" }), row("900003", { status: "off", mode: "dry_run", scoring: "points" })];
  // The private league is never one of them; the points leagues the landing hides are, and said.
  assert.deepEqual(switchRows(rows).map((r) => r.league), ["900001", "900002", "900003"]);
  assert.equal(switchScope(rows), "all 3 public leagues, the 2 points leagues the landing hides among them");
  assert.equal(switchScope([priv, row("900001")]), "the 1 public league");
  // The modes in force: live first, then dry run, then off; one mode, or none when they differ.
  assert.equal(modesWord(rows), "3 dry run");
  assert.equal(commonMode(rows), "dry_run");
  const mixed = [priv, row("900001", { mode: "live" }), row("900002", { mode: "off" }), row("900003"), row("900004", { mode: "live" })];
  assert.equal(modesWord(mixed), "2 live · 1 dry run · 1 off");
  assert.equal(commonMode(mixed), null);
  assert.equal(commonMode([priv]), null);
  // Live: every league whose guard holds, the points ones among them; those it keeps, and those
  // already live, are said.
  assert.equal(allLiveLine(rows), "Switch all 3 to live, the 2 points leagues among them: each claims its due moves on Yahoo's add page with its bid.");
  assert.equal(allLiveLine([priv, row("900001"), row("900002")]), "Switch all 2 to live: each claims its due moves on Yahoo's add page with its bid.");
  const some = [priv, row("900001"), row("900002", { live: wait, scoring: "points" }), row("900003", { mode: "live" })];
  assert.deepEqual(liveSplit(some).ready.map((r) => r.league), ["900001"]);
  assert.deepEqual(liveSplit(some).waiting.map((r) => r.league), ["900002"]);
  assert.equal(allLiveLine(some), "Switch 1 of the 3 to live: each claims its due moves on Yahoo's add page with its bid; 1 keeps its mode: live waits; 1 already live.");
  const names: Record<string, string> = { "900001": "Alpha", "900002": "Bravo", "900003": "Charlie" };
  const title = (l: string) => names[l] ?? `league ${l}`;
  assert.equal(allLiveTitle(some, title), "Live waits in Bravo (a dry run on 1 day first: 0 so far).");
  assert.equal(allLiveTitle(rows, title), "The dry run has passed in every league not live.");
  assert.equal(allLiveTitle([priv, row("900001", { mode: "live" })], title), "Every public league is live.");
  // The answer: the leagues kept in their mode, each with why.
  const answer = {
    mode: "live" as const,
    leagues: [
      { league: "900001", mode: "live" as const, ok: true, reason: null },
      { league: "900002", mode: "dry_run" as const, ok: false, reason: "a dry run on 1 day first: 0 so far" },
      { league: "900003", mode: "dry_run" as const, ok: false, reason: "STOP is on (data/autopilot/STOP)" },
    ],
  };
  assert.deepEqual(keptLines(answer, title), ["Bravo stays dry run: a dry run on 1 day first: 0 so far", "Charlie stays dry run: STOP is on (data/autopilot/STOP)"]);
});

test("an entry reads its latest pass after its outcome, why it is not queued and a strike; the day's tally joins the line (#200)", () => {
  const now = Date.parse("2026-10-24T11:00:00Z");
  const at = "2026-10-24T14:32:00Z"; // 9:32 AM CDT
  const pass = (over: Partial<QueuePass> = {}): QueuePass => ({ at, trigger: "routine", outcome: "would_claim", reason: null, extension: "0.7.0", ...over });
  const e = queueEntry("a", { pass: pass() });
  assert.equal(queueStateText(e, now), "would claim · 9:32 AM CT");
  assert.equal(queueStateText(queueEntry("a", { pass: pass({ outcome: "skipped", reason: "page not read" }) }), now), "skipped 9:32 AM CT: page not read");
  assert.equal(queueStateText(queueEntry("a", { pass: pass({ outcome: "gone", reason: "the page shows the add on a team" }) }), now), "gone 9:32 AM CT: the page shows the add on a team");
  assert.equal(queueStateText(queueEntry("a", { pass: pass({ outcome: "failed", reason: "no answer" }) }), now), "failed 9:32 AM CT: no answer");
  assert.equal(queueStateText(queueEntry("a", { pass: pass({ reason: "open spot" }) }), now), "would claim · 9:32 AM CT: open spot");
  // A live outcome, a move not queued and a strike each come first; with no pass, the countdown.
  assert.equal(queueStateText({ ...e, outcome: "claimed", resolved: "won" }, now), "claimed, won");
  assert.equal(queueStateText({ ...e, queued: false, reason: "over the day's cap" }, now), "over the day's cap");
  assert.equal(queueStateText({ ...e, struck: true }, now), "struck");
  assert.equal(queueStateText(queueEntry("a"), now), "executes in 1 h");
  assert.equal(queueStateText(queueEntry("a", { pass: null }), now + 3_600_000), "due at the next pass");
  // The tone: a claim good, a failure bad; a struck entry's pass is not its state.
  assert.equal(queueStateTone(e), "good");
  assert.equal(queueStateTone(queueEntry("a", { pass: pass({ outcome: "skipped" }) })), "");
  assert.equal(queueStateTone(queueEntry("a", { pass: pass({ outcome: "failed" }) })), "bad");
  assert.equal(queueStateTone({ ...e, struck: true }), "");
  assert.equal(queueStateTone(queueEntry("a", { outcome: "claimed" })), "good");
  assert.equal(passTitle(e), "routine pass at 9:32 AM CT, extension 0.7.0");
  assert.equal(passTitle(queueEntry("a", { pass: pass({ trigger: "routine_late", extension: null }) })), "late routine pass at 9:32 AM CT");
  assert.equal(passTitle(queueEntry("a")), "");
  // The tally: the counts at zero left out, in order, then the last pass.
  const tally: PassTally = { last: "2026-10-24T14:35:00Z", would_claim: 13, claimed: 0, skipped: 7, gone: 0, failed: 1, pages: 22 };
  assert.equal(passTally(tally), "13 would claim · 7 skipped · 1 failed · last pass 9:35 AM CT");
  assert.equal(passTally(null), "");
  const settings = { execute_time: "09:00", at: null, by: null, set: false };
  const q: QueuePayload = { date: "2026-10-24", built: ["2026-10-24T10:00:00Z"], execute_time: null, leagues: [], entries: [e], settings, stop: false, now: "2026-10-24T15:00:00Z" };
  assert.equal(queueFoldLine({ ...q, passes: tally }), "1 queued in 1 league · 13 would claim · 7 skipped · 1 failed · last pass 9:35 AM CT · executes from 09:00 CT");
  assert.equal(queueFoldLine({ ...q, passes: null }), "1 queued in 1 league · executes from 09:00 CT");
});
