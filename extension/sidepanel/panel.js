// pickandroll side panel: the draft tab's room (what the content script last reported, kept in
// chrome.storage.session by the service worker) plus the API's view of it, and the controls to
// attach a session, see the mode and detach.
"use strict";

const $ = (id) => document.getElementById(id);
const REFRESH_MS = 2000;

async function call(op, body = {}) {
  const r = await chrome.runtime.sendMessage({ op, ...body });
  if (!r) throw new Error("no answer from the extension");
  if (!r.ok) {
    const e = new Error(r.error);
    e.status = r.status;
    throw e;
  }
  return r.data;
}

const show = (id, on) => {
  $(id).hidden = !on;
};
const text = (id, value) => {
  $(id).textContent = value;
};

let tab = null; // the draft tab's report
let room = null; // GET /rooms/{d}
let sessions = null;
let busy = false;

async function draftTab() {
  const all = await chrome.storage.session.get(null);
  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  return (active && all[`tab:${active.id}`]) || (all.last_tab != null ? all[`tab:${all.last_tab}`] : null) || null;
}

async function load() {
  if (busy) return;
  busy = true;
  try {
    tab = await draftTab();
    room = null;
    if (tab) {
      try {
        const r = await call("status", { draft_id: tab.draft_id });
        room = r.attached ? r.room : null;
        setApi("ok", r.api);
      } catch (e) {
        setApi(e.status ? "ok" : "bad", tab.api_base, e.message);
      }
    } else {
      const s = await call("settings").catch(() => null);
      if (s) setApi("unknown", s.api);
    }
    if (tab && !room && !sessions) await loadSessions();
    render();
  } finally {
    busy = false;
  }
}

function setApi(state, base, error) {
  const el = $("api");
  el.className = "pill " + (state === "ok" ? "ok" : state === "bad" ? "bad" : "");
  el.textContent = state === "ok" ? "API ok" : state === "bad" ? "API unreachable" : "API";
  el.title = [base, error].filter(Boolean).join(": ");
}

async function loadSessions() {
  try {
    sessions = await call("sessions");
  } catch (e) {
    sessions = null;
    text("attach-error", e.message);
    show("attach-error", true);
  }
  const sel = $("session");
  sel.replaceChildren();
  for (const s of sessions || []) {
    const o = document.createElement("option");
    o.value = s.id;
    o.textContent = `${s.id} · ${s.projection || "projection"} · position ${s.my_position} of ${s.num_teams} · ${s.picks_made} picks`;
    sel.append(o);
  }
  if (!sessions || !sessions.length) {
    const o = document.createElement("option");
    o.textContent = "No sessions: create one in the pickandroll app";
    o.disabled = true;
    sel.append(o);
  }
  checkSession();
}

function checkSession() {
  const s = (sessions || []).find((x) => x.id === $("session").value);
  let warn = "";
  if (s && tab && s.my_position !== tab.slot) warn = `This session drafts from position ${s.my_position}; this seat is ${tab.slot}.`;
  if (s && s.picks_made > 0) warn += ` It already has ${s.picks_made} picks; the room's picks win.`;
  text("session-warn", warn.trim());
  show("session-warn", Boolean(warn));
  $("attach-btn").disabled = !s;
}

