// Season Sim Lab: the Screen tab shows a screen as it is played (PR live screen). Every figure is
// in the screen's view (src/pickandroll/sim/lab/screen_view.py); this file only draws it, moves
// the playhead along the screen's story and asks for the view again while the screen is in play.
(function () {
  "use strict";
  const SPEEDS = [1, 3, 10];
  // The whole story plays in this many seconds at 1x; a pause between pieces passes faster.
  const STORY = 40, RUSH = 6, POLL = 15;
  const S = { M: null, list: [], name: null, v: null, error: null, t: 0, live: true, playing: false, speed: 1, raf: 0, last: 0, poll: 0, el: null, pick: null, key: "" };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
  const isNum = (v) => typeof v === "number" && isFinite(v);
  const when = (t) => (t ? new Date(t).toLocaleString("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " CT" : "n/a");
  const at = (off) => (S.v && S.v.story.start && isNum(off) ? when(new Date(Date.parse(S.v.story.start) + off * 1000).toISOString()) : "n/a");
  const span = (sec) => (!isNum(sec) ? "n/a" : sec < 3600 ? Math.round(sec / 60) + " min" : (sec / 3600).toFixed(1) + " h");
  const signed = (v, d) => (!isNum(v) ? "n/a" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(d));
  const screens = (M) => ((M && M.runs) || []).filter((r) => r.kind === "screen");

  // ------------------------------------------------------------------ the board at a moment
  function spanAt(key, t) {
    const L = S.v.story.length;
    return S.v.story.spans.find((s) => s.key === key && s.from <= t && (s.to == null ? t <= L : t < s.to)) || null;
  }
  function markAt(r, t) {
    if (r.mark === "not played") return "not played";
    if (isNum(r.landed) && r.landed <= t) return "played";
    return spanAt(r.key, t) ? "in play" : "waiting";
  }
  // How far the pair in play has come at t: the screen's own estimate, never over its whole.
  function progressAt(sp, t) {
    const elapsed = Math.max(0, t - sp.from), est = sp.estimate;
    if (!isNum(est) || est <= 0) return { share: null, over: false, words: "no estimate in the record for this pair" };
    const over = elapsed > est, share = Math.min(1, elapsed / est);
    return { share, over, words: over ? "longer than estimated" : `about ${Math.floor(100 * share)}% of its estimate` };
  }
  const pieceAt = (t) => S.v.story.pieces.find((p) => p.from <= t && (p.to == null ? true : t <= p.to)) || null;
  const pauseAt = (t) => S.v.story.pauses.find((p) => p.from <= t && (p.to == null || t < p.to)) || null;
  function stateAt(t) {
    const v = S.v, p = pieceAt(t);
    if (!v.story.pieces.length) return "not started";
    if (p) return p.to == null ? `piece ${p.index + 1} is open` : `piece ${p.index + 1}`;
    if (pauseAt(t)) return "paused between pieces";
    return v.state.state === "finished" && t >= v.story.length ? "finished" : "between pieces";
  }

  // ------------------------------------------------------------------ the tab's parts
  const pickLine = (r) => `${r.name} · ${r.live.state} · ${r.live.played} played, ${r.live.left} left`;
  function picker() {
    return `<section class="panel"><div class="sv-pick"><span class="k">Screen</span>
      <select id="sc-pick" data-sc="pick" aria-label="the screen to show">${S.list.map((r) => `<option value="${esc(r.folder)}"${r.folder === S.name ? " selected" : ""}>${esc(pickLine(r))}</option>`).join("")}</select></div></section>`;
  }
  function head() {
    const v = S.v, w = v.world;
    const kept = v.kept ? `<p class="sv-err">The record could not be read at ${esc(when(v.kept.at))} (${esc(v.kept.why)}): the view shows the last good read.</p>` : "";
    return `<section class="panel"><p class="sc-state"><span class="badge ${v.state.state === "in play" ? "ok" : ""}">${esc(v.state.state)}</span> ${esc(v.state.words)}</p>${kept}
      <p class="sub">${esc(v.league || "")} · ${esc(v.measure_label)} · ${w.seasons.map(esc).join(", ") || "no season"} · ${esc(w.forecasters)} · seed ${esc(w.seed)} · ${esc(w.paths)} paths a pair · the baseline's knobs ${esc(v.baseline.knobs_from)} · screen version ${esc(v.screen_version)}</p>
      <details class="same"><summary>The screen's rule</summary><p class="sub">${esc(v.rule || "not recorded")}</p></details></section>`;
  }
  function bar() {
    const v = S.v, L = Math.max(v.story.length, 1);
    return `<section class="panel sv-sticky"><div class="sv-bar"><button class="btn" id="sc-play" data-sc="play">Play</button>
        ${v.story.now == null ? "" : `<button class="btn ghost" id="sc-now" data-sc="now">Now</button>`}<div class="sv-clock" id="sc-clock"></div>
        <input type="range" id="sc-scrub" data-sc="scrub" min="0" max="${L}" step="any" value="0" aria-label="the moment of the screen's story">
        <span class="seg">${SPEEDS.map((x) => `<button id="sc-sp${x}" data-sc="speed" data-v="${x}">${x}×</button>`).join("")}</span></div>
        <div class="sc-track" id="sc-track">${track()}</div><p class="sv-err" id="sc-err"></p></section>`;
  }
  function track() {
    const v = S.v, L = Math.max(v.story.length, 1), x = (o) => (100 * Math.min(L, Math.max(0, o))) / L;
    const pcs = v.story.pieces.map((p) => `<i class="pc${p.to == null ? " open" : ""}" style="left:${x(p.from)}%;width:${Math.max(0.4, x(p.to == null ? L : p.to) - x(p.from))}%" title="piece ${p.index + 1}"></i>`).join("");
    const gaps = v.story.pauses.map((p) => `<i class="ps" style="left:${x(p.from)}%;width:${Math.max(0.4, x(p.to == null ? L : p.to) - x(p.from))}%"></i>`).join("");
    const lands = v.story.landings.map((l) => `<i class="ld" style="left:${x(l.t)}%"></i>`).join("");
    return `${gaps}${pcs}${lands}<i class="hd" id="sc-head"></i>`;
  }
  function clockPanel() {
    const v = S.v;
    return `<section class="panel"><span class="k">The clock</span><div id="sc-now-box"></div>
      <p class="sub">${esc(v.counts.played)} played · ${esc(v.counts.left)} left · ${esc(v.counts.not_played)} not played · ${esc(v.counts.rows)} rows</p>
      ${v.work_left == null ? "" : `<p class="sc-left">Work left: about ${esc(span(v.work_left))} of play <small>(an estimate${v.unknown_estimates ? `; ${esc(v.unknown_estimates)} pair(s) with none` : ""})</small>, in pieces.${v.unbroken_end ? ` Played on without a pause it would end about ${esc(when(v.unbroken_end))}.` : ""}</p>`}
      <p class="sub">${esc(v.pieces_words)}</p>
      ${v.plan ? `<p class="sc-plan"><b>The plan:</b> ${esc(v.plan)}</p>` : `<p class="sub">No plan for the pieces in the notes.</p>`}
      <ul class="sc-pieces">${v.story.pieces.map((p, i) => `<li>${esc(v.piece_words[i])} <span class="sub">· from ${esc(when(p.started_at))}${p.finished_at ? ` to ${esc(when(p.finished_at))}` : ""} · ${esc(p.workers)} worker(s)</span></li>`).join("")}</ul>
      <p class="sub">${esc(v.outside_words)}</p></section>`;
  }
  function cell(c, many) {
    const side = c.clears ? c.side : "none";
    return `<span class="sc-cell ${esc(side)}">${side === "better" ? "▲" : side === "worse" ? "▼" : "·"} ${esc(signed(c.mean, 3))} <small>± ${esc(isNum(c.se) ? c.se.toFixed(3) : "n/a")} · ${isNum(c.ratio) ? esc(Math.abs(c.ratio).toFixed(1)) + " SE" : "no SE"}${many ? " · " + esc(c.cell) : ""}</small></span>`;
  }
  function rowMark(r, t) {
    const m = markAt(r, t), on = r.key === S.pick ? " on" : "";
    const vals = r.values ? `${esc(r.values.a)} → ${esc(r.values.b)}` : "";
    let body = "";
    if (m === "played" && r.result) {
      const res = r.result;
      const verdict = res.did_nothing ? "did nothing" : res.survives ? "survives the rule" : "inside one SE";
      body = `${res.cells.map((c) => cell(c, res.cells.length > 1)).join("")}<small class="sc-v">${esc(verdict)}${res.voided ? ` · ${esc(res.voided)} path(s) voided` : ""}</small>`;
    } else if (m === "in play") {
      const p = progressAt(spanAt(r.key, t), t);
      body = `<span class="sc-prog${p.over ? " over" : ""}"><i style="width:${isNum(p.share) ? (100 * p.share).toFixed(1) : 0}%"></i></span><small>${esc(p.words)} (an estimate)</small>`;
    } else if (m === "waiting") {
      body = `<small>waiting</small>`;
    } else {
      body = `<small>${esc(r.status || "not played")}${r.why ? ": " + esc(r.why) : ""}</small>`;
    }
    return `<button class="sc-row m-${m.replace(" ", "-")}${on}" data-sc="row" data-v="${esc(r.key)}"><span class="sc-n"><b>${esc(r.override || r.nudge || r.key)}</b><small>${vals}</small></span><span class="sc-b">${body}</span></button>`;
  }
  function board(t) {
    const v = S.v, by = Object.fromEntries(v.rows.map((r) => [r.key, r]));
    return v.groups.map((g) => `<div class="sc-group"><span class="k">${esc(g.label)}</span>${g.keys.map((k) => rowMark(by[k], t)).join("")}</div>`).join("");
  }
  function boardPanel() {
    return `<section class="panel"><span class="k">The board · every row in play order, B against A on ${esc(S.v.measure_label.toLowerCase())}</span>
      <div class="sc-board" id="sc-board"></div>
      <p class="sub">▲ cleared one SE, better for the seat · ▼ cleared one SE, worse · · inside one SE. Tap a row for its two arms.</p></section>`;
  }
  const krow = (r) => `<div class="kdiff"><span>${esc(r.label)}</span><b class="ca">${esc(r.a)}</b><b class="cb">${esc(r.b)}</b></div>`;
  function pairPanel(t) {
    const v = S.v, key = S.pick || inPlayAt(t) || v.shown, r = v.rows.find((x) => x.key === key);
    if (!r) return `<section class="panel"><span class="k">The pair</span><p class="empty">No pair to show.</p></section>`;
    const a = r.arms, m = markAt(r, t);
    return `<section class="panel"><span class="k">The pair · ${esc(m)}</span>
      <div class="sv-lever"><b>${esc(r.label)}</b>${r.values ? ` <span>${esc(r.values.a)} → ${esc(r.values.b)}</span>` : ""}<small>${esc(r.nudge || "")}${r.override ? ` · ${esc(r.override)}` : ""} · ${esc(r.tier || "")} · ${esc(v.world.paths)} paths · rivals ${esc(a.opponents)}</small></div>
      <div class="kdiff kh"><span></span><b class="ca">A · ${esc(a.names.a)}</b><b class="cb">B · ${esc(a.names.b)}</b></div>
      ${a.differ.map(krow).join("") || `<p class="sub">No value differs: ${esc(r.status || "")}${r.why ? ", " + esc(r.why) : ""}.</p>`}
      ${a.both.length ? `<p class="sub sc-both">Set in both arms: ${a.both.map((x) => `${esc(x.label)} ${esc(x.value)}`).join(" · ")}</p>` : ""}
      <details class="same"><summary>${esc(a.same.length)} other knobs, the same in both arms</summary>${a.same.map(krow).join("")}</details></section>`;
  }
  function inPlayAt(t) { const r = S.v.rows.find((x) => markAt(x, t) === "in play"); return r ? r.key : null; }
  const cautions = () => `<section class="panel">${S.v.cautions.map((c) => `<p class="caution">${esc(c)}</p>`).join("")}</section>`;

  // ------------------------------------------------------------------ drawing
  function draw() {
    const v = S.v;
    if (!v || !$("sc-clock")) return;
    const L = v.story.length, t = Math.max(0, Math.min(L, S.t)), ip = inPlayAt(t);
    $("sc-clock").innerHTML = `${esc(stateAt(t))}<small>${esc(at(t))}${S.live && v.story.now != null ? " · now" : ""}</small>`;
    $("sc-scrub").value = t;
    const hd = $("sc-head");
    if (hd) hd.style.left = (L > 0 ? (100 * t) / L : 0).toFixed(2) + "%";
    const sp = ip ? spanAt(ip, t) : null, pr = sp ? progressAt(sp, t) : null;
    const key = v.rows.map((r) => markAt(r, t)[0]).join("") + "|" + (pr ? Math.floor(100 * (pr.share || 0)) : "") + "|" + S.pick;
    if (key === S.key) return;
    S.key = key;
    $("sc-board").innerHTML = board(t);
    const nb = $("sc-now-box");
    if (nb) nb.innerHTML = ip ? `<p class="sc-ip">In play: <b>${esc((v.rows.find((r) => r.key === ip) || {}).override || ip)}</b> since ${esc(at(sp.from))}, ${esc(pr.words)} <small>(an estimate)</small></p>` : `<p class="sc-ip">${esc(stateAt(t))}: no pair in play.</p>`;
    const pp = $("sc-pair");
    if (pp) pp.innerHTML = pairPanel(t);
  }
  function safeDraw() {
    try { draw(); } catch (e) { const el = $("sc-err"); if (el) el.textContent = "The view could not draw this moment: " + e.message; }
  }
  function controls() {
    const b = $("sc-play");
    if (b) b.textContent = S.playing ? "Pause" : S.v && S.t >= S.v.story.length && S.v.story.now == null ? "Replay" : "Play";
    const n = $("sc-now");
    if (n) n.className = "btn ghost" + (S.live ? " on" : "");
    for (const x of SPEEDS) { const e = $("sc-sp" + x); if (e) e.className = x === S.speed ? "on" : ""; }
  }
  function tick(ts) {
    if (!S.playing || !S.v) return;
    const L = S.v.story.length, dt = Math.max(0, Math.min(0.1, (ts - S.last) / 1000));
    S.last = ts;
    S.t += ((dt * S.speed * L) / STORY) * (pauseAt(S.t) ? RUSH : 1);
    if (S.t >= L) { S.t = L; S.playing = false; if (S.v.story.now != null) S.live = true; }
    safeDraw(); controls();
    if (S.playing) S.raf = requestAnimationFrame(tick);
  }
  function play(on) {
    cancelAnimationFrame(S.raf);
    S.playing = !!(on && S.v && S.v.story.length > 0);
    if (S.playing) {
      S.live = false;
      if (S.t >= S.v.story.length) S.t = 0;
      S.last = performance.now(); S.raf = requestAnimationFrame(tick);
    }
    controls();
  }
  function follow() { S.live = true; play(false); if (S.v) S.t = S.v.story.now != null ? S.v.story.now : S.v.story.length; S.key = ""; safeDraw(); controls(); }

  // ------------------------------------------------------------------ the tab
  function shell() {
    S.el.innerHTML = picker() + bar() + head() + `<div class="grid2"><div class="sc-col">${boardPanel()}</div><div class="sc-col">${clockPanel()}<div id="sc-pair"></div></div></div>` + cautions();
    S.key = ""; safeDraw(); controls();
  }
  function fetchView(name) {
    return fetch("/api/screen/" + encodeURIComponent(name), { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : r.text().catch(() => "").then((t) => { throw new Error(t.trim() || "the screen answered " + r.status); })));
  }
  function schedule() {
    clearInterval(S.poll); S.poll = 0;
    if (!S.v || S.v.story.now == null) return;
    S.poll = setInterval(() => { if (document.visibilityState === "visible" && S.name) refresh(); }, POLL * 1000);
  }
  // A new read of the screen in play: the board moves on; a reader at now stays at now.
  function refresh() {
    const name = S.name;
    return fetchView(name).then((v) => {
      if (S.name !== name) return;
      const first = !S.v; S.v = v; S.error = null;
      if (S.live || first) S.t = v.story.now != null ? v.story.now : v.story.length;
      shell(); schedule();
    }).catch((e) => { if (S.name !== name) return; S.error = e.message; const el = $("sc-err"); if (el && S.v) el.textContent = e.message + "; the view shows the last read"; else if (S.el) S.el.innerHTML = picker() + `<section class="panel"><p class="empty">${esc(e.message)}</p></section>`; });
  }
  function load(name) {
    stop();
    S.name = name; S.v = null; S.error = null; S.pick = null; S.live = true;
    S.el.innerHTML = picker() + `<section class="panel"><p class="sub">Reading the screen…</p></section>`;
    return refresh();
  }
  function pickDefault() {
    const open = S.list.find((r) => r.live.state === "in play") || S.list.find((r) => r.live.state === "paused between pieces");
    return (open || S.list[S.list.length - 1]).folder;
  }
  function mount(el, M) {
    S.el = el; S.M = M; S.list = screens(M);
    if (!S.list.length) {
      stop(); S.v = null; S.name = null;
      el.innerHTML = `<section class="panel"><p class="empty">No screen on the box yet. A screen is played by the screen command (the lead runs it); the lab plays nothing.</p></section>`;
      return null;
    }
    const want = S.list.some((r) => r.folder === S.name) ? S.name : pickDefault();
    if (S.v && S.name === want) { shell(); schedule(); return null; }
    return load(want);
  }
  // The model was built again while the tab is open: the picker's lines change, the view stays.
  function list(M) {
    S.M = M; S.list = screens(M);
    if (!S.el) return null;
    if (!S.list.some((r) => r.folder === S.name)) return mount(S.el, M);
    const p = $("sc-pick");
    if (p) p.innerHTML = S.list.map((r) => `<option value="${esc(r.folder)}"${r.folder === S.name ? " selected" : ""}>${esc(pickLine(r))}</option>`).join("");
    return null;
  }
  function choose(name) { if (S.name !== name) { S.name = name; S.v = null; } }
  function stop() { S.playing = false; cancelAnimationFrame(S.raf); clearInterval(S.poll); S.poll = 0; }
  function act(what, val) {
    if (what === "pick") return load(val);
    if (!S.v) return null;
    if (what === "play") play(!S.playing);
    else if (what === "now") follow();
    else if (what === "speed") { S.speed = +val; controls(); }
    else if (what === "scrub") { S.live = false; play(false); S.t = +val; safeDraw(); controls(); }
    else if (what === "row") { S.pick = S.pick === val ? null : val; S.key = ""; safeDraw(); }
    return null;
  }
  window.ScreenView = { mount, list, stop, act, choose, tick, refresh, state: () => ({ t: S.t, live: S.live, playing: S.playing, name: S.name, loaded: !!S.v, error: S.error, speed: S.speed, pick: S.pick, polling: !!S.poll }) };
})();
