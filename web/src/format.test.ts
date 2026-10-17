// Node's own test runner with its built-in type stripping (`npm test`); outside tsc's project,
// since the web app has no Node types.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { AdjustmentRow, AvailabilityBias, BoardPlayer, CurveFit, LeagueResolved, LeagueSummary, RoomSummary, SessionSummary } from "./api";
import { adpCell, adpTitle, armLabel, biasDetail, blendDetail, blendLabel, clockNote, clockText, curveFitNote, draftWhen, haircutLabel, leagueSurvivalText, haircutTitle, haircutWeeks, nextDraft, oddsSource, rankLabel, roomOrder, survivalDetail, turnFlag, weeksToGames } from "./format.ts";

const row = (adp_from: BoardPlayer["adp_from"], adp: number | null, keepers_ahead = 0): BoardPlayer =>
  ({ adp, adp_eff: adp == null ? null : adp - keepers_ahead, adp_from, keepers_ahead }) as BoardPlayer;

test("the board marks an ADP mapped from a rank and hides one past the end of the draft", () => {
  assert.equal(adpCell(row("market", 12.34)), "12.3");
  assert.equal(adpCell(row("rank", 118.6)), "≈118.6");
  assert.equal(adpCell(row("rank", 118.6, 2)), "≈119 → 117");
  assert.equal(adpCell(row("end", 157)), "—");
  assert.equal(adpCell(row("stand-in", 40)), "40.0");
  assert.equal(adpCell(row("market", null)), "");
});

