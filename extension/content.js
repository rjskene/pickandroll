// pickandroll, content half (isolated world). Mirrors the Yahoo draft room into the pickandroll
// API through the service worker: every pick the room's socket sends (page.js hands them over),
// the pick on the clock, and the fidelity events of docs/YAHOO_SYNC.md §4. It shows a status
// strip in the page. Only when the user has armed the room (mode "autopilot", set from the side
// panel or the web app) does it draft for the seat, through lib/drafter.js; otherwise it never
// clicks anything in Yahoo.
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
    drafting: null, // what the drafter is doing on an armed turn
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
  /** ``signal``: aborting it cancels the request in the service worker (a /plan hold of a turn
   * that a newer one superseded); the call then fails with status 499. */
  async function call(op, body = {}, signal = null) {
    if (S.dead) throw new Error("extension reloaded");
    let r;
    let hold = null;
    const cancel = () => chrome.runtime.sendMessage({ op: "cancel", hold }).catch(() => {});
    if (signal) {
      if (signal.aborted) throw Object.assign(new Error("cancelled"), { status: 499 });
      hold = `${Date.now().toString(36)}.${Math.random().toString(36).slice(2, 10)}`;
      signal.addEventListener("abort", cancel, { once: true });
    }
    try {
      r = await chrome.runtime.sendMessage({
        op,
        draft_id: tracker.draftId,
        slot: tracker.slot,
        ...body,
        ...(hold ? { hold } : {}),
      });
    } catch (e) {
      if (/context invalidated/i.test(String(e && e.message))) {
        S.dead = true;
        render();
      }
      throw e;
    } finally {
      if (signal) signal.removeEventListener("abort", cancel);
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
    if (S.autopickMode) return "absent";
    return S.mode === "autopilot" ? "armed" : "mirror";
  }
  // The user armed the room; the seat is drafted by us only while Yahoo's Autodraft is off.
  const userArmed = () => S.attached === true && !S.dead && S.mode === "autopilot";
  const armed = () => userArmed() && !S.autopickMode;
  function reportControl() {
    const state = controlState();
    if (state === S.control) return;
    S.control = state;
    const event = { type: "control", state, slot: tracker.slot, mode: S.mode };
    if (state === "absent") event.reason = S.autoReason || "autopick";
    emit(event);
  }

  // ------------------------------------------------------------------ socket frames
  let pageReady = false; // the page half's "ready" was handled (it can come twice)
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
    else if (m.dir === "ready" && !pageReady) {
      pageReady = true;
      S.worker = Boolean(m.worker);
      window.postMessage({ [KEY]: "content", dir: "replay" }, location.origin);
    }
  });
  // The page half announces itself once at load; when it ran first (the order of the two worlds
  // at document_start is not guaranteed, and the harness loads it first) that announcement is
  // gone, so ask. Without it every timer here is a DOM timer, which a hidden tab holds back
  // to once a minute after five minutes (harness pick 145, 2026-10-01).
  window.postMessage({ [KEY]: "content", dir: "ping" }, location.origin);

  function onFrame(text, t) {
    const out = tracker.ingest(text, t);
    // The pick goes out before this frame's turn asks for its plan, so the API's hold for the
    // turn's board is short; the board contract (drafter.js) keeps it correct either way.
    if (out.picks) flush();
    if (out.landed) {
      const event = tracker.landedEvent(out.landed, { autodraft: autodraftOn() === true });
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
    if (out.turn !== null) {
      if (armed()) takeTurn(out.turn, "on deck");
      else refreshPlan();
    }
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
      drafter.probeRound = /^\d+$/.test(String(r.probe_round)) ? Number(r.probe_round) : null;
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
  const tableRows = () => [...document.querySelectorAll("tr")].filter((r) => r.querySelector("td"));
  const rowId = (r) => {
    const img = r.querySelector("img");
    return img ? PR.imageId(img.getAttribute("src")) : null;
  };
  const rowDraftButton = (row) =>
    [...row.querySelectorAll("button, a, [role=button]")].find((b) => PR.isDraftLabel(labelOf(b)));
  function findRow(c) {
    const rows = tableRows();
    const i = PR.matchRow(
      rows.map((r) => ({ id: rowId(r), text: r.textContent })),
      c,
    );
    return i >= 0 ? rows[i] : null;
  }
  function scroller() {
    let el = document.querySelector("tr td");
    while (el && el !== document.body) {
      const cs = getComputedStyle(el);
      if (/(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 20) return el;
      el = el.parentElement;
    }
    return document.scrollingElement;
  }
  async function nudge() {
    const sc = scroller();
    const top = sc.scrollTop;
    sc.scrollTop = top + 40;
    await sleep(120);
    sc.scrollTop = top;
    await sleep(120);
  }
  async function scrollTo(c) {
    const sc = scroller();
    let row = findRow(c);
    for (let i = 0; !row && i < 20; i++) {
      const before = sc.scrollTop;
      sc.scrollTop = before + Math.max(300, sc.clientHeight * 0.85);
      await sleep(110);
      row = findRow(c);
      if (!row && sc.scrollTop === before) break;
    }
    if (row) {
      row.scrollIntoView({ block: "center" });
      await sleep(150);
      row = findRow(c);
    }
    return row;
  }
  const searchBox = () =>
    document.querySelector('input[type=search], input[placeholder*="earch"], input[aria-label*="earch"]');
  async function setSearch(value) {
    const box = searchBox();
    if (!box) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    box.focus();
    setter.call(box, value);
    box.dispatchEvent(new Event("input", { bubbles: true }));
    box.dispatchEvent(new Event("change", { bubbles: true }));
    await sleep(700);
    return true;
  }
  function confirmDialog() {
    const dlg = document.querySelector("[role=dialog], [role=alertdialog]");
    if (!dlg) return;
    const b = [...dlg.querySelectorAll("button")].find((x) => /^(confirm|yes|draft|ok)/i.test(x.textContent.trim()));
    if (b) b.click();
  }
  // Yahoo's queue panel ("Autodraft will pick from queue") and its Autodraft switch.
  let queuePanel = null;
  function qPanel() {
    if (queuePanel && queuePanel.isConnected && /Autodraft will pick from queue/.test(queuePanel.textContent)) {
      return queuePanel;
    }
    queuePanel =
      [...document.querySelectorAll("div, section, aside")]
        .filter(
          (e) =>
            /Autodraft will pick from queue/.test(e.textContent) &&
            (e.querySelector("li") || /queue is empty/i.test(e.textContent)) &&
            e.textContent.length < 2500,
        )
        .sort((a, b) => a.textContent.length - b.textContent.length)[0] || null;
    return queuePanel;
  }
  const qItems = () => {
    const panel = qPanel();
    return panel
      ? [...panel.querySelectorAll("li")].filter((li) => li.querySelector("button") && li.textContent.trim().length > 4)
      : [];
  };
  async function clearQueue() {
    for (let i = 0; i < 12; i++) {
      const items = qItems();
      if (!items.length) return true;
      const b = [...items[0].querySelectorAll("button")].pop();
      if (!b) break;
      b.click();
      await sleep(300);
      if (qItems().length >= items.length) break;
    }
    return qItems().length === 0;
  }
  async function starRow(row) {
    const b = row.children[0] && row.children[0].querySelector("button");
    if (!b) return false;
    b.click();
    await sleep(350);
    return true;
  }
  // Exactly this one player in Yahoo's queue, checked against the queue's text.
  async function queueOnly(c) {
    const k = tracker.myTurnNow();
    await clearQueue();
    let row = findRow(c) || (await scrollTo(c));
    if (!row) return { ok: false, msg: "no row" };
    for (let attempt = 0; attempt < 2; attempt++) {
      await starRow(row);
      const items = qItems();
      if (items.length === 1 && PR.fold(items[0].textContent).includes(PR.fold(c.last))) return { ok: true };
      if (k !== null && tracker.picks.has(k)) return { ok: true }; // on my turn the star drafts
      await clearQueue();
      await nudge();
      row = findRow(c) || (await scrollTo(c));
      if (!row) return { ok: false, msg: "row vanished" };
    }
    await clearQueue();
    return { ok: false, msg: "queue check failed" };
  }
  const inQueue = (li, p) => PR.fold(li.textContent).includes(PR.fold(p.last));
  const labelsOf = (b) => [b.getAttribute("aria-label"), b.title, b.textContent];
  /** The queue panel's entries as text, or null when the panel cannot be read. */
  const panelText = () => (qPanel() ? qItems().map((li) => li.textContent.replace(/\s+/g, " ").trim().slice(0, 40)) : null);
  // The back-to-back exception (user, 2026-10-02): ``c2``, my next pick's player, behind ``c``
  // in the queue. Only a control labelled as the queue's is clicked: on my turn a row's
  // first-cell button can be its Draft button (drafts 5-6), which would draft ``c2`` for this
  // pick, and an unlabelled one is refused too. Autodraft takes the queue's head, so the panel
  // must then read exactly ``c``, ``c2``. On any failure the queue is put back to ``c`` alone
  // (``single``).
  async function queueAlso(c2, c) {
    const fail = async (msg) => ({ ok: false, msg, single: await queueOnly(c) });
    if (!qPanel()) return fail("queue panel unreadable");
    const items = qItems();
    if (items.length !== 1 || !inQueue(items[0], c)) return fail("the queue is not this pick's player alone");
    const row = findRow(c2) || (await scrollTo(c2));
    if (!row) return fail("no row");
    const b = [...row.querySelectorAll("button, [role=button]")].find((x) => PR.isQueueControl(labelsOf(x)));
    if (!b) return fail("no control labelled as the queue's");
    b.click();
    await sleep(350);
    if (!qPanel()) return fail("queue panel unreadable");
    const now = qItems();
    if (now.length === 2 && inQueue(now[0], c) && inQueue(now[1], c2)) return { ok: true };
    return fail(`queue reads ${now.length} entries, not ${c.last} then ${c2.last}`);
  }
  // The queue probe: what the star (a row's first-cell button, the one queueOnly uses) does on
  // my turn. Either outcome is harmless: it queues ``c``, or it drafts ``c``, the pick wanted.
  async function probeQueue(c) {
    const k = tracker.myTurnNow();
    const row = findRow(c) || (await scrollTo(c));
    const b = row && row.children[0] && row.children[0].querySelector("button");
    if (!b) return { outcome: "no_control", panel: panelText(), control: null };
    const control = labelsOf(b).filter(Boolean).join(" | ").replace(/\s+/g, " ").slice(0, 60);
    b.click();
    // A registered click confirms within ~400 ms; give it up to the re-click gap (1.8 s).
    const drafted = () => k !== null && tracker.picks.has(k);
    const queued = () => qItems().some((li) => inQueue(li, c));
    for (let i = 0; i < 7 && !drafted() && !queued(); i++) await sleep(i ? 250 : 400);
    const panel = panelText();
    if (drafted()) return { outcome: "drafted", panel, control };
    if (queued()) return { outcome: "queued", panel, control };
    return { outcome: "failed", panel, control };
  }
  async function setAutodraft(on) {
    const b = autodraftButton();
    if (!b) return null;
    if (Boolean(b.querySelector("svg")) !== on) {
      b.click();
      await sleep(350);
    }
    return Boolean(b.querySelector("svg"));
  }
  const yahoo = {
    draftable: () => tableRows().some((r) => rowDraftButton(r)),
    find: findRow,
    scrollTo,
    async search(c) {
      if (!(await setSearch(c.last))) return null;
      return findRow(c);
    },
    async click(row, c) {
      const b = rowDraftButton(row);
      if (!b) return "none";
      if (!PR.labelNames(labelOf(b), c)) return "mismatch";
      b.click();
      await sleep(400);
      confirmDialog();
      return "clicked";
    },
    nudge,
    queueOnly,
    queueAlso,
    probeQueue,
    setAutodraft,
    autodraftOn: () => autodraftOn(),
    clearQueue,
    async reset() {
      const box = searchBox();
      if (box && box.value) await setSearch("");
      scroller().scrollTop = 0;
    },
  };
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
    else if (/^draft\b/i.test(label)) {
      const k = tracker.noteManual(Date.now(), label.slice(0, 40));
      if (k !== null) {
        drafter.handPick(k); // the turn touches the page no more
        render();
      }
    }
  }
  document.addEventListener("pointerdown", onPress, true);
  document.addEventListener("click", onPress, true);

  // ------------------------------------------------------------------ armed turns
  const drafter = new PR.Drafter({
    tracker,
    dom: yahoo,
    plan: async (wait, board, signal) => {
      const plan = await call("plan", { wait, board }, signal);
      for (const c of [...(plan.candidates || []), ...(plan.second || [])]) {
        names.set(String(c.yahoo_player_id), c.name);
      }
      S.plan = { ...plan, for: tracker.nextMine(), at: Date.now() };
      render();
      return plan;
    },
    emit,
    sleep,
    now: () => Date.now(),
    log: (line) => {
      S.drafting = line;
      render();
    },
  });
  // Each of my turns starts from its own turn frame (or the guard, if that frame was missed);
  // starting it stops the previous turn wherever it is. Nothing waits for a turn to settle.
  function takeTurn(k, why) {
    if (!armed() || S.handPick === k || drafter.tried.has(k)) return;
    S.drafting = `taking #${k}`;
    render();
    drafter.turn(k).then((out) => {
      if (drafter.current && drafter.current.k === k) S.drafting = null;
      if (out) {
        const { result, attempts, fresh, board, waited_ms, ms, stopped } = out;
        emit({ type: "note", what: "turn", overall: k, why, result, attempts, fresh, board, waited_ms, ms, stopped });
      }
      render();
    });
  }
  // Once a second while armed: start a turn the on-deck frame did not start, and between turns
  // undo Yahoo's flip into autopick mode and keep its queue empty (we queue only for the pick
  // on the clock). A switch the user turned on by hand is theirs and left alone.
  async function guard() {
    if (!userArmed()) return;
    const k = tracker.myTurnNow();
    if (k !== null) {
      takeTurn(k, "guard"); // no-op once the turn frame started it
      return;
    }
    if (drafter.busy) return; // a turn still settling owns the page
    if (/^your turn/i.test(document.title)) {
      const n = tracker.nextMine();
      if (n !== null && n === tracker.contiguous() + 1) takeTurn(n, "title");
      return;
    }
    if (S.autopickMode && S.autoReason === "autopick" && autodraftOn() === true) {
      await setAutodraft(false);
      emit({ type: "note", what: "autodraft off by pickandroll" });
    }
    if (qItems().length) await clearQueue();
  }

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
      const mode = S.autopickMode ? "YAHOO AUTOPICK ON" : S.mode === "autopilot" ? "ARMED" : "MIRROR";
      const sync =
        s.behind === 0
          ? `synced ${s.sent}/${s.last}`
          : `behind ${s.behind} (${s.sent}/${s.last})` + (s.gap ? ` · waiting for #${s.gap}` : "");
      head = `pickandroll · ${mode} · ${sync}`;
      tone = S.autopickMode || s.behind > 2 ? "bad" : s.behind ? "warn" : "ok";
    }
    if (S.drafting && S.attached === true) head += ` · ${S.drafting}`;
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
  // The moment the draft client loaded (G6 counts from here); it waits in the outbox until the
  // room is attached.
  emit({ type: "note", what: "entered", visible: document.visibilityState });
  window.postMessage({ [KEY]: "content", dir: "replay" }, location.origin);
  connect();
  every(STATUS_EVERY_MS, refresh);
  every(WATCH_EVERY_MS, async () => {
    if (!document.body) return;
    watchYahoo();
    await guard();
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
