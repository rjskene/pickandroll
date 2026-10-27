// node --test extension/test/*.test.js
// The league page reader (#98): which pages it posts, the snapshot body, and the multi-page read
// of the players page, in lib/league.js and in the service worker's season ops.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const L = require("../lib/league.js");

const DIR = path.join(__dirname, "..");
const SITE = "https://basketball.fantasysports.yahoo.com";

test("the reader knows the league's own pages and nothing else", () => {
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822`), { league: "31822", kind: "league" });
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/`), { league: "31822", kind: "league" });
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/3`), { league: "31822", kind: "team", team: 3 });
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/3?stat1=S_PS7`), { league: "31822", kind: "team", team: 3 });
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/players?status=A&pos=P&count=50`), { league: "31822", kind: "players", offset: 50 });
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/players`), { league: "31822", kind: "players", offset: 0 });
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/players?status=A&stat1=S_PS7&count=25`), {
    league: "31822",
    kind: "players",
    offset: 25,
    view: "S_PS7",
  });
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/matchup?week=1&mid1=3&mid2=8`), { league: "31822", kind: "matchup" });
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/transactions`), { league: "31822", kind: "transactions" });
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/draftresults`), { league: "31822", kind: "draftresults" });
  // A team's page for a day is that day's lineup (#107); the settings page, the held slots and the rule.
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/3?date=2026-10-18`), { league: "31822", kind: "team", team: 3, date: "2026-10-18" });
  assert.deepEqual(L.leaguePage(`${SITE}/nba/31822/settings`), { league: "31822", kind: "settings" });
  // Not read: the draft client, a player's page, a team's sub-pages, another site, plain http.
  for (const url of [
    `${SITE}/draftclient/31822/3`,
    `${SITE}/nba/31822/3/team?stat1=S_PS7`,
    `${SITE}/nba/31822/3?date=2026-02-30`, // not a day
    `${SITE}/nba/31822/3?date=`,
    `${SITE}/nba/31822/3?date=20261018`,
    `${SITE}/nba/31822/settings/edit`,
    `${SITE}/nba/players/6013`,
    `${SITE}/nba/31822/playerswatch`,
    `https://sports.yahoo.com/nba/31822`,
    `http://basketball.fantasysports.yahoo.com/nba/31822`,
    "not a url",
  ]) {
    assert.equal(L.leaguePage(url), null, url);
  }
});

test("each page keeps one line in the panel, the snapshot body carries the page as rendered", () => {
  assert.equal(L.postKey({ kind: "team", team: 3 }), "team 3");
  assert.equal(L.postKey({ kind: "team", team: 3, date: "2026-10-26" }), "team 3 on 2026-10-26");
  assert.equal(L.postKey({ kind: "settings" }), "settings");
  assert.equal(L.postKey({ kind: "players", offset: 25 }), "players 26-50");
  assert.equal(L.postKey({ kind: "players", offset: 25, view: "R_O" }), "players 26-50");
  assert.equal(L.postKey({ kind: "players", offset: 0, view: "S_PS7" }), "players 1-25 (next 7 days)");
  assert.equal(L.postKey({ kind: "matchup" }), "matchup");
  const at = Date.parse("2026-10-21T18:00:00Z");
  assert.deepEqual(L.snapshotBody(`${SITE}/nba/31822/3`, "<html></html>", at), {
    pages: [{ url: `${SITE}/nba/31822/3`, html: "<html></html>", fetched_at: "2026-10-21T18:00:00.000Z" }],
  });
});

