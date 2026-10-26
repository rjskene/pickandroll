// pickandroll, service worker: the only part of the extension that talks to the pickandroll API
// (host permission for localhost, so the draft page never calls localhost itself). The content
// script and the side panel send it {op, ...}; it answers {ok, data} or {ok: false, status,
// error}. Status 0 means the API could not be reached; 499, that the caller cancelled it.
//
// MV3 stops an idle worker. Nothing is lost when it does: the room's history lives in the draft
// tab (page.js keeps every frame, the content script every pick) and is resent from the API's
// synced_through. What the side panel shows per tab is kept in chrome.storage.session.
//
// The league reader (league.js, #98) posts the league pages the user opens to the season's
// snapshot route here; what each post did is kept per league for the panel. On my team page it
// also fetches the lineup executor's steps and logs its runs here (#170), and the moves
// executor's due entries and its passes (#171), the last of each kept per league for the panel.
// A live claim is put on record here before its page is touched (``moves_submit:<entry>`` in
// chrome.storage.local, so a restart keeps it) and dropped only once the API has its pass: while
// it is there no pass submits that entry again.
"use strict";
importScripts("lib/protocol.js", "lib/league.js", "lib/lineup.js", "lib/moves.js");

const DEFAULTS = {
  api: "http://localhost:8000",
  web: "http://localhost:5173",
  players_file: "",
  probe_round: "3", // the queue probe's round, or "off"
  search_fallback: "off", // "on": Yahoo's search box for a row scrolling did not find
  lineup_executor: "on", // "off": this browser's brake on the lineup executor, beside STOP
  moves_executor: "on", // "off": this browser's brake on the moves executor, beside STOP
};

async function settings() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  const s = { ...DEFAULTS };
  for (const k of Object.keys(DEFAULTS)) if (typeof stored[k] === "string" && stored[k]) s[k] = stored[k];
  s.api = s.api.replace(/\/+$/, "");
  s.web = s.web.replace(/\/+$/, "");
  return s;
}

/** The extension's version (manifest.json): the attach logs it, so a scorecard states which
 * build ran. */
function version() {
  try {
    return chrome.runtime.getManifest().version;
  } catch (_) {
    return null;
  }
}

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const CANCELLED = 499; // the caller cancelled the request (not an API failure)
const SEAT_UNKNOWN = "seat not known yet, waiting for the draft order";

