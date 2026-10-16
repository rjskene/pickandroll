// Node's own test runner with its built-in type stripping (`npm test`); outside tsc's project,
// since the web app has no Node types.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { AvailabilityBias, BoardPlayer, SessionSummary } from "./api";
import { adpCell, adpTitle, armLabel, biasDetail, draftWhen, oddsSource, rankLabel, survivalDetail } from "./format.ts";

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
});
