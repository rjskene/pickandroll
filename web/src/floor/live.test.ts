// The live floor's reads (#462): the pace of the polling, the week's past days, and a run in
// flight drawn on the floor's scene from a live progress file.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { RoutineLivePayload } from "../api.ts";
import { GLOSSARY, termById } from "../explain/terms.ts";
import { termHash, termOfHash, parseHash } from "../explain/nav.ts";
import { TRACKS } from "../explain/tracks/index.ts";
import { AGENTS, timeline } from "./model.ts";
import { POLL, inFlight, livePoll, pastDays } from "./live.ts";
import { FLOW, FLOW_TERMS, sceneAt } from "./scene.ts";

const liveOf = (stale: boolean, progress = true): RoutineLivePayload => ({
  now: "2026-11-21T04:41:00Z",
  live: [
    {
      routine: "evening",
      file: "evening.json",
      written_at: "2026-11-21T04:40:30Z",
      stale,
      reason: null,
      progress: progress
        ? {
            routine: "evening",
            started_at: "2026-11-21T04:40:00Z",
            written_at: "2026-11-21T04:40:30Z",
            current: { name: "moves", after: "fresh_reads", started: "2026-11-21T04:40:30Z" },
            steps: [{ name: "fresh_reads", status: "ok", detail: "3 leagues read", started: "2026-11-21T04:40:00Z", finished: "2026-11-21T04:40:30Z" }],
          }
        : null,
    },
  ],
});

test("the floor polls every few seconds while a run or a pass is in flight, once a minute at rest (#462)", () => {
  assert.equal(livePoll(null, null), POLL.rest);
  assert.equal(livePoll({ now: "", live: [] }, { active: null }), POLL.rest);
  assert.equal(livePoll(liveOf(false), null), POLL.busy);
  // a stale file is a killed run, not one in flight; a file that does not read is none either
  assert.equal(livePoll(liveOf(true), null), POLL.rest);
  assert.equal(livePoll(liveOf(false, false), null), POLL.rest);
  assert.equal(inFlight(null, { active: { id: "p" } as never }), true);
});

test("the week strip reads the queues of the week's days before today (#462)", () => {
  assert.deepEqual(pastDays("2026-11-20"), ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19"]);
  assert.deepEqual(pastDays("2026-11-16"), []);
  assert.deepEqual(pastDays("2026-11-22"), ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21"]);
});

test("a run in flight plays on the floor: the panel names the run and its step, its agent at work (#462)", () => {
  const now = Date.parse("2026-11-21T04:41:00Z");
  const tl = timeline({ live: liveOf(false), now });
  const s = sceneAt({ tl, t: now, age: (x) => (now - x) / 1000, now: 0, leagues: [], one: null, executeTime: "22:40" });
  assert.equal(s.now.agent, "mover");
  assert.match(s.now.title, /evening/i);
  assert.ok(s.now.steps.some((x) => x.name === "fresh_reads" && x.state === "done"));
  assert.ok(s.now.steps.some((x) => x.name === "moves" && x.state === "running"));
});

test("the floor's names and stage titles each open a glossary term by its hash (#462)", () => {
  assert.equal(FLOW_TERMS.length, FLOW.length);
  for (const id of [...FLOW_TERMS, ...Object.keys(AGENTS), "the-floor", "demo"]) assert.ok(termById(id), id);
  assert.equal(new Set(GLOSSARY.map((t) => t.id)).size, GLOSSARY.length);
  assert.equal(termOfHash(termHash("out-and-back")), "out-and-back");
  assert.equal(termOfHash("#moves/2"), null);
  // a term hash is no place: Explain stays where it opens
  assert.deepEqual(parseHash(termHash("scout"), TRACKS), parseHash("", TRACKS));
});