async function api(path, { method = "GET", body, timeout = 8000, signal = null } = {}) {
  const { api: base } = await settings();
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  const cancel = () => ctl.abort();
  if (signal) {
    if (signal.aborted) ctl.abort();
    else signal.addEventListener("abort", cancel, { once: true });
  }
  try {
    const r = await fetch(base + path, {
      method,
      signal: ctl.signal,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await r.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (_) {
      data = null;
    }
    if (!r.ok) {
      const detail = data && data.detail;
      throw new ApiError(r.status, typeof detail === "string" ? detail : text.slice(0, 300) || `HTTP ${r.status}`);
    }
    return data;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (signal && signal.aborted) throw new ApiError(CANCELLED, "cancelled");
    throw new ApiError(0, e.name === "AbortError" ? `no answer from ${base} in ${timeout / 1000} s` : `${base}: ${e.message}`);
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener("abort", cancel);
  }
}

// /plan holds by the caller's ``hold`` id. A turn that a newer one superseded cancels its hold,
// so a 20 s server wait nobody will read gives its connection back at once.
const holds = new Map();

const roomPath = (d) => `/rooms/${encodeURIComponent(d)}`;

/** Run ``fn``; a 404 from the room routes means no room is attached for this draft. */
async function attachedOr(fn) {
  try {
    return { attached: true, ...(await fn()) };
  } catch (e) {
    if (e.status === 404) return { attached: false };
    throw e;
  }
}

// ------------------------------------------------------------------ league pages (#98)
const postsKey = (league) => `league:${league}`;
const readKey = (league) => `season_read:${league}`;
const lineupKey = (league) => `lineup:${league}`;
const movesKey = (league) => `moves:${league}`;
const submitKey = (id) => `moves_submit:${id}`;
/** The submits put on record one after another, so two pages never pass the cap together. */
let submitting = Promise.resolve();

/** The live claims on record in ``league``: submitted, their pass not yet taken by the API. */
async function submits(league) {
  const all = await chrome.storage.local.get(null);
  return Object.entries(all)
    .filter(([k, v]) => k.startsWith("moves_submit:") && v && v.league === String(league))
    .map(([, v]) => v);
}

async function stored(key) {
  return (await chrome.storage.session.get(key))[key] || null;
}

/** Keep ``post`` as its page's line in the league's posts, newest per page. */
async function remember(league, post) {
  const posts = (await stored(postsKey(league))) || {};
  await chrome.storage.session.set({ [postsKey(league)]: { ...posts, [post.key]: post } });
}

const ops = {
  async settings() {
    return settings();
  },
  async status({ draft_id, slot = null, room_teams = null }) {
    const { api: base, probe_round, search_fallback } = await settings();
    const r = await attachedOr(async () => ({ room: await api(roomPath(draft_id)) }));
    if (!r.attached) {
      // The web app lists a room open here that no session follows (#10); the user attaches
      // it there. Best effort: the tab's status does not wait on it.
      const body = { draft_id, slot: slot || null, room_teams: room_teams || null };
      api("/rooms/seen", { method: "POST", body, timeout: 3000 }).catch(() => {});
    }
    return { ...r, api: base, probe_round, search_fallback };
  },
  async picks({ draft_id, picks }) {
    return attachedOr(() =>
      api(`${roomPath(draft_id)}/picks`, { method: "POST", body: { picks }, timeout: 20000 }),
    );
  },
  async events({ draft_id, events }) {
    return attachedOr(() => api(`${roomPath(draft_id)}/events`, { method: "POST", body: { events } }));
  },
  async plan({ draft_id, wait = 0, board = null, hold = null }) {
    const w = Math.max(0, Math.min(20, Number(wait) || 0));
    // ``board``: hold for the solve built on that many picks, not just the API's latest board.
    const b = Number.isInteger(board) && board >= 0 ? `&board=${board}` : "";
    const ctl = hold ? new AbortController() : null;
    if (ctl) holds.set(hold, ctl);
    try {
      return await api(`${roomPath(draft_id)}/plan?wait=${w}${b}`, {
        timeout: (w + 10) * 1000,
        signal: ctl && ctl.signal,
      });
    } finally {
      if (ctl && holds.get(hold) === ctl) holds.delete(hold);
    }
  },
  async cancel({ hold }) {
    const ctl = holds.get(hold);
    if (ctl) ctl.abort();
    return { cancelled: Boolean(ctl) };
  },
  async attach({ draft_id, slot, session_id, num_teams = 12, room_teams = null, pick_owners = null }) {
    // The tab's slot is my draft position, null until the room shows it (a league room's path
    // names the Yahoo team id instead): never attach without one.
    if (!(Number.isInteger(slot) && slot >= 1)) throw new ApiError(400, SEAT_UNKNOWN);
    const s = await settings();
    const body = { draft_id, slot, num_teams, mode: "mirror", session_id, ext_version: version() };
    if (room_teams) body.room_teams = room_teams; // the API refuses an attach that disagrees (#17)
    // The room's draft order (the position on each overall, from the R| frame): the session
    // drafts on it, so traded picks are their owners' and not the snake's.
    if (Array.isArray(pick_owners) && pick_owners.length) body.pick_owners = pick_owners;
    if (s.players_file) body.players_file = s.players_file;
    return api("/rooms", { method: "POST", body, timeout: 60000 });
  },
  async mode({ draft_id, mode }) {
    if (mode !== "mirror" && mode !== "autopilot") throw new ApiError(400, `unknown mode ${mode}`);
    return api(roomPath(draft_id), { method: "PATCH", body: { mode } });
  },
  async detach({ draft_id }) {
    return api(roomPath(draft_id), { method: "DELETE" });
  },
  async sessions() {
    return api("/sessions");
  },
  /** A league page as the user's Chrome rendered it, posted to the season's snapshot route.
   * Answers the post and ``follow``: the players page's Next 25 link, or the first page of the
   * read's next view, only while a multi-page read the user armed from the panel is running. */
  async season_page({ url, html, fetched_at, next = null }, sender) {
    const L = self.PickAndRoll;
    const page = L.leaguePage(url);
    if (!page) throw new ApiError(400, `not a league page: ${url}`);
    const key = L.postKey(page);
    const at = Date.now();
    let post;
    let season = null;
    try {
      const body = L.snapshotBody(url, html, fetched_at || at);
      const r = await api(`/seasons/${encodeURIComponent(page.league)}/snapshot`, { method: "POST", body, timeout: 30000 });
      post = { key, url, at, accepted: r.accepted || [], skipped: r.skipped || [] };
      season = r.season || null;
    } catch (e) {
      post = { key, url, at, error: e.message, status: e.status ?? 0 };
    }
    await remember(page.league, post);
    if (sender.tab) await chrome.storage.session.set({ [`league_tab:${sender.tab.id}`]: { ...page, url, at } });
    const read = await stored(readKey(page.league));
    const posted = !post.error && post.accepted.length > 0;
    const { follow, read: left } = L.afterPost(read, page, posted, next, url);
    if (read && left) await chrome.storage.session.set({ [readKey(page.league)]: left });
    else if (read) await chrome.storage.session.remove(readKey(page.league));
    return { post, follow, season };
  },
  /** Arm (``pages`` > 0) or stop a multi-page read of the league's players page, starting in
   * ``view`` (the page's ``stat1``). */
  async season_read({ league, pages = 0, view = null }) {
    const L = self.PickAndRoll;
    if (!(Number(pages) > 0)) {
      await chrome.storage.session.remove(readKey(league));
      return { read: null };
    }
    const read = L.startRead(league, Math.min(Number(pages), L.READ_PAGES), Date.now(), view);
    await chrome.storage.session.set({ [readKey(league)]: read });
    return { read };
  },
  /** The lineup executor's steps for my team's page of ``date`` (#170). */
  async lineup_steps({ league, date }) {
    const q = `date=${encodeURIComponent(date)}`;
    return api(`/seasons/${encodeURIComponent(league)}/lineup/steps?${q}`, { timeout: 30000 });
  },
  /** A run of the lineup executor, for the league's log; the last one is kept for the panel. */
  async lineup_log({ league, run }) {
    const logged = await api(`/seasons/${encodeURIComponent(league)}/autopilot/lineup`, { method: "POST", body: run, timeout: 15000 });
    const moves = (run.steps || []).filter((x) => x.outcome === "would_set").length;
    const last = { at: Date.now(), day: run.day, trigger: run.trigger, outcome: run.outcome, reason: run.reason, moves };
    await chrome.storage.session.set({ [lineupKey(league)]: last });
    return logged;
  },
  /** The moves executor's entries due now in ``league`` (#171), with what the page checks need. */
  async moves_due({ league }) {
    return api(`/seasons/${encodeURIComponent(league)}/autopilot/moves/due`, { timeout: 30000 });
  },
  /** An execute pass of the moves executor, for the league's log; the last one is kept for the
   * panel. Once the API has a live pass, its entries' submit records are dropped. */
  async moves_log({ league, run }) {
    const logged = await api(`/seasons/${encodeURIComponent(league)}/autopilot/moves`, { method: "POST", body: run, timeout: 15000 });
    if (run.mode === "live") await chrome.storage.local.remove((run.entries || []).map((x) => submitKey(x.id)));
    const claims = (run.entries || []).filter((x) => ["would_claim", "claimed"].includes(x.outcome)).length;
    const last = { at: Date.now(), day: run.day, trigger: run.trigger, outcome: run.outcome, reason: run.reason, claims };
    await chrome.storage.session.set({ [movesKey(league)]: last });
    return logged;
  },
  /** A live claim about to be submitted from the add page in ``sender``'s tab (#171 PR 3):
   * ``record`` is its day, trigger, the log's line for it and the day's cap and claims as the API
   * counted them. One at a time, and refused when the entry is on record already (it is never
   * submitted twice), when a claim on the same add is in flight, or when the claims in flight
   * that day would pass the cap. */
  moves_submitting({ league, record }, sender) {
    const run = submitting.then(async () => {
      const key = submitKey(record.line.id);
      if ((await chrome.storage.local.get(key))[key]) throw new Error("this claim was submitted already");
      const inflight = (await submits(league)).filter((x) => x.day === record.day);
      if (inflight.some((x) => x.line.add === record.line.add)) throw new Error("a claim on this add is in flight");
      if (record.cap != null && (record.done || 0) + inflight.length >= record.cap) throw new Error("over the day's cap with claims in flight");
      const kept = { ...record, league: String(league), tab: sender && sender.tab ? sender.tab.id : null, at: Date.now() };
      await chrome.storage.local.set({ [key]: kept });
      return { kept: true };
    });
    submitting = run.catch(() => {});
    return run;
  },
  /** The claim ``sender``'s tab submitted in ``league`` and whose pass is not logged, while its
   * answer may still be on this page (``LANDING_MS``); null otherwise. */
  async moves_landed({ league }, sender) {
    const tab = sender && sender.tab ? sender.tab.id : null;
    const now = Date.now();
    const mine = (await submits(league)).filter((x) => x.tab === tab && now - x.at < self.PickAndRoll.LANDING_MS);
    return mine.sort((a, b) => b.at - a.at)[0] || null;
  },
  /** Every live claim on record in ``league``: the add page logs the stale ones first and never
   * submits one of them again. */
  async moves_submits({ league }) {
    return submits(league);
  },
  /** The league's season summary (GET /seasons), null when pickandroll has no folder for it. */
  async season({ league }) {
    const all = await api("/seasons");
    return { season: (all || []).find((s) => s.league === String(league)) || null };
  },
  async report({ tab }, sender) {
    if (!sender.tab) return {};
    const { api: base } = await settings();
    await chrome.storage.session.set({
      [`tab:${sender.tab.id}`]: { ...tab, api_base: base, tab_id: sender.tab.id, at: Date.now() },
      last_tab: sender.tab.id,
    });
    return {};
  },
};

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  const fn = msg && ops[msg.op];
  if (!fn) return false;
  fn(msg, sender).then(
    (data) => reply({ ok: true, data }),
    (e) => reply({ ok: false, status: e.status ?? 0, error: String(e.message || e) }),
  );
  return true;
});