test("a multi-page read follows Next 25 only on the armed league's players pages, and stops", () => {
  const p0 = L.leaguePage(`${SITE}/nba/31822/players?count=0`);
  const next = `${SITE}/nba/31822/players?count=25`;
  // Nothing armed: never navigates.
  assert.deepEqual(L.afterPost(null, p0, true, next), { follow: null, read: null });
  // Started in the projection view, the read has no other view to walk.
  const read = L.startRead("31822", 3, 1000, "S_PS7");
  assert.deepEqual(read, { league: "31822", pages: 3, pages_left: 3, started_at: 1000, then: [] });
  let r = L.afterPost(read, p0, true, next);
  assert.equal(r.follow, next);
  assert.equal(r.read.pages_left, 2);
  r = L.afterPost(r.read, L.leaguePage(next), true, `${SITE}/nba/31822/players?count=50`);
  assert.equal(r.read.pages_left, 1);
  // The last page of the read: posted, and the read is done.
  assert.deepEqual(L.afterPost(r.read, L.leaguePage(`${SITE}/nba/31822/players?count=50`), true, `${SITE}/nba/31822/players?count=75`), { follow: null, read: null });
  // A short page (no Next 25), a failed post, or a link elsewhere ends it.
  assert.deepEqual(L.afterPost(read, p0, true, null), { follow: null, read: null });
  assert.deepEqual(L.afterPost(read, p0, false, next), { follow: null, read: null });
  assert.deepEqual(L.afterPost(read, p0, true, `${SITE}/draftclient/31822/3`), { follow: null, read: null });
  // Another league's page, or a team page, leaves the read alone and does not navigate.
  assert.deepEqual(L.afterPost(read, L.leaguePage(`${SITE}/nba/15953/players`), true, `${SITE}/nba/15953/players?count=25`), { follow: null, read });
  assert.deepEqual(L.afterPost(read, L.leaguePage(`${SITE}/nba/31822/3`), true, null), { follow: null, read });
});

test("a read started in another view walks Next 7 Days (proj) after it, from its first page", () => {
  const url = (view, n) => `${SITE}/nba/31822/players?status=A&pos=P&stat1=${view}&sort=R_PO&sdir=1&count=${n}`;
  const read = L.startRead("31822", 2, 1000, "R_O");
  assert.deepEqual(read.then, ["S_PS7"]);
  assert.deepEqual(L.startRead("31822", 2, 1000).then, ["S_PS7"], "the default view too");
  let r = L.afterPost(read, L.leaguePage(url("R_O", 0)), true, url("R_O", 25), url("R_O", 0));
  assert.equal(r.follow, url("R_O", 25));
  // The ownership view's last page: on to the projection view's first, its filters and sort kept.
  r = L.afterPost(r.read, L.leaguePage(url("R_O", 25)), true, url("R_O", 50), url("R_O", 25));
  assert.equal(r.follow, `${SITE}/nba/31822/players?status=A&pos=P&stat1=S_PS7&sort=R_PO&sdir=1`);
  assert.deepEqual(r.read, { ...read, pages_left: 2, then: [] });
  r = L.afterPost(r.read, L.leaguePage(r.follow), true, url("S_PS7", 25), r.follow);
  assert.equal(r.follow, url("S_PS7", 25));
  assert.deepEqual(L.afterPost(r.read, L.leaguePage(url("S_PS7", 25)), true, url("S_PS7", 50), url("S_PS7", 25)), { follow: null, read: null });
  // A short page moves on too; a failed post still ends the whole read.
  assert.equal(L.afterPost(read, L.leaguePage(url("R_O", 0)), true, null, url("R_O", 0)).follow, L.viewUrl(url("R_O", 0), "S_PS7"));
  assert.deepEqual(L.afterPost(read, L.leaguePage(url("R_O", 0)), false, url("R_O", 25), url("R_O", 0)), { follow: null, read: null });
  // The user moved to the projection view mid-read: it is not walked twice.
  assert.deepEqual(L.afterPost({ ...read, pages_left: 1 }, L.leaguePage(url("S_PS7", 0)), true, url("S_PS7", 25), url("S_PS7", 0)), { follow: null, read: null });
});

