// pickandroll, service worker: the only part of the extension that talks to the pickandroll API
// (host permission for localhost, so the draft page never calls localhost itself). The content
// script and the side panel send it {op, ...}; it answers {ok, data} or {ok: false, status,
// error}. Status 0 means the API could not be reached.
//
// MV3 stops an idle worker. Nothing is lost when it does: the room's history lives in the draft
// tab (page.js keeps every frame, the content script every pick) and is resent from the API's
// synced_through. What the side panel shows per tab is kept in chrome.storage.session.
"use strict";
importScripts("lib/protocol.js");

const DEFAULTS = {
  api: "http://localhost:8000",
  web: "http://localhost:5173",
  players_file: "",
};

async function settings() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  const s = { ...DEFAULTS };
  for (const k of Object.keys(DEFAULTS)) if (typeof stored[k] === "string" && stored[k]) s[k] = stored[k];
  s.api = s.api.replace(/\/+$/, "");
  s.web = s.web.replace(/\/+$/, "");
  return s;
}

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function api(path, { method = "GET", body, timeout = 8000 } = {}) {
  const { api: base } = await settings();
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
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
    throw new ApiError(0, e.name === "AbortError" ? `no answer from ${base} in ${timeout / 1000} s` : `${base}: ${e.message}`);
  } finally {
    clearTimeout(timer);
  }
}

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

const ops = {
  async settings() {
    return settings();
  },
  async status({ draft_id }) {
    const { api: base } = await settings();
    const r = await attachedOr(async () => ({ room: await api(roomPath(draft_id)) }));
    return { ...r, api: base };
  },
  async picks({ draft_id, picks }) {
    return attachedOr(() =>
      api(`${roomPath(draft_id)}/picks`, { method: "POST", body: { picks }, timeout: 20000 }),
    );
  },
  async events({ draft_id, events }) {
    return attachedOr(() => api(`${roomPath(draft_id)}/events`, { method: "POST", body: { events } }));
  },
  async plan({ draft_id, wait = 0, board = null }) {
    const w = Math.max(0, Math.min(20, Number(wait) || 0));
    // ``board``: hold for the solve built on that many picks, not just the API's latest board.
    const b = Number.isInteger(board) && board >= 0 ? `&board=${board}` : "";
    return api(`${roomPath(draft_id)}/plan?wait=${w}${b}`, { timeout: (w + 10) * 1000 });
  },
  async attach({ draft_id, slot, session_id, num_teams = 12 }) {
    const s = await settings();
    const body = { draft_id, slot, num_teams, mode: "mirror", session_id };
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
