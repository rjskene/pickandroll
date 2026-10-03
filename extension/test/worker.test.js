// node --test extension/test/*.test.js
// The service worker's /plan hold can be cancelled by its caller (a superseded turn), which
// frees the connection at once and answers status 499, not "API down".
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const DIR = path.join(__dirname, "..");

/** worker.js in a context with a fake chrome and a fetch that holds until it is aborted or
 * released; returns the message entry point and the fetches it made. */
function loadWorker() {
  const listeners = [];
  const fetches = [];
  const evt = (list) => ({ addListener: (fn) => list.push(fn) });
  const chrome = {
    runtime: { onMessage: evt(listeners), onConnect: evt([]), onInstalled: evt([]), onStartup: evt([]) },
    storage: { local: { get: async () => ({ api: "http://api.test" }) }, session: {} },
    sidePanel: { setPanelBehavior: async () => {} },
  };
  function fetch(url, { signal, body } = {}) {
    return new Promise((resolve, reject) => {
      const f = { url, body: body ? JSON.parse(body) : null, aborted: false };
      f.release = (data) =>
        resolve({ ok: true, status: 200, text: async () => JSON.stringify(data) });
      fetches.push(f);
      if (signal) {
        signal.addEventListener("abort", () => {
          f.aborted = true;
          reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
        });
      }
    });
  }
  const ctx = vm.createContext({ chrome, fetch, AbortController, setTimeout, clearTimeout, console, URL });
  ctx.self = ctx;
  ctx.importScripts = (...files) => {
    for (const f of files) vm.runInContext(fs.readFileSync(path.join(DIR, f), "utf8"), ctx);
  };
  vm.runInContext(fs.readFileSync(path.join(DIR, "worker.js"), "utf8"), ctx);
  // Replies cross a message boundary, as in Chrome: serialized (and out of the vm's realm).
  const send = (msg) =>
    new Promise((resolve) => {
      const reply = (r) => resolve(JSON.parse(JSON.stringify(r)));
      for (const fn of listeners) if (fn(msg, { tab: { id: 1 } }, reply) === true) return;
      resolve(undefined);
    });
  return { send, fetches };
}

const tick = () => new Promise((r) => setImmediate(r));

test("a cancelled /plan hold aborts its fetch and answers 499", async () => {
  const w = loadWorker();
  const plan = w.send({ op: "plan", draft_id: "d", wait: 18, board: 23, hold: "h1" });
  await tick();
  assert.equal(w.fetches.length, 1);
  assert.match(w.fetches[0].url, /\/rooms\/d\/plan\?wait=18&board=23$/);
  assert.deepEqual(await w.send({ op: "cancel", hold: "h1" }), { ok: true, data: { cancelled: true } });
  assert.equal(w.fetches[0].aborted, true);
  assert.deepEqual(await plan, { ok: false, status: 499, error: "cancelled" });
  // The hold is gone: cancelling it again finds nothing.
  assert.deepEqual(await w.send({ op: "cancel", hold: "h1" }), { ok: true, data: { cancelled: false } });
});

test("a hold that answered is not cancelled, and a plan without a hold is unaffected", async () => {
  const w = loadWorker();
  const held = w.send({ op: "plan", draft_id: "d", wait: 5, board: 7, hold: "h2" });
  const bare = w.send({ op: "plan", draft_id: "d", wait: 0 });
  await tick();
  w.fetches[0].release({ board: 7, fresh: true });
  w.fetches[1].release({ board: 7, fresh: true });
  assert.deepEqual(await held, { ok: true, data: { board: 7, fresh: true } });
  assert.deepEqual(await bare, { ok: true, data: { board: 7, fresh: true } });
  assert.deepEqual(await w.send({ op: "cancel", hold: "h2" }), { ok: true, data: { cancelled: false } });
});

test("the attach carries the room's own team count once the room has shown it (#17)", async () => {
  const w = loadWorker();
  const shown = w.send({
    op: "attach",
    draft_id: "d",
    slot: 1,
    session_id: "s",
    num_teams: 12,
    room_teams: 10,
  });
  await tick();
  assert.equal(w.fetches.length, 1);
  assert.equal(w.fetches[0].body.room_teams, 10);
  assert.equal(w.fetches[0].body.num_teams, 12);
  w.fetches[0].release({ attached: true });
  await shown;
  const unseen = w.send({
    op: "attach",
    draft_id: "d",
    slot: 1,
    session_id: "s",
    num_teams: 12,
    room_teams: null,
  });
  await tick();
  assert.equal("room_teams" in w.fetches[1].body, false, "not known yet: the API cannot check");
  w.fetches[1].release({ attached: true });
  await unseen;
});
