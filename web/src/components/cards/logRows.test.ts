import assert from "node:assert/strict";
import { test } from "node:test";
import type { KeeperRow, PickRow } from "../../api";
import { byTeam, draftOrder, logItems } from "./logRows.ts";

const ME = "me";
const TEAMS = ["Team 1", ME, "Team 3"];

const pick = (overall: number, team: string, player_id: string, keeper = false): PickRow => ({
  overall,
  round: Math.ceil(overall / 3),
  position: 1,
  team,
  player_id,
  name: player_id.toUpperCase(),
  keeper,
});

const keeper = (overall: number, team: string, player_id: string, applied: boolean): KeeperRow => ({
  position: 1,
  round: Math.ceil(overall / 3),
  overall,
  player_id,
  name: player_id.toUpperCase(),
  team,
  mine: team === ME,
  applied,
});

test("keepers to come sit at their overall among the picks made", () => {
  const items = logItems([pick(1, "Team 1", "a"), pick(2, ME, "b")], [keeper(5, "Team 3", "k", false)], ME);
  assert.deepEqual(
    items.map((i) => [i.overall, i.toCome]),
    [
      [1, false],
      [2, false],
      [5, true],
    ],
  );
  assert.deepEqual(
    draftOrder(items).map((i) => i.overall),
    [5, 2, 1],
  );
});

test("an applied keeper is an ordinary row with the K mark, not a second row", () => {
  const items = logItems([pick(4, "Team 3", "k", true)], [keeper(4, "Team 3", "k", true)], ME);
  assert.equal(items.length, 1);
  assert.equal(items[0].keeper, true);
  assert.equal(items[0].toCome, false);
});

test("a kept player gets the K mark even when his pick row is not flagged a keeper", () => {
  const items = logItems([pick(7, "Team 1", "k", false), pick(8, "Team 1", "x")], [keeper(9, "Team 3", "k", false)], ME);
  assert.equal(items.find((i) => i.player_id === "k" && !i.toCome)?.keeper, true);
  assert.equal(items.find((i) => i.player_id === "x")?.keeper, false);
});

test("at one overall the pick made comes before the keeper still to come", () => {
  const items = logItems([pick(6, "Team 1", "x")], [keeper(6, ME, "k", false)], ME);
  assert.deepEqual(
    items.map((i) => i.key),
    ["pick-6", "keeper-6-k"],
  );
});

test("by team: draft-position order, picks in overall order, made counted without keepers to come", () => {
  const picks = [pick(1, "Team 1", "a"), pick(2, ME, "b"), pick(3, "Team 3", "c"), pick(4, "Team 3", "d"), pick(5, ME, "e")];
  const groups = byTeam(logItems(picks, [keeper(8, ME, "k", false)], ME), TEAMS);
  assert.deepEqual(
    groups.map((g) => [g.team, g.made, g.items.map((i) => i.overall), g.mine]),
    [
      ["Team 1", 1, [1], false],
      [ME, 2, [2, 5, 8], true],
      ["Team 3", 2, [3, 4], false],
    ],
  );
});

test("by team: a team outside the list follows, by its first pick; empty teams are left out", () => {
  const groups = byTeam(logItems([pick(2, "Visitor", "a"), pick(3, "Team 3", "b")], [], ME), TEAMS);
  assert.deepEqual(
    groups.map((g) => g.team),
    ["Team 3", "Visitor"],
  );
});
