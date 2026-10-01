// Extension Tier 1 harness (docs/YAHOO_SYNC.md §5) for the browser pane. Served from the repo
// root on localhost; the pickandroll API must be running. It
//   1. puts a stand-in WebSocket and a stand-in chrome.* on the page,
//   2. loads the extension's own scripts: worker.js (its message handlers answer the stand-in
//      chrome.runtime), page.js (wraps the WebSocket), lib/*.js and content.js,
//   3. creates a session from the newest bbm_projections file and attaches the room through
//      the worker's "attach" op, as the side panel does,
//   4. plays a recorded room (tests/fixtures/rooms/<fixture>.csv) as Yahoo frames: D| when a
//      pick goes on the clock, 0| when it lands, X|29 + 5|slot before my picks (Yahoo picking
//      for an Autodraft seat), at the recorded pace divided by ``speed``,
//   5. waits for the session to catch up and shows the room's status and scorecard.
// Results land in window.__harness.
(async () => {
  "use strict";
  const q = new URLSearchParams(location.search);
  const speed = Number(q.get("speed") || 10);
  const slot = Number(q.get("slot") || 1);
  const fixture = q.get("fixture") || "2515267";
  const flip = q.get("flip") === "1";
  const draftId = q.get("draft") || `ext-${fixture}-${Date.now().toString(36)}`;
  const API = (q.get("api") || "http://localhost:8000").replace(/\/+$/, "");
  const out = (window.__harness = { draftId, done: false, error: null, log: [] });
  const logEl = document.getElementById("log");
  const log = (s) => {
    out.log.push(s);
    logEl.textContent = out.log.slice(-25).join("\n");
  };
  // Pacing runs on a worker's timer: the pane may be hidden, which throttles page timers.
  const pacer = new Worker(
    URL.createObjectURL(new Blob(["onmessage=(e)=>setTimeout(()=>postMessage(e.data.id),e.data.ms)"])),
  );
  const pending = new Map();
  let nextId = 0;
  pacer.onmessage = (e) => {
    pending.get(e.data)();
    pending.delete(e.data);
  };
  const sleep = (ms) =>
    new Promise((r) => {
      pending.set(++nextId, r);
      pacer.postMessage({ id: nextId, ms });
    });
  const load = (src) =>
    new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src + (src.includes("?") ? "&" : "?") + "v=" + Date.now(); // never a cached copy
      s.onload = resolve;
      s.onerror = () => reject(new Error("could not load " + src));
      document.head.appendChild(s);
    });
  async function http(path, opts = {}) {
    const r = await fetch(API + path, {
      method: opts.method || "GET",
      headers: opts.body ? { "Content-Type": "application/json" } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    const j = await r.json().catch(() => null);
    if (!r.ok) throw new Error(`${path}: ${r.status} ${JSON.stringify(j).slice(0, 200)}`);
    return j;
  }

  try {
    // ---- 1. stand-ins
    class FakeSocket extends EventTarget {
      constructor(url) {
        super();
        this.url = url;
        this.readyState = 1;
        this.sent = [];
      }
      send(data) {
        this.sent.push(data);
      }
      close() {
        this.readyState = 3;
      }
      emit(text) {
        this.dispatchEvent(new MessageEvent("message", { data: text }));
      }
    }
    window.WebSocket = FakeSocket;

    const { chrome: fakeChrome, store } = window.makeFakeChrome();
    Object.defineProperty(window, "chrome", { value: fakeChrome, configurable: true, writable: true });
    window.importScripts = () => {};
    store.local.api = API;
    out.store = store;

    // ---- 2. the extension's scripts, on a draft-client path
    history.replaceState(null, "", `/draftclient/nba/${draftId}/${slot}`);
    await load("/extension/lib/protocol.js");
    await load("/extension/worker.js");
    await load("/extension/page.js");
    await load("/extension/lib/room.js");
    await load("/extension/content.js");
    log(`loaded; draft ${draftId}, seat ${slot}, speed ${speed}`);

    // ---- 3. session + attach (the side panel's path)
    const projections = await http("/projections");
    const projection = projections.map((f) => f.file).find((f) => f.startsWith("bbm_projections"));
    if (!projection) throw new Error("no bbm_projections file in the API's data/");
    const session = await http("/sessions", {
      method: "POST",
      body: {
        projection_file: projection,
        positions_file: "positions_yahoo_31822.csv",
        adp_file: "adp_yahoo_31822.csv",
        num_teams: 12,
        my_position: slot,
        objective: q.get("objective") || "win",
        solve_ahead: true,
        time_limit: 5,
      },
    });
    out.session = session.id;
    const attach = await fakeChrome.runtime.sendMessage({
      op: "attach",
      draft_id: draftId,
      slot,
      session_id: session.id,
      num_teams: 12,
    });
    if (!attach.ok) throw new Error("attach: " + attach.error);
    log(`session ${session.id} (${projection}); room attached, ${attach.data.mapped} players mapped`);

    // ---- 4. the room
    const csv = await (await fetch(`/tests/fixtures/rooms/${fixture}.csv`, { cache: "no-store" })).text();
    const rows = csv
      .trim()
      .split(/\r?\n/)
      .slice(1)
      .map((line) => {
        const [overall, yid, , , t] = line.split(",").map((c) => c.trim());
        return { overall: Number(overall), yid, t: t ? Number(t) : null };
      });
    const times = timeline(rows);
    const owner = (k) => globalThis.PickAndRoll.pickOwner(12, k).slot;
    const ws = new window.WebSocket("wss://harness.invalid/draft");
    ws.send(`8|31822|${slot}|harness`);
    await sleep(3500); // the content script's first status call sees the room attached
    const start = performance.now();
    const at = (ms) => sleep(Math.max(0, start + ms / speed - performance.now()));
    const toggle = document.getElementById("autodraft");
    ws.emit("D|1|1|30");
    for (let i = 0; i < rows.length; i++) {
      const p = rows[i];
      await at(times[i]);
      const who = owner(p.overall);
      if (who === slot) {
        ws.emit("X|29");
        ws.emit(`5|${slot}`);
      }
      ws.emit(`0|${p.overall}|${p.yid}|${who}|X|0`);
      if (p.overall < rows.length) ws.emit(`D|${p.overall + 1}|${owner(p.overall + 1)}|30`);
      if (flip && p.overall === 30) toggle.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "svg"));
      if (flip && p.overall === 33) toggle.querySelector("svg").remove();
      if (p.overall % 12 === 0) log(`pick ${p.overall} played`);
    }
    out.played = rows.length;

    // ---- 5. results
    let status = null;
    for (let i = 0; i < 60; i++) {
      status = await http(`/rooms/${encodeURIComponent(draftId)}`);
      if (status.synced_through === rows.length) break;
      await sleep(500);
    }
    await sleep(16000); // the next status loop flushes the last client events
    const card = await http(`/rooms/${encodeURIComponent(draftId)}/fidelity`);
    const md = await (await fetch(`${API}/rooms/${encodeURIComponent(draftId)}/fidelity?format=md`)).text();
    Object.assign(out, {
      done: true,
      synced_through: status.synced_through,
      g: card.guardrails,
      d: card.diagnostics,
      counts: card.counts,
      rows: card.rows.map((r) => [r.overall, r.label, r.how]),
      markdown: md,
    });
    log(`done: synced ${status.synced_through}/${rows.length}`);
    document.getElementById("result").innerHTML = "";
    const pre = document.createElement("pre");
    pre.textContent = md;
    document.getElementById("result").appendChild(pre);
  } catch (e) {
    out.error = String((e && e.stack) || e);
    log("ERROR " + out.error);
  }

  // Milliseconds from pick 1 for every pick: recorded times where known, the median gap
  // between consecutive recorded picks elsewhere (as fidelity/replay.py does).
  function timeline(picks) {
    const known = picks.map((p, i) => [i, p.t]).filter(([, t]) => t !== null);
    const gaps = [];
    for (let j = 1; j < known.length; j++) {
      if (known[j][0] === known[j - 1][0] + 1) gaps.push(known[j][1] - known[j - 1][1]);
    }
    gaps.sort((a, b) => a - b);
    const mid = gaps.length ? (gaps[(gaps.length - 1) >> 1] + gaps[gaps.length >> 1]) / 2 : 5000;
    if (!known.length) return picks.map((_, i) => i * mid);
    const t = new Array(picks.length).fill(0);
    const [fi, ft] = known[0];
    for (let i = 0; i <= fi; i++) t[i] = ft - (fi - i) * mid;
    for (let j = 1; j < known.length; j++) {
      const [i0, a] = known[j - 1];
      const [i1, b] = known[j];
      for (let k = i0; k <= i1; k++) t[k] = a + ((b - a) * (k - i0)) / (i1 - i0);
    }
    const [li, lt] = known[known.length - 1];
    for (let k = li; k < picks.length; k++) t[k] = lt + (k - li) * mid;
    return t.map((x) => x - t[0]);
  }
})();
