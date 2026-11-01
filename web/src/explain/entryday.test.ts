import assert from "node:assert/strict";
import { test } from "node:test";
import { ENTRY_EVENTS, ENTRY_MAX, ENTRY_MIN, ENTRY_NODES, T, entryGates, entryHhmm, entryState, wrap } from "./entryday.ts";

test("the events are the example day's instants, unique and ascending, inside the play", () => {
  assert.equal(ENTRY_EVENTS.length, new Set(ENTRY_EVENTS).size);
  for (let i = 1; i < ENTRY_EVENTS.length; i++) assert.ok(ENTRY_EVENTS[i] > ENTRY_EVENTS[i - 1]);
  assert.ok(ENTRY_EVENTS[0] >= ENTRY_MIN && ENTRY_EVENTS[ENTRY_EVENTS.length - 1] <= ENTRY_MAX);
});

test("before the build the entry does not exist and every gate is unasked", () => {
  assert.deepEqual(entryState(ENTRY_MIN, 0), { cur: -1, dead: false });
  assert.deepEqual(
    entryGates(ENTRY_MIN, 0).map((g) => g.k),
    ["off", "off", "off", "off", "off", "off", "off"],
  );
});

test("the veto window blocks on the hour, then on the execute time, and the pass takes it after", () => {
  const atQueued = entryGates(T.queued, 0);
  assert.equal(atQueued[1].k, "no");
  assert.equal(atQueued[2].k, "no");
  assert.equal(entryState(T.queued, 0).cur, 1);
  const afterHour = entryGates(T.hour, 0);
  assert.equal(afterHour[1].k, "ok");
  assert.equal(afterHour[2].k, "no");
  const due = entryGates(T.exec, 0);
  assert.equal(due[2].k, "ok");
  assert.equal(due[4].k, "no");
  assert.equal(entryState(T.exec, 0).cur, 2);
  const claimed = entryGates(T.pass, 0);
  assert.equal(claimed[4].k, "ok");
  assert.equal(claimed[5].k, "ok");
  assert.match(claimed[5].text, /\$3/);
  assert.equal(entryState(T.pass, 0).cur, 4);
});

test("the claim clears at Yahoo's run and the next daily reads it", () => {
  assert.equal(entryState(T.run, 0).cur, 5);
  assert.equal(entryGates(T.run, 0)[6].k, "ok");
  assert.equal(entryState(ENTRY_MAX, 0).cur, ENTRY_NODES.length - 1);
  assert.match(entryGates(ENTRY_MAX, 0)[6].text, /won/);
});

test("a struck bid claims at $0; a struck entry dies in the veto window and never claims", () => {
  assert.match(entryGates(T.pass, 1)[5].text, /\$0/);
  assert.equal(entryGates(T.pass, 1)[3].k, "ok");
  assert.equal(entryGates(T.strike - 1, 2)[3].k, "ok");
  assert.deepEqual(entryState(T.strike, 2), { cur: 1, dead: true });
  const dead = entryGates(ENTRY_MAX, 2);
  assert.equal(dead[3].k, "no");
  assert.deepEqual(dead.slice(4).map((g) => g.k), ["off", "off", "off"]);
});

test("the clock reads the next day past midnight", () => {
  assert.equal(entryHhmm(T.queued), "05:40");
  assert.equal(entryHhmm(T.run), "next day 04:00");
  assert.equal(entryHhmm(ENTRY_MAX), "next day 06:00");
});

test("wrap keeps every line under the limit and loses no word", () => {
  const text = "the 09:15 pass opened the page: available · drop on the roster · under the cap · not struck · one live run a league";
  const lines = wrap(text, 64);
  assert.ok(lines.length >= 2);
  for (const l of lines) assert.ok(l.length <= 64, l);
  assert.equal(lines.join(" "), text);
  assert.deepEqual(wrap("one", 64), ["one"]);
});
