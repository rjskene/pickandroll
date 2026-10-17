import assert from "node:assert/strict";
import { test } from "node:test";
import type { SessionCreateBody } from "./api";
import { createWithCurveFallback } from "./sessionRequest.ts";

const BODY: SessionCreateBody = {
  projection_file: "bbm.csv",
  league: "251146",
  my_position: 7,
  my_team: "me",
  objective: "win",
  sigma_scale: 1,
  curve_file: null,
  curve: "league",
  survival_sims: 300,
  solve_ahead: true,
  time_limit: 20,
};

/** A server that refuses curve=league with the API's 400 and makes anything else. */
function server(refuse = "curve=league: no season to fit") {
  const sent: SessionCreateBody[] = [];
  const create = async (body: SessionCreateBody) => {
    sent.push(body);
    if (body.curve === "league" && refuse) throw new Error(refuse);
    return { id: `s${sent.length}` };
  };
  return { sent, create };
}

test("a league curve the folder resolved and the server cannot fit falls back to the simulated curve, with the reason", async () => {
  const { sent, create } = server();
  const made = await createWithCurveFallback(create, BODY, true);
  assert.deepEqual(made, { session: { id: "s2" }, curveNote: "curve=league: no season to fit" });
  assert.equal(sent.length, 2);
  assert.equal("curve" in sent[1], false, "the retry leaves the curve to the server");
  assert.equal(sent[1].league, "251146", "and keeps the rest of the request");
  assert.equal(BODY.curve, "league", "the form's own body is not changed");
});

test("the curve the user chose, and any other refusal, fail as they are", async () => {
  const chosen = server();
  await assert.rejects(createWithCurveFallback(chosen.create, BODY, false), /curve=league/);
  assert.equal(chosen.sent.length, 1);
  const other = server("projections not found: bbm.csv");
  await assert.rejects(createWithCurveFallback(other.create, BODY, true), /projections not found/);
  assert.equal(other.sent.length, 1);
});

test("a league curve the server fits makes the session once", async () => {
  const { sent, create } = server("");
  assert.deepEqual(await createWithCurveFallback(create, BODY, true), { session: { id: "s1" }, curveNote: null });
  assert.equal(sent.length, 1);
});