test("the panel's lines say what each post did", () => {
  const now = Date.parse("2026-10-21T18:00:00Z");
  assert.equal(L.ago(now - 5000, now), "5 s ago");
  assert.equal(L.ago(now - 180_000, now), "3 min ago");
  assert.equal(L.ago(now - 5 * 3600_000, now), "5 h ago");
  assert.equal(L.postLine({ key: "team 3", at: now - 60_000, accepted: ["roster/3"], skipped: [] }, now), "team 3: posted 1 min ago as roster/3");
  assert.equal(L.postLine({ key: "team 3", at: now, error: "no league 31822" }, now), "team 3: no league 31822 (0 s ago)");
  assert.equal(
    L.postLine({ key: "players 1-25", at: now, accepted: [], skipped: [{ url: "u", reason: "no player table on the players page" }] }, now),
    "players 1-25: not read: no player table on the players page (0 s ago)",
  );
});

// ---------------------------------------------------------------- the service worker's ops
/** worker.js with a fake chrome (session storage in a Map) and a fetch that answers ``reply``. */
function loadWorker(reply) {
  const listeners = [];
  const fetches = [];
  const store = new Map();
  const evt = (list) => ({ addListener: (fn) => list.push(fn) });
  const session = {
    get: async (key) => {
      if (key == null) return Object.fromEntries(store);
      return store.has(key) ? { [key]: structuredClone(store.get(key)) } : {};
    },
    set: async (obj) => {
      for (const [k, v] of Object.entries(obj)) store.set(k, structuredClone(v));
    },
    remove: async (key) => {
      store.delete(key);
    },
  };
  const chrome = {
    runtime: { onMessage: evt(listeners), onConnect: evt([]), onInstalled: evt([]), onStartup: evt([]) },
    storage: { local: { get: async () => ({ api: "http://api.test" }) }, session },
    sidePanel: { setPanelBehavior: async () => {} },
  };
  async function fetch(url, { method, body } = {}) {
    const f = { url, method, body: body ? JSON.parse(body) : null };
    fetches.push(f);
    const [status, data] = reply(f);
    return { ok: status < 400, status, text: async () => JSON.stringify(data) };
  }
  const ctx = vm.createContext({ chrome, fetch, AbortController, setTimeout, clearTimeout, console, URL });
  ctx.self = ctx;
  ctx.importScripts = (...files) => {
    for (const f of files) vm.runInContext(fs.readFileSync(path.join(DIR, f), "utf8"), ctx);
  };
  vm.runInContext(fs.readFileSync(path.join(DIR, "worker.js"), "utf8"), ctx);
  const send = (msg, tabId = 7) =>
    new Promise((resolve) => {
      const done = (r) => resolve(JSON.parse(JSON.stringify(r)));
      for (const fn of listeners) if (fn(msg, { tab: { id: tabId } }, done) === true) return;
      resolve(undefined);
    });
  return { send, fetches, store };
}

const accepted = (keys) => () => [200, { accepted: keys, skipped: [], season: { league: "31822", week: 1 } }];

test("a league page is posted to the season's snapshot route and remembered for the panel", async () => {
  const w = loadWorker(accepted(["roster/3"]));
  const url = `${SITE}/nba/31822/3`;
  const r = await w.send({ op: "season_page", url, html: "<html>team</html>", fetched_at: Date.parse("2026-10-21T18:00:00Z") });
  assert.equal(r.ok, true);
  assert.equal(w.fetches.length, 1);
  assert.equal(w.fetches[0].url, "http://api.test/seasons/31822/snapshot");
  assert.equal(w.fetches[0].method, "POST");
  assert.deepEqual(w.fetches[0].body, { pages: [{ url, html: "<html>team</html>", fetched_at: "2026-10-21T18:00:00.000Z" }] });
  assert.deepEqual(r.data.post.accepted, ["roster/3"]);
  assert.equal(r.data.follow, null);
  assert.deepEqual(w.store.get("league:31822")["team 3"].accepted, ["roster/3"]);
  assert.deepEqual(w.store.get("league_tab:7"), { league: "31822", kind: "team", team: 3, url, at: w.store.get("league_tab:7").at });
});