test("the ADP cell's hover says where a mapped number comes from", () => {
  const source = "o_rank:yahoo_players_x.json";
  assert.equal(rankLabel(source), "Yahoo's rank (o_rank, yahoo_players_x.json)");
  assert.equal(rankLabel("rank:ranks.csv"), "ranks in ranks.csv");
  assert.equal(adpTitle(row("market", 12), source), undefined);
  assert.match(adpTitle(row("rank", 118.6), source) ?? "", /^not on the ADP list: Yahoo's rank \(o_rank, yahoo_players_x\.json\) mapped onto its scale, ADP 118\.6$/);
  assert.match(adpTitle(row("end", 157), source) ?? "", /past the end of the draft/);
  assert.match(adpTitle(row("rank", 118.6, 1), source) ?? "", /; a keeper ranked ahead of him is out of the market, so it reaches him at 117\.6$/);
  assert.match(adpTitle(row("market", 30, 2), source) ?? "", /^Yahoo ADP 30\.0; 2 keepers ranked ahead/);
});

test("the leagues list says when a draft is and whether the user armed it", () => {
  const now = Date.parse("2026-10-17T10:00:00-07:00");
  assert.match(draftWhen("2026-10-17T11:00:00-07:00", now), /\(in 60 min\)$/);
  assert.match(draftWhen("2026-10-18T14:00:00-07:00", now), /\(in 28 h\)$/);
  assert.match(draftWhen("2026-10-17T09:30:00-07:00", now), /\(30 min ago\)$/);
  assert.equal(draftWhen(null, now), "draft time unknown");
  assert.equal(draftWhen("soon", now), "soon");
  assert.equal(armLabel(null), "not armed");
  assert.match(armLabel({ at: "2026-10-17T16:00:00+00:00" }), /^armed \S/);
  assert.equal(armLabel({ at: "?" }), "armed");
});

test("the survival odds say when the ADP formula is shifted by the league's bias", () => {
  const bias: AvailabilityBias = { source: "bias:yahoo_history/adp_bias.json", from_adp: 72, half_life: 1, seasons: [2017, 2026], target: 2026 };
  assert.equal(oddsSource("adp"), "the ADP formula");
  assert.equal(oddsSource("adp", bias), "the ADP formula + league bias");
  assert.equal(oddsSource("league"), "the league's drafts");
  assert.equal(oddsSource("league", bias), "the league's drafts and the ADP formula + league bias");
  assert.equal(oddsSource("survival", bias), "simulated drafts");
  // A blended league table names the drafts behind it (#77).
  const blend = { drafts: 1.5, same_format: 1, other_format: 1, weight: 0.5 };
  assert.equal(oddsSource("league", null, blend), "the league's drafts (blend: 1.5 drafts)");
  assert.equal(oddsSource("league", bias, blend), "the league's drafts (blend: 1.5 drafts) and the ADP formula + league bias");
  assert.equal(oddsSource("adp", null, blend), "the ADP formula");
  assert.equal(blendLabel(1), "blend: 1 draft");
  assert.equal(blendLabel(2.5), "blend: 2.5 drafts");
  assert.equal(blendDetail(blend), "blend: 1.5 drafts: 1 of the format + 1 of the other format at ×0.5, 40% ADP formula");
  assert.equal(blendDetail({ ...blend, drafts: 3, same_format: 3, other_format: 0 }), "blend: 3 drafts: 3 of the format, 25% ADP formula");
  assert.equal(
    biasDetail(bias),
    "the ADP formula centred on ADP plus the league's bias from ADP 72, fit on 2017-2026 (half-life 1 season) from yahoo_history/adp_bias.json",
  );
  assert.equal(biasDetail({ ...bias, source: null, seasons: [], half_life: null }), "the ADP formula centred on ADP plus the league's bias from ADP 72");
  const s = {
    availability_source: "adp",
    adp_source: "file:adp.csv",
    adp_keepers_ahead: 0,
    spread_base: 1.5,
    spread_growth: 0.15,
    survival: { mode: "none", status: "none" },
    availability_bias: null,
  } as unknown as SessionSummary;
  assert.equal(survivalDetail(s), "ADP formula (file:adp.csv); spread 1.5 + 0.15 × ADP picks.");
  assert.match(survivalDetail({ ...s, availability_bias: bias }), /^ADP formula \(file:adp\.csv\); the ADP formula centred on ADP plus the league's bias from ADP 72, .*; spread 1\.5/);
  const shared = {
    ...s,
    availability_source: "league",
    survival: {
      mode: "league",
      status: "ready",
      source: "league:leagues/_shared/points/survival_by_adp.csv",
      from_adp: 90,
      max_adp: 133,
      blend: { drafts: 1.5, same_format: 1, other_format: 1, weight: 0.5 },
    },
  } as unknown as SessionSummary;
  assert.equal(
    survivalDetail(shared),
    "this league's drafts by ADP (league:leagues/_shared/points/survival_by_adp.csv, blend: 1.5 drafts: 1 of the format + 1 of the other format at ×0.5, 40% ADP formula), the normal model under ADP 90 and past ADP 133; spread 1.5 + 0.15 × ADP picks.",
  );
});

test("the league curve says what it was fitted on and which seasons the standings check reads", () => {
  const fit: CurveFit = {
    seasons: [{ year: 2026, rosters: 12, picks: 156, scored: 156, unmatched: [] }],
    skipped: [{ year: 2016, reason: "12 teams x 12 rounds, the session drafts 12 x 13" }],
    check: { pts: 3.58, fg_pct: null },
    check_seasons: ["2016-17", "2017-18", "2025-26"],
  };
  assert.equal(curveFitNote(fit), "12 rosters from 2026; standings check 2016-17 to 2025-26");
  const two: CurveFit = {
    ...fit,
    seasons: [...fit.seasons, { year: 2025, rosters: 12, picks: 156, scored: 154, unmatched: ["A", "B"] }],
    check: {},
    check_seasons: [],
  };
  assert.equal(curveFitNote(two), "24 rosters from 2026, 2025 (2 picks unscored); no standings check");
  const shared: CurveFit = {
    ...two,
    seasons: two.seasons.map((s, i) => ({ ...s, year: 2026, league: ["111", "222"][i] })),
  };
  assert.equal(curveFitNote(shared), "24 rosters from 2026 111, 2026 222 (2 picks unscored); no standings check");
  // Pooled from the other format at half weight, and blended toward the simulated league (#77).
  const pooled: CurveFit = {
    ...shared,
    seasons: shared.seasons.map((s, i) => (i ? { ...s, format: "points", weight: 0.5 } : s)),
    drafts: 1.5,
    blend: { drafts: 1.5, weight: 0.6, prior: "flat default", prior_status: "static" },
  };
  assert.equal(
    curveFitNote(pooled),
    "24 rosters from 2026 111, 2026 222 (points ×0.5) (2 picks unscored); no standings check; blend: 1.5 drafts toward the static fit until today's run lands",
  );
  assert.match(curveFitNote({ ...pooled, blend: { ...pooled.blend!, prior_status: "ready" } }), /blend: 1\.5 drafts toward today's simulated run$/);
});

test("the footer shows the room's pick clock and the plan budget it gives", () => {
  assert.equal(clockNote({ clock_s: 60, plan_time_limit: 20 }), " · 60 s clock, plan 20 s");
  assert.equal(clockNote({ clock_s: 30, plan_time_limit: 5 }), " · 30 s clock, plan 5 s");
  assert.equal(clockNote({ clock_s: null, plan_time_limit: 8 }), " · plan 8 s (fixed)");
  assert.equal(clockNote({}), "");
});

const cut = (over: Partial<AdjustmentRow>): AdjustmentRow =>
  ({ player_id: "p1", name: "A Player", team: "", games_fraction: null, games_out: null, note: null, fraction: 1, games: 60, games_left: 60, taken: false, ...over }) as AdjustmentRow;

test("out N weeks is about 3.75 games a week, four weeks about fifteen", () => {
  assert.equal(weeksToGames(4), 15);
  assert.equal(weeksToGames(1), 4);
  assert.equal(weeksToGames(8), 30);
});

test("a haircut reads as the weeks the board set, else as given", () => {
  const board = cut({ games_out: 15, note: "out 4 weeks", fraction: 0.75, games_left: 45 });
  assert.equal(haircutWeeks(board), 4);
  assert.equal(haircutLabel(board), "out 4 wk");
  assert.equal(haircutTitle(board), "games haircut: 15 games out (out 4 weeks), 45 of 60 projected games; his totals are scaled and z recomputed");
  assert.equal(haircutLabel(cut({ games_out: 10, note: "sweep: ESPN" })), "−10 GP");
  assert.equal(haircutWeeks(cut({ games_out: 10, note: "sweep: ESPN" })), null);
  assert.equal(haircutLabel(cut({ games_fraction: 0.8, fraction: 0.8 })), "×0.80 GP");
});

// Seat 4 and seat 12 of a 12-team, 13-round snake: seat 4 picks 4, 21, 28, ...; seat 12 picks 12
// and 13, 36 and 37, ... (the turnaround).
const snake = (seat: number, teams = 12, rounds = 13) =>
  Array.from({ length: rounds }, (_, r) => r * teams + (r % 2 === 0 ? seat : teams + 1 - seat));

test("the turn flag counts the picks to my turn down to you're next and your pick", () => {
  const my_picks = snake(4);
  const at = (next_overall: number) => turnFlag({ next_overall, my_next_pick: my_picks.find((k) => k >= next_overall) ?? null, complete: false, my_picks }, true);
  assert.deepEqual(at(1), { text: "3 picks to your turn", tone: "" });
  assert.deepEqual(at(3), { text: "you're next", tone: "" });
  assert.deepEqual(at(4), { text: "your pick", tone: "warn" });
  // After my pick the count starts again from the next one: 21 - 5 = 16.
  assert.deepEqual(at(5), { text: "16 picks to your turn", tone: "" });
  assert.equal(at(20)?.text, "you're next");
});

test("at the snake's turnaround my pick comes back at once: your pick, then again", () => {
  const my_picks = snake(12);
  const flag = (next_overall: number, clock: number | null = null) =>
    turnFlag({ next_overall, my_next_pick: my_picks.find((k) => k >= next_overall) ?? null, complete: false, my_picks }, true, clock);
  assert.deepEqual(flag(11), { text: "you're next", tone: "" });
  assert.deepEqual(flag(12, 42), { text: "your pick, then again · 0:42 left", tone: "warn" });
  assert.deepEqual(flag(13, 59), { text: "your pick · 0:59 left", tone: "warn" });
  assert.equal(flag(14)?.text, "22 picks to your turn");
  // A keeper in the second slot of the pair is no pick of mine: no "then again".
  const kept = my_picks.filter((k) => k !== 13);
  assert.equal(turnFlag({ next_overall: 12, my_next_pick: 12, complete: false, my_picks: kept }, true)?.text, "your pick");
  // A room's summary has no pick list: the plain flag.
  assert.equal(turnFlag({ next_overall: 12, my_next_pick: 12, complete: false }, true)?.text, "your pick");
});

test("the turn flag hides without a room, after my last pick and when the draft is complete", () => {
  const board = { next_overall: 5, my_next_pick: 8, complete: false };
  assert.equal(turnFlag(board, false), null);
  assert.equal(turnFlag({ ...board, my_next_pick: null }, true), null);
  assert.equal(turnFlag({ ...board, complete: true }, true), null);
  // The clock never reads below zero.
  assert.equal(turnFlag({ next_overall: 8, my_next_pick: 8, complete: false }, true, -3)?.text, "your pick · 0:00 left");
  assert.equal(clockText(125), "2:05");
});

test("the live panel lists live rooms by my next turn, finished rooms last, and names the next draft", () => {
  const room = (draft_id: string, next_overall: number, my_next_pick: number | null, complete = false) =>
    ({ draft_id, next_overall, my_next_pick, complete }) as RoomSummary;
  const order = roomOrder([room("done", 157, null, true), room("far", 10, 20), room("soon", 10, 11), room("over", 150, null)]);
  assert.deepEqual(
    order.map((r) => r.draft_id),
    ["soon", "far", "over", "done"],
  );
  const league = (id: string, draft_time: string | null) => ({ league: id, draft_time }) as LeagueSummary;
  const now = Date.parse("2026-10-17T20:00:00Z");
  const leagues = [league("past", "2026-10-17T18:00:00Z"), league("later", "2026-10-18T18:00:00Z"), league("next", "2026-10-18T03:00:00Z"), league("unknown", null)];
  assert.equal(nextDraft(leagues, now)?.league, "next");
  assert.equal(nextDraft([league("past", "2026-10-17T18:00:00Z")], now), null);
});

test("the form says what a league session's survival resolves to", () => {
  const base: LeagueResolved = {
    survival: "simulate", survival_file: null, note: null, blend: null, curve: "simulated",
    curve_drafts: null, adp_file: "leagues/1/yahoo_players.json", positions_file: "leagues/1/yahoo_players.json", rounds: 13,
  };
  assert.equal(leagueSurvivalText(base), "simulated drafts against the league's board");
  assert.equal(leagueSurvivalText({ ...base, note: "archive: no drafts of 12 x 13 yet" }), "simulated drafts against the league's board (archive: no drafts of 12 x 13 yet)");
  const blend = { drafts: 1.5, same_format: 1, other_format: 1, weight: 0.5 };
  assert.equal(
    leagueSurvivalText({ ...base, survival: "league", survival_file: "leagues/_shared/categories/survival_by_adp.csv", blend }),
    "the format's drafts by ADP (blend: 1.5 drafts: 1 of the format + 1 of the other format at ×0.5, 40% ADP formula)",
  );
  assert.equal(leagueSurvivalText({ ...base, survival: "league", survival_file: "leagues/1/survival_by_adp.csv" }), "this league's own drafts by ADP (leagues/1/survival_by_adp.csv)");
});
