// Node's own test runner with its built-in type stripping (`npm test`), as format.test.ts.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { AvailableRow, SeasonPlayer } from "./api";
import {
  ageLabel,
  availabilityLabel,
  changeLabel,
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