test("a refused post is remembered with the API's reason, and never follows a link", async () => {
  const w = loadWorker(() => [404, { detail: "no league folder 31822" }]);
  await w.send({ op: "season_read", league: "31822", pages: 12 });
  const r = await w.send({ op: "season_page", url: `${SITE}/nba/31822/players`, html: "<html></html>", next: `${SITE}/nba/31822/players?count=25` });
  assert.equal(r.data.follow, null);
  assert.equal(r.data.post.error, "no league folder 31822");
  assert.equal(w.store.get("league:31822")["players 1-25"].status, 404);
  // The failed page ended the read.
  assert.equal(w.store.has("season_read:31822"), false);
});

test("an armed read walks the players pages in both views, then disarms; stop disarms at once", async () => {
  const w = loadWorker(accepted(["available"]));
  const page = (n, view = "R_O") => `${SITE}/nba/31822/players?status=A&pos=P&stat1=${view}&count=${n}`;
  assert.equal((await w.send({ op: "season_page", url: page(0), html: "x", next: page(25) })).data.follow, null, "nothing armed");
  await w.send({ op: "season_read", league: "31822", pages: 2, view: "R_O" });
  assert.equal((await w.send({ op: "season_page", url: page(0), html: "x", next: page(25) })).data.follow, page(25));
  const first = `${SITE}/nba/31822/players?status=A&pos=P&stat1=S_PS7`;
  assert.equal((await w.send({ op: "season_page", url: page(25), html: "x", next: page(50) })).data.follow, first);
  assert.equal((await w.send({ op: "season_page", url: first, html: "x", next: page(25, "S_PS7") })).data.follow, page(25, "S_PS7"));
  assert.equal((await w.send({ op: "season_page", url: page(25, "S_PS7"), html: "x", next: page(50, "S_PS7") })).data.follow, null);
  assert.equal(w.store.has("season_read:31822"), false);
  assert.deepEqual(Object.keys(w.store.get("league:31822")).sort(), [
    "players 1-25",
    "players 1-25 (next 7 days)",
    "players 26-50",
    "players 26-50 (next 7 days)",
  ]);
  // At most READ_PAGES pages, whatever the panel asks.
  assert.equal((await w.send({ op: "season_read", league: "31822", pages: 99 })).data.read.pages_left, L.READ_PAGES);
  assert.deepEqual((await w.send({ op: "season_read", league: "31822", pages: 0 })).data, { read: null });
  assert.equal(w.store.has("season_read:31822"), false);
});

test("the panel's season line comes from GET /seasons; a league with no folder is null", async () => {
  const w = loadWorker(() => [200, [{ league: "15953", week: 1 }, { league: "31822", week: 2 }]]);
  assert.deepEqual((await w.send({ op: "season", league: "31822" })).data, { season: { league: "31822", week: 2 } });
  assert.deepEqual((await w.send({ op: "season", league: "99999" })).data, { season: null });
  assert.equal(w.fetches[0].url, "http://api.test/seasons");
});

test("a page that is not a league page is refused before anything is posted", async () => {
  const w = loadWorker(accepted([]));
  const r = await w.send({ op: "season_page", url: `${SITE}/draftclient/31822/3`, html: "x" });
  assert.equal(r.ok, false);
  assert.equal(r.status, 400);
  assert.equal(w.fetches.length, 0);
});

test("the league reader runs on league pages only, never on the draft client", () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(DIR, "manifest.json"), "utf8"));
  const reader = manifest.content_scripts.find((c) => c.js.includes("league.js"));
  assert.deepEqual(reader.matches, ["https://basketball.fantasysports.yahoo.com/nba/*"]);
  assert.deepEqual(reader.js, ["lib/league.js", "lib/lineup.js", "lib/moves.js", "lib/startactive.js", "lib/ilmove.js", "league.js"]);
  for (const c of manifest.content_scripts) {
    if (c === reader) continue;
    assert.ok(!c.js.includes("league.js"), "the draft client's scripts do not include the reader");
  }
  // The reader clicks nothing: no click() and no dispatched events in its source.
  const src = fs.readFileSync(path.join(DIR, "league.js"), "utf8");
  assert.ok(!/\.click\(|dispatchEvent|submit\(/.test(src));
});