// A draft tab holds a port while it is open. When the port closes because the tab closed,
// reloaded or left the room, the seat is no longer under the extension's eye: say so.
chrome.runtime.onConnect.addListener((port) => {
  // A league page holds one too: when it closes or the tab leaves it, the panel stops showing it.
  if (port.name === "league") {
    port.onDisconnect.addListener(() => {
      void chrome.runtime.lastError;
      if (port.sender && port.sender.tab) chrome.storage.session.remove(`league_tab:${port.sender.tab.id}`);
    });
    return;
  }
  if (port.name !== "room") return;
  let seat = null;
  port.onMessage.addListener((m) => {
    if (m && m.draft_id) seat = { draft_id: String(m.draft_id), slot: Number(m.slot) || null };
  });
  port.onDisconnect.addListener(() => {
    void chrome.runtime.lastError;
    if (port.sender && port.sender.tab) chrome.storage.session.remove(`tab:${port.sender.tab.id}`);
    if (!seat) return;
    const event = { type: "control", state: "absent", slot: seat.slot, reason: "tab closed", t: Date.now() };
    api(`${roomPath(seat.draft_id)}/events`, { method: "POST", body: { events: [event] } }).catch(() => {});
  });
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
});
chrome.runtime.onStartup.addListener(() => {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
});
