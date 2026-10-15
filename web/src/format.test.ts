// Node's own test runner with its built-in type stripping (`npm test`); outside tsc's project,
// since the web app has no Node types.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { BoardPlayer } from "./api";
import { adpCell, adpTitle, rankLabel } from "./format.ts";

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
