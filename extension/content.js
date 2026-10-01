// pickandroll, content half (isolated world). Mirrors the Yahoo draft room into the pickandroll
// API through the service worker: every pick the room's socket sends (page.js hands them over),
// the pick on the clock, and the fidelity events of docs/YAHOO_SYNC.md §4. It shows a status
// strip in the page. In this build it never clicks anything in Yahoo.
(() => {
  "use strict";
  const PR = globalThis.PickAndRoll;
  const KEY = "__pickandroll";
  const where = PR.roomFromPath(location.pathname);
  if (!where || window[KEY + "Content"]) return;
  window[KEY + "Content"] = true;

  const STATUS_EVERY_MS = 3000;
  const HEARTBEAT_EVERY_MS = 15000;
  const WATCH_EVERY_MS = 1000;
  const PLAN_AHEAD = 3; // fetch the plan once my pick is this many picks away
  const PLAN_WAIT_S = 20; // on my turn, hold this long for a fresh solve
  const BY_HAND_MS = 3000; // a switch flip this soon after a trusted click on it is the user's

  const tracker = new PR.RoomTracker({ draftId: where.draft_id, slot: where.slot });
  const S = {
    attached: null, // null until the API answers, then true / false
    api: "unknown", // "ok" | "down"
    base: "",
    room: null, // GET /rooms/{d}
    mode: null, // the room's mode in the API: "mirror" | "autopilot"
    control: null, // what this tab last reported: "mirror" | "absent"
    plan: null,
    lastMine: null,
    handPick: null,
    autodraft: null, // Yahoo's Autodraft switch: true / false / null (not found)
    autodraftClickAt: 0,
    autopickMode: false, // Yahoo picks for the seat: the Autodraft switch is on
    autoReason: null, // "autopick" (Yahoo flipped it: G5), "autodraft at entry", "autodraft by hand"
    helloSlot: null,
    worker: false,
    dead: false,
    error: null,
  };
  const names = new Map(); // Yahoo id -> name, from plans
  const outbox = []; // client events the API has not accepted yet

  // ------------------------------------------------------------------ timers (page worker)
  let wakeId = 0;
  const wakes = new Map();
  function sleep(ms) {
    return new Promise((resolve) => {
      if (!S.worker) {
        setTimeout(resolve, ms);
        return;
      }
      const id = ++wakeId;
      wakes.set(id, resolve);
      window.postMessage({ [KEY]: "content", dir: "sleep", id, ms }, location.origin);
    });
  }
  async function every(ms, fn) {
    while (!S.dead) {
      try {
        await fn();
      } catch (e) {
        S.error = String((e && e.message) || e);
      }
      await sleep(ms);
    }
  }

  // ------------------------------------------------------------------ service worker
  async function call(op, body = {}) {
    if (S.dead) throw new Error("extension reloaded");
    let r;
    try {
      r = await chrome.runtime.sendMessage({
        op,
        draft_id: tracker.draftId,
        slot: tracker.slot,
        ...body,
      });
    } catch (e) {
      if (/context invalidated/i.test(String(e && e.message))) {
        S.dead = true;
        render();
      }
      throw e;
    }
    if (!r) throw new Error("no answer from the service worker");
    if (!r.ok) {
      if (!r.status) S.api = "down";
      const err = new Error(r.error || "error");
      err.status = r.status;
      throw err;
    }
    S.api = "ok";
    return r.data;
  }

  // The port tells the service worker this tab holds the seat; when it closes (tab closed or
  // reloaded) the worker posts control: absent. A worker restart also closes it: reconnect.
  function connect() {
    if (S.dead) return;
    let port;
    try {
      port = chrome.runtime.connect({ name: "room" });
    } catch (_) {
      S.dead = true;
      render();
      return;
    }
    port.postMessage({ draft_id: tracker.draftId, slot: tracker.slot });
    port.onDisconnect.addListener(() => {
      void chrome.runtime.lastError;
      // The worker may have posted control: absent for this port; say again who holds the seat.
      S.control = null;
      sleep(1000).then(() => {
        connect();
        refresh();
      });
    });
  }

  // ------------------------------------------------------------------ picks
  let flushing = false;
  let flushAgain = false;
  async function flush() {
    if (flushing) {
      flushAgain = true;
      return;
    }
    if (S.attached !== true || S.dead) return;
    const picks = tracker.unsent();
    if (!picks.length) return;
    flushing = true;
    const before = tracker.sent;
    try {
      const r = await call("picks", { picks });
      if (r.attached === false) S.attached = false;
      else tracker.synced(r);
    } catch (e) {
      S.error = "picks: " + e.message; // the status loop resends
    } finally {
      flushing = false;
      render();
      if (tracker.sent > before) refreshPlan();
      if (flushAgain) {
        flushAgain = false;
        flush();
      }
    }
  }

  // ------------------------------------------------------------------ events
  function emit(event) {
    outbox.push({ t: Date.now(), ...event });
    if (outbox.length > 2000) outbox.shift();
    sendEvents();
  }
  let sending = false;
  async function sendEvents() {
    if (sending || S.attached !== true || S.dead) return;
    const room = tracker.takeEvents();
    if (room.length) outbox.push(...room);
    if (!outbox.length) return;
    sending = true;
    const batch = outbox.splice(0, 200);
    let ok = false;
    try {
      await call("events", { events: batch });
      ok = true;
    } catch (e) {
      if (e.status && e.status < 500 && e.status !== 404) {
        S.error = "events dropped: " + e.message; // a batch the API rejects would block the rest
        ok = true;
      } else outbox.unshift(...batch);
    } finally {
      sending = false;
      if (ok && outbox.length) sendEvents();
    }
  }

  function controlState() {
    return S.autopickMode ? "absent" : "mirror"; // this build never drafts, so never "armed"
  }
  function reportControl() {
    const state = controlState();
    if (state === S.control) return;
    S.control = state;
    const event = { type: "control", state, slot: tracker.slot, mode: S.mode };
    if (state === "absent") event.reason = S.autoReason || "autopick";
    emit(event);
  }

  // ------------------------------------------------------------------ socket frames
  window.addEventListener("message", (e) => {
    if (e.source !== window || !e.data || e.data[KEY] !== "page") return;
    const m = e.data;
    if (m.dir === "in") onFrame(m.data, m.t);
    else if (m.dir === "wake") {
      const resolve = wakes.get(m.id);
      if (resolve) {
        wakes.delete(m.id);
        resolve();
      }
    } else if (m.dir === "hello") S.helloSlot = m.slot;
    else if (m.dir === "ready") {
      S.worker = Boolean(m.worker);
      window.postMessage({ [KEY]: "content", dir: "replay" }, location.origin);
    }
  });

  function onFrame(text, t) {
    const out = tracker.ingest(text, t);
    if (out.picks) flush();
    if (out.landed) {
      const event = tracker.landedEvent(out.landed, { autodraft: S.autodraft === true });
      if (event) emit(event);
      const top = S.plan && S.plan.for === out.landed.overall ? S.plan.candidates[0] : null;
      S.lastMine = {
        overall: out.landed.overall,
        yid: out.landed.yid,
        how: event ? event.how : null,
        top: top ? { yid: String(top.yahoo_player_id), name: top.name } : null,
      };
      if (S.handPick === out.landed.overall) S.handPick = null;
    }
    if (out.turn !== null) refreshPlan();
    if (out.kind === "on_deck" || out.kind === "pick" || out.kind === "history") {
      sendEvents();
      render();
    }
  }

  // ------------------------------------------------------------------ plan
  let planBusy = false;
  let planAgain = false;
  async function refreshPlan() {
    if (S.attached !== true || S.dead) return;
    if (planBusy) {
      planAgain = true;
      return;
    }
    const turn = tracker.myTurnNow();
    const next = tracker.nextMine();
    if (next === null) return;
    if (turn === null && next - tracker.contiguous() - 1 > PLAN_AHEAD) return;
    planBusy = true;
    try {
      const plan = await call("plan", { wait: turn !== null ? PLAN_WAIT_S : 0 });
      for (const c of [...(plan.candidates || []), ...(plan.second || [])]) {
        names.set(String(c.yahoo_player_id), c.name);
      }
      S.plan = { ...plan, for: next, at: Date.now() };
    } catch (e) {
      S.error = "plan: " + e.message;
    } finally {
      planBusy = false;
      render();
      if (planAgain) {
        planAgain = false;
        refreshPlan();
      }
    }
  }

  // ------------------------------------------------------------------ status
  async function refresh() {
    try {
      const r = await call("status");
      S.base = r.api || S.base;
      if (!r.attached) {
        S.attached = false;
        S.room = null;
      } else {
        const first = S.attached !== true;
        S.attached = true;
        S.room = r.room;
        S.mode = r.room.mode;
        tracker.configure({ numTeams: r.room.num_teams, rounds: r.room.rounds });
        tracker.synced(r.room);
        reportControl();
        if (first || tracker.unsent().length) flush();
        sendEvents();
        if (!S.plan || !S.plan.fresh || S.plan.version !== r.room.version) refreshPlan();
      }
    } catch (_) {
      // S.api says why
    }
    report();
    render();
  }

  function report() {
    const s = tracker.snapshot();
    const top = S.plan ? (S.plan.candidates || []).slice(0, 3) : [];
    call("report", {
      tab: {
        ...s,
        attached: S.attached,
        api: S.api,
        mode: S.mode,
        control: S.control,
        session_id: S.room ? S.room.session_id : null,
        plan: S.plan
          ? { for: S.plan.for, fresh: S.plan.fresh, board: S.plan.board, top: top.map((c) => c.name) }
          : null,
        last_mine: S.lastMine,
        autodraft: S.autodraft,
        autopick_mode: S.autopickMode,
        hello_slot: S.helloSlot,
        error: S.error,
      },
    }).catch(() => {});
  }

  // ------------------------------------------------------------------ Yahoo's page
  const labelOf = (el) =>
    (el.textContent.trim() || el.getAttribute("aria-label") || el.title || "").trim();
  const autodraftButton = () =>
    [...document.querySelectorAll("button")].find((b) => /autodraft/i.test(b.textContent));
  const autodraftOn = () => {
    const b = autodraftButton();
    return b ? Boolean(b.querySelector("svg")) : null;
  };

  function onPress(e) {
    if (!e.isTrusted || !(e.target instanceof Element)) return;
    const el = e.target.closest("button, a, [role=button]");
    if (!el || el.closest("#pickandroll-strip")) return;
    const label = labelOf(el);
    if (/autodraft/i.test(label)) S.autodraftClickAt = Date.now();
    else if (/^draft\b/i.test(label) && tracker.noteManual(Date.now(), label.slice(0, 40)) !== null) {
      render();
    }
  }
  document.addEventListener("pointerdown", onPress, true);
  document.addEventListener("click", onPress, true);

  // Yahoo's Autodraft switch. While it is on Yahoo picks for the seat, reported as control
  // absent. Only a flip Yahoo makes (a missed pick puts the seat into autopick mode) carries
  // reason "autopick", which G5 counts; on at entry or by a trusted click is not a flip. Off
  // again restores control.
  function watchYahoo() {
    const on = autodraftOn();
    const was = S.autodraft;
    S.autodraft = on;
    if (on === null || was === on) return;
    if (was === null) {
      emit({ type: "note", what: "autodraft switch seen", on });
      if (!on) return;
      S.autoReason = "autodraft at entry";
    } else if (on) {
      const byHand = Date.now() - S.autodraftClickAt < BY_HAND_MS;
      S.autoReason = byHand ? "autodraft by hand" : "autopick";
      emit({ type: "note", what: byHand ? "autodraft on by hand" : "autodraft on by Yahoo" });
    } else {
      S.autoReason = null;
      emit({ type: "note", what: "autodraft off" });
    }
    S.autopickMode = on;
    reportControl();
    render();
  }
  // The "put into autopick mode" banner, for when the switch is not where we look for it.
  const banner = new MutationObserver((records) => {
    for (const r of records) {
      for (const n of r.addedNodes) {
        const text = n.nodeType === 1 || n.nodeType === 3 ? n.textContent || "" : "";
        if (text.length < 400 && /autopick mode/i.test(text) && !S.autopickMode) {
          S.autopickMode = true;
          S.autoReason = "autopick";
          emit({ type: "note", what: "autopick banner", text: text.trim().slice(0, 120) });
          reportControl();
          render();
          return;
        }
      }
    }
  });

  // ------------------------------------------------------------------ strip
  const STRIP = "pickandroll-strip";
  const TONES = { ok: "#2f9e6a", warn: "#c98a1b", bad: "#c0392b", idle: "#5b6b8c" };
  let compact = false;

  function mountStrip() {
    if (document.getElementById(STRIP) || !document.body) return;
    const el = document.createElement("div");
    el.id = STRIP;
    el.setAttribute("role", "status");
    el.setAttribute("aria-label", "pickandroll status");
    el.style.cssText =
      "position:fixed;left:8px;bottom:8px;z-index:2147483646;max-width:min(560px,90vw);" +
      "background:rgba(14,16,28,.95);color:#e6edf7;font:12px/1.45 -apple-system,system-ui,sans-serif;" +
      "padding:6px 10px 6px 12px;border-radius:8px;border-left:4px solid #5b6b8c;" +
      "box-shadow:0 2px 10px rgba(0,0,0,.35)";
    const line = (k) => {
      const d = document.createElement("div");
      d.dataset.k = k;
      return d;
    };
    el.append(line("l1"), line("l2"), line("l3"));
    const hand = document.createElement("button");
    hand.type = "button";
    hand.dataset.k = "hand";
    hand.hidden = true;
    hand.setAttribute("aria-label", "pickandroll: I will make my next pick by hand");
    hand.style.cssText =
      "margin-top:4px;font:inherit;color:#e6edf7;background:#2a3350;border:1px solid #4a5a85;" +
      "border-radius:5px;padding:1px 8px;cursor:pointer";
    hand.addEventListener("click", (e) => {
      if (!e.isTrusted) return;
      const k = tracker.nextMine();
      S.handPick = S.handPick === k ? null : k;
      emit({ type: "note", what: S.handPick ? "hand pick" : "hand pick cancelled", overall: k });
      render();
    });
    el.append(hand);
    el.firstChild.addEventListener("click", () => {
      compact = !compact;
      render();
    });
    document.body.appendChild(el);
    render();
  }

  function nameOf(yid) {
    return names.get(String(yid)) || `#${yid}`;
  }

  function render() {
    try {
      draw();
    } catch (e) {
      S.error = "strip: " + e.message; // the strip must never stop the mirror
    }
  }

  function draw() {
    const el = document.getElementById(STRIP);
    if (!el) return;
    const s = tracker.snapshot();
    const [l1, l2, l3] = ["l1", "l2", "l3"].map((k) => el.querySelector(`[data-k=${k}]`));
    const hand = el.querySelector("[data-k=hand]");
    let tone = "idle";
    let head;
    if (S.dead) {
      head = "pickandroll: the extension was reloaded. Reload this tab to reconnect.";
      tone = "bad";
    } else if (S.api === "down") {
      head = `pickandroll: API not reachable${S.base ? " at " + S.base : ""} · room has ${s.last} picks (kept)`;
      tone = "bad";
    } else if (S.attached === false) {
      head = `pickandroll: room ${tracker.draftId} is not attached. Attach a session in the side panel · ${s.last} picks so far (kept)`;
      tone = "warn";
    } else if (S.attached === null) {
      head = "pickandroll: connecting…";
    } else {
      const mode = S.autopickMode
        ? "YAHOO AUTOPICK ON"
        : S.mode === "autopilot"
          ? "MIRROR (armed in the API; this build does not draft)"
          : "MIRROR";
      const sync =
        s.behind === 0
          ? `synced ${s.sent}/${s.last}`
          : `behind ${s.behind} (${s.sent}/${s.last})` + (s.gap ? ` · waiting for #${s.gap}` : "");
      head = `pickandroll · ${mode} · ${sync}`;
      tone = S.autopickMode || s.behind > 2 ? "bad" : s.behind ? "warn" : "ok";
    }
    l1.textContent = head;
    el.style.borderLeftColor = TONES[tone];

    let mine = "";
    if (S.attached === true && s.next_mine !== null) {
      const away = s.next_mine - s.contiguous - 1;
      mine = s.my_turn !== null ? `YOUR PICK #${s.my_turn}` : `your pick #${s.next_mine} in ${away}`;
      if (S.handPick === s.next_mine) mine += " · by hand";
      if (S.plan && S.plan.for === s.next_mine) {
        const top = (S.plan.candidates || []).slice(0, 3).map((c) => c.name);
        const state = S.plan.fresh ? "fresh" : `board ${S.plan.board ?? "-"}, solving`;
        mine += ` · plan: ${top.join(", ") || "-"} (${state})`;
      }
    } else if (S.attached === true) mine = "roster full";
    l2.textContent = mine;
    l2.hidden = compact || !mine;

    let last = "";
    if (S.lastMine) {
      const m = S.lastMine;
      last = `last pick #${m.overall}: ${nameOf(m.yid)}`;
      if (m.top) last += m.top.yid === m.yid ? " = plan top" : ` (plan top ${m.top.name})`;
      if (m.how) last += ` · ${m.how}`;
    }
    l3.textContent = last;
    l3.hidden = compact || !last;

    hand.hidden = compact || S.mode !== "autopilot" || S.attached !== true;
    hand.textContent = S.handPick ? `Hand pick #${S.handPick}: on (click to cancel)` : "Hand pick next";
  }

  // ------------------------------------------------------------------ start
  window.postMessage({ [KEY]: "content", dir: "replay" }, location.origin);
  connect();
  every(STATUS_EVERY_MS, refresh);
  every(WATCH_EVERY_MS, async () => {
    if (document.body) watchYahoo();
  });
  every(HEARTBEAT_EVERY_MS, async () => {
    const s = tracker.snapshot();
    if (S.attached === true) {
      emit({
        type: "heartbeat",
        vis: document.visibilityState,
        last: s.last,
        sent: s.sent,
        on_deck: s.on_deck ? [s.on_deck.overall, s.on_deck.slot] : null,
        autodraft: S.autodraft,
        frames: s.frames,
        worker: S.worker,
      });
    }
  });
  const onReady = () => {
    mountStrip();
    banner.observe(document.body, { childList: true, subtree: true });
  };
  if (document.body) onReady();
  else document.addEventListener("DOMContentLoaded", onReady, { once: true });
})();
