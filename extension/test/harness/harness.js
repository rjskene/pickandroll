// Extension Tier 1 harness (docs/YAHOO_SYNC.md §5) for the browser pane. Served from the repo
// root on localhost; the pickandroll API must be running. It
//   1. puts a stand-in WebSocket and a stand-in chrome.* on the page,
//   2. loads the extension's own scripts: worker.js (its message handlers answer the stand-in
//      chrome.runtime), page.js (wraps the WebSocket), lib/*.js and content.js,
//   3. creates a session from the newest bbm_projections file and attaches the room through
//      the worker's "attach" op, as the side panel does,
//   4. plays a recorded room (tests/fixtures/rooms/<fixture>.csv) as Yahoo frames: D| when a
//      pick goes on the clock, 0| when it lands, X|29 + 5|slot before my picks (Yahoo picking
//      for an Autodraft seat), at the recorded pace divided by ``speed``, or one pick every
//      ``gap`` seconds (a human-pace room),
//   5. waits for the session to catch up and shows the room's status and scorecard.
// Results land in window.__harness.
(async () => {
  "use strict";
  const q = new URLSearchParams(location.search);
  const speed = Number(q.get("speed") || 10);
  const slot = Number(q.get("slot") || 1);
  const fixture = q.get("fixture") || "2515267";
  const flip = q.get("flip") === "1";
  const armedRun = q.get("armed") === "1";
  const drop = Number(q.get("drop") || 0);
  // Seconds between picks for a human-pace room (draft day), in place of the recording's times.
  const gap = Number(q.get("gap") || 0);
  // Seconds from the attach to pick 1 (the protocol attaches from the waiting room, >= 60 s).
  const lead = Number(q.get("lead") || 3.5);
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
    await load("/extension/lib/yahoo.js");
    await load("/extension/lib/drafter.js");
    await load("/extension/content.js");
    log(`loaded; draft ${draftId}, seat ${slot}, ${gap > 0 ? `a pick every ${gap} s` : `speed ${speed}`}`);

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
    // ``gap`` is wall-clock seconds; ``speed`` divides only the recording's own pace.
    const times = gap > 0 ? rows.map((_, i) => i * gap * 1000 * speed) : timeline(rows);
    const owner = (k) => globalThis.PickAndRoll.pickOwner(12, k).slot;
    const ws = new window.WebSocket("wss://harness.invalid/draft");
    ws.send(`8|31822|${slot}|harness`);

    // Armed: a stand-in for Yahoo's player table. Every candidate the drafter is served gets a
    // row with a Draft button; a click on our turn is the room's pick 300 ms later (``drop`` of
    // first clicks are lost, as Yahoo loses clicks during a re-render). A player we take that
    // the recording gives to another team later is replaced there by the one it had at our pick.
    const table = document.querySelector("#players tbody");
    const taken = new Set();
    const swap = new Map();
    const shown = new Map();
    const landed = new Set();
    const ours = {};
    let onClock = null;
    const emitPick = (k, yid) => {
      ws.emit(`0|${k}|${yid}|${owner(k)}|X|0`);
      taken.add(String(yid));
      landed.add(k);
      const row = shown.get(String(yid));
      if (row) row.remove();
    };
    const resolve = (yid) => {
      let y = String(yid);
      for (let n = 0; taken.has(y) && swap.has(y) && n < 20; n++) y = swap.get(y);
      return y;
    };
    const addRows = (cands) => {
      for (const c of cands || []) {
        const yid = String(c.yahoo_player_id);
        if (shown.has(yid) || taken.has(yid)) continue;
        const tr = document.createElement("tr");
        const td1 = document.createElement("td");
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = "Draft";
        b.dataset.yid = yid;
        td1.appendChild(b);
        const td2 = document.createElement("td");
        const img = document.createElement("img");
        img.setAttribute("src", `/extension/test/harness/headshots/${yid}.png`);
        img.alt = "";
        img.hidden = true;
        td2.append(img, `${c.ini}. ${c.last} ${c.team} - ${c.why || ""}`);
        tr.append(td1, td2);
        table.appendChild(tr);
        shown.set(yid, tr);
      }
    };
    if (armedRun) {
      const send = fakeChrome.runtime.sendMessage;
      fakeChrome.runtime.sendMessage = async (msg) => {
        const r = await send(msg);
        if (msg.op === "plan" && r && r.ok) {
          addRows(r.data.candidates);
          addRows(r.data.second);
        }
        return r;
      };
      table.addEventListener("click", (e) => {
        const b = e.target.closest("button[data-yid]");
        const k = onClock && onClock.slot === slot ? onClock.overall : null;
        if (!b || k === null || k > rows.length || landed.has(k) || taken.has(b.dataset.yid)) return;
        out.clicks = (out.clicks || 0) + 1;
        if (drop && !b.dataset.dropped && Math.random() < drop) {
          b.dataset.dropped = "1";
          out.dropped = (out.dropped || 0) + 1;
          return;
        }
        const yid = b.dataset.yid;
        setTimeout(() => {
          if (landed.has(k) || taken.has(yid)) return;
          ours[k] = yid;
          emitPick(k, yid);
          // The draft ends with the fixture's last pick: nothing goes on the clock after it.
          if (k < rows.length) {
            ws.emit(`D|${k + 1}|${owner(k + 1)}|30`);
            onClock = { overall: k + 1, slot: owner(k + 1) };
          } else onClock = null;
        }, 300);
      });
      const r = await fakeChrome.runtime.sendMessage({ op: "mode", draft_id: draftId, mode: "autopilot" });
      if (!r.ok) throw new Error("arm: " + r.error);
      log("armed");
    }

    await sleep(lead * 1000); // the content script's first status call sees the room attached
    let anchorT = performance.now();
    let anchorI = 0;
    const at = (i) => sleep(Math.max(0, anchorT + (times[i] - times[anchorI]) / speed - performance.now()));
    const toggle = document.getElementById("autodraft");
    ws.emit("D|1|1|30");
    onClock = { overall: 1, slot: 1 };
    out.expired = 0;
    for (let i = 0; i < rows.length; i++) {
      const p = rows[i];
      const k = p.overall;
      const who = owner(k);
      if (armedRun && who === slot) {
        const deadline = performance.now() + 30000; // Yahoo's clock runs in real time
        while (!landed.has(k) && performance.now() < deadline) await sleep(100);
        if (!landed.has(k)) {
          ws.emit("X|29");
          ws.emit(`5|${slot}`);
          ours[k] = resolve(p.yid);
          emitPick(k, ours[k]);
          out.expired++;
        } else if (ours[k] !== String(p.yid)) swap.set(ours[k], String(p.yid));
        anchorT = performance.now();
        anchorI = i;
      } else {
        await at(i);
        if (who === slot) {
          ws.emit("X|29");
          ws.emit(`5|${slot}`);
        }
        emitPick(k, resolve(p.yid));
      }
      if (k < rows.length && !(armedRun && who === slot && onClock.overall === k + 1)) {
        ws.emit(`D|${k + 1}|${owner(k + 1)}|30`);
        onClock = { overall: k + 1, slot: owner(k + 1) };
      }
      if (flip && k === 30) toggle.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "svg"));
      if (flip && k === 33) toggle.querySelector("svg").remove();
      if (k % 12 === 0) log(`pick ${k} played`);
    }
    out.ours = ours;
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
      compliance: card.compliance,
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