function render() {
  show("none", !tab);
  show("room", Boolean(tab));
  show("attach", Boolean(tab) && !room && tab.attached !== true);
  show("attached", Boolean(room));
  if (!tab) return;

  text("room-title", `Room ${tab.draft_id} · seat ${tab.slot}`);
  text("picks", `${tab.last} (${tab.room_picks} seen)`);
  const synced = room ? room.synced_through : tab.sent;
  const behind = Math.max(0, tab.last - synced);
  const sync = room
    ? behind
      ? `behind ${behind} (has ${synced})` + (room.waiting_for ? `, waiting for #${room.waiting_for}` : "")
      : `synced (${synced})`
    : tab.attached === false
      ? "not attached"
      : "-";
  text("sync", sync);
  $("sync").className = room ? (behind > 2 ? "bad" : behind ? "warn" : "ok") : "warn";
  const d = tab.on_deck;
  text("clock", d ? `#${d.overall}, seat ${d.slot}` : "-");
  text(
    "next",
    tab.my_turn != null
      ? `#${tab.my_turn}: your turn`
      : tab.next_mine != null
        ? `#${tab.next_mine}, in ${tab.next_mine - tab.contiguous - 1}`
        : "roster full",
  );
  text(
    "autodraft",
    tab.autodraft == null ? "not found" : tab.autodraft ? "ON: Yahoo picks for this seat" : "off",
  );
  $("autodraft").className = tab.autodraft ? "bad" : "";

  if (!room) return;
  const armed = room.mode === "autopilot";
  $("mode-mirror").setAttribute("aria-pressed", String(!armed));
  $("mode-armed").setAttribute("aria-pressed", String(armed));
  text(
    "mode-note",
    tab.autodraft
      ? "Yahoo's Autodraft is on: Yahoo picks for this seat until it is switched off."
      : armed
        ? "Armed: on your turn pickandroll drafts its top pick in Yahoo. Draft by hand any time to take over that pick; \"Hand pick next\" in the page skips one turn."
        : "Mirror: you draft in Yahoo; pickandroll follows every pick.",
  );

  const plan = tab.plan;
  const ol = $("plan");
  ol.replaceChildren(
    ...((plan && plan.top) || []).map((name) => {
      const li = document.createElement("li");
      li.textContent = name;
      return li;
    }),
  );
  text(
    "plan-state",
    plan && plan.for != null
      ? `for pick #${plan.for}: ${plan.fresh ? "fresh" : `board ${plan.board ?? "-"}, solving`}`
      : "shown when your pick is near",
  );

  const m = tab.last_mine;
  text(
    "last",
    m
      ? `#${m.overall}: ${m.top && m.top.yid === m.yid ? m.top.name + " (plan top)" : "Yahoo id " + m.yid + (m.top ? `; plan top was ${m.top.name}` : "")}${m.how ? ` · ${m.how}` : ""}`
      : "-",
  );

  const warnings = [];
  if (room.standins && room.standins.length) {
    warnings.push(`Stand-ins: ${room.standins.map((s) => `#${s.overall} ${s.name || s.yid}`).join(", ")}`);
  }
  if (room.unresolved && room.unresolved.length) warnings.push(`Unresolved picks: ${room.unresolved.length}`);
  if (room.conflicts && room.conflicts.length) warnings.push(`Conflicts (the room won): ${room.conflicts.length}`);
  const unmatched = (room.unmatched_projection || []).slice(0, 5).map((p) => p.name);
  const notes = unmatched.length
    ? [`Best projected players missing from Yahoo's list (never offered): ${unmatched.join(", ")}`]
    : [];
  const para = (cls) => (w) => {
    const p = document.createElement("p");
    p.className = cls;
    p.textContent = w;
    return p;
  };
  $("warnings").replaceChildren(...warnings.map(para("warn")), ...notes.map(para("muted small")));

  call("settings")
    .then((s) => {
      $("open-web").href = `${s.web}/?session=${encodeURIComponent(room.session_id)}`;
    })
    .catch(() => {});
}

$("session").addEventListener("change", checkSession);
$("attach-btn").addEventListener("click", async () => {
  const s = (sessions || []).find((x) => x.id === $("session").value);
  if (!s || !tab) return;
  $("attach-btn").disabled = true;
  show("attach-error", false);
  try {
    await call("attach", { draft_id: tab.draft_id, slot: tab.slot, session_id: s.id, num_teams: s.num_teams });
    sessions = null;
    await load();
  } catch (e) {
    text("attach-error", e.message);
    show("attach-error", true);
  } finally {
    $("attach-btn").disabled = false;
  }
});
$("mode-armed").addEventListener("click", async () => {
  if (!tab || !room || room.mode === "autopilot") return;
  const ok = confirm(
    "Arm pickandroll for this room?\n\nOn each of your turns it will click the Draft button for " +
      "pickandroll's top pick in Yahoo. You can still draft by hand at any time; your pick wins.",
  );
  if (!ok) return;
  await call("mode", { draft_id: tab.draft_id, mode: "autopilot" }).catch(() => {});
  load();
});
$("mode-mirror").addEventListener("click", async () => {
  if (!tab || !room || room.mode === "mirror") return;
  await call("mode", { draft_id: tab.draft_id, mode: "mirror" }).catch(() => {});
  load();
});
$("detach-btn").addEventListener("click", async () => {
  if (!tab || !confirm(`Detach room ${tab.draft_id}? The session keeps its picks; the room stops syncing.`)) return;
  await call("detach", { draft_id: tab.draft_id }).catch(() => {});
  sessions = null;
  load();
});
$("options").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

chrome.storage.onChanged.addListener((_, area) => {
  if (area === "session") load();
});
chrome.tabs.onActivated.addListener(() => load());
setInterval(() => {
  if (document.visibilityState === "visible") load();
}, REFRESH_MS);
load();
