// Node's own test runner with its built-in type stripping (`npm test`), as format.test.ts.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { AvailableRow, Rates, SeasonPlayer } from "./api";
import {
  ageLabel,
  availabilityLabel,
  catValue,
  changeLabel,
  horizonGames,
  oddsLabel,
  oddsTone,
  projectedTotals,
  DEFAULT_AVAILABLE_SORT,
  filterAvailable,
  isStale,
  NO_FILTER,
  ordinal,
  pctLabel,
  playsPosition,
  recordLabel,
  refreshNote,
  sortAvailable,
  statusTitle,
  statusTone,
  weekDates,
  weekLabel,
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

test("the available table sorts most rostered first, missing values last, ties in Yahoo's order", () => {
  const rows = [
    row(player("A", ["C"]), { pct_rostered: 12, adds: 5 }),
    row(player("B", ["C"]), { pct_rostered: null, adds: 9 }),
    row(player("C", ["C"]), { pct_rostered: 40, adds: 5, availability: "W", clears: "2026-10-23" }),
    row(player("D", ["C"]), { pct_rostered: 12, adds: null, availability: "W", clears: "2026-10-22" }),
  ];
  const order = (key: Parameters<typeof sortAvailable>[1]["key"], dir: "asc" | "desc") => sortAvailable(rows, { key, dir }).map((r) => r.player.name).join("");
  assert.equal(order(DEFAULT_AVAILABLE_SORT.key, DEFAULT_AVAILABLE_SORT.dir), "CADB");
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
