// Season Sim Lab: the Season tab plays a trace (PR viewer). Every figure is in the trace's view
// (src/pickandroll/sim/lab/trace_view.py); this file only draws it and moves the clock.
// A day plays in three steps: the engine solves, the day's moves ride in, the games go in.
(function () {
  "use strict";
  const SIDES = ["a", "b"];
  const RIDE = 0.25, GAMES = 0.6, SECONDS = 1.5, SLOW = 0.25, EPS = 0.001;
  const SPEEDS = [1, 3, 10];
  const V = { M: null, list: [], name: null, view: null, error: null, t: 0, playing: false, speed: 3, raf: 0, last: 0, key: "", week: -1, el: null, W: 0, RW: 0, resize: 0 };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
  const isNum = (v) => typeof v === "number" && isFinite(v);
  const ease = (x) => x * x * (3 - 2 * x), lerp = (a, b, p) => a + (b - a) * p;
  const ord = (n) => (!isNum(n) ? "n/a" : n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : n % 10 === 1 ? "st" : n % 10 === 2 ? "nd" : n % 10 === 3 ? "rd" : "th"));
  const fmt = (v, d) => (!isNum(v) ? "none" : v.toFixed(d));
  const ARM = (s) => s.toUpperCase();
  const short = (pid) => { const p = V.view.players[String(pid)]; return p ? p.short : "player " + pid; };
  const res = (x) => (!x || !x.outcome ? "" : x.outcome === "W" ? "won" : x.outcome === "L" ? "lost" : "tied");
  const when = (t) => (t ? new Date(t).toLocaleString("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + " CT" : "n/a");
  const badge = (l) => `<span class="badge ${esc(l)}">${l === "ok" ? "✓ ok" : l === "watch" ? "! watch" : "✕ problem"}</span>`;
  const note = () => `<p class="sv-note">${esc(V.M && V.M.viewer ? V.M.viewer.note : "")}</p>`;

  // ------------------------------------------------------------------ the picker
  const pickLine = (x) => `${x.label || "no lever"}${x.values ? ` ${x.values.a} → ${x.values.b}` : ""} · ${x.from || x.form} · ${x.season_words || ""} · path ${x.path} · ${x.check.level}`;
  function picker() {
    return `<section class="panel"><div class="sv-pick"><span class="k">Trace</span>
      <select id="sv-pick" data-sv="pick" aria-label="the trace to play">${V.list.map((x) => `<option value="${esc(x.name)}"${x.name === V.name ? " selected" : ""}>${esc(pickLine(x))}</option>`).join("")}</select>${V.view ? badge(V.view.check.level) : ""}</div>
      ${V.view ? "" : note()}</section>`;
  }
  function head() {
    const v = V.view, s = v.summary, c = v.check;
    return `<section class="panel"><p class="sv-check">${badge(c.level)} ${esc(c.words)}${c.drift.length ? ": " + c.drift.map(esc).join("; ") : ""}</p>
      <p class="sub">${esc(s.form)} ${esc(s.from || "")}${s.row ? ` row <code>${esc(s.row)}</code>` : ""} · ${esc(s.season_words)} · ${esc(s.forecaster)} · seed ${esc(s.seed)} · path ${esc(s.path)} · the seat is team ${esc(v.seat)} of ${esc(v.teams)} · code <code>${esc(s.code_sha)}</code> · made ${esc(when(s.made))}</p>
      <div class="chips"><span class="chip">${esc(v.league.label)}</span><span class="chip">${esc(v.league.shape)}</span></div></section>`;
  }

  // ------------------------------------------------------------------ the tab's parts
  function bar() {
    const v = V.view, N = v.days.length;
    return `<section class="panel sv-sticky"><div class="sv-bar"><button class="btn" id="sv-play" data-sv="play">Play</button><div class="sv-clock" id="sv-clock"></div>
        <input type="range" id="sv-scrub" data-sv="scrub" min="0" max="${N - EPS}" step="0.01" value="0" aria-label="day of the season">
        <span class="seg">${SPEEDS.map((x) => `<button id="sv-sp${x}" data-sv="speed" data-v="${x}">${x}×</button>`).join("")}</span></div>
        <p class="sv-err" id="sv-err"></p>${note()}</section>
      <div class="wkstrip" id="sv-strip">${v.weeks.map((w, i) => `<button class="wk${w.bracket ? " po" : ""}" id="sv-wk${i}" data-sv="week" data-v="${i}" title="A's result, then B's"><i></i><i></i>${esc(w.label)}</button>`).join("")}</div>`;
  }
  const krow = (r) => `<div class="kdiff"><span>${esc(r.label)}</span><b class="ca">${esc(r.a)}</b><b class="cb">${esc(r.b)}</b></div>`;
  function pairPanel() {
    const v = V.view, p = v.pair, first = v.jumps.slice(0, 12), more = v.jumps.slice(12);
    const jump = (j, i) => `<button id="sv-j${i}" data-sv="jump" data-v="${j.day}">${esc(j.label)}${i ? "" : " · first"}</button>`;
    return `<section class="panel"><span class="k">The pair · what differs between the arms</span>
      <div class="sv-lever"><b>${esc(p.label)}</b>${p.values ? ` <span>${esc(p.values.a)} → ${esc(p.values.b)}</span>` : ""}${p.nudge ? `<small>${esc(p.nudge)}</small>` : ""}</div>
      <div class="kdiff kh"><span></span><b class="ca">A · ${esc(p.arms.a)}</b><b class="cb">B · ${esc(p.arms.b)}</b></div>
      ${p.differ.map(krow).join("") || `<p class="sub">The two arms' settings are the same.</p>`}
      <details class="same"><summary>${esc(p.same.length)} settings are the same in both arms</summary>${p.same.map(krow).join("")}</details>
      <div class="rule"></div><span class="k">Where the arms decide differently</span>
      <p class="sub">${v.jumps.length ? `On ${esc(v.differ.count)} days the arms' decisions for the seat differ (the set, what was queued or the claims). Tap a day to go there.` : "The two arms decide the same every day."}</p>
      <div class="jumps">${first.map(jump).join("")}</div>
      ${more.length ? `<details class="same"><summary>and ${esc(more.length)} more days</summary><div class="jumps">${more.map((j, i) => jump(j, i + first.length)).join("")}</div></details>` : ""}</section>`;
  }
  function knobPanel() {
    const v = V.view;
    const con = (x) => (x.differs ? `<b class="kdiffer">${esc(x.label)}: <span class="ca">A ${esc(x.a)}</span>, <span class="cb">B ${esc(x.b)}</span></b>` : `${esc(x.label)} ${esc(x.a)}`);
    return `<section class="panel"><span class="k">Knobs in force, day by day</span>
      ${v.flat.length ? `<p class="sub sv-flat">Constant all season, so not drawn${v.flat.some((x) => x.differs) ? " (the arms' own values where they differ)" : ""}: ${v.flat.map(con).join(" · ")}.</p>` : ""}
      ${v.unread.length ? `<p class="sub sv-flat">${v.unread.map((x) => `${esc(x.label)}: ${esc(x.words)}`).join(" · ")}.</p>` : ""}
      <div id="sv-charts">${v.charts.map((c, i) => `<div class="kchart"><div><b>${esc(c.label)}</b><span class="kv" id="sv-kv${i}"></span></div><p class="sub">${esc(c.words)}</p><div id="sv-ch${i}"></div></div>`).join("") || `<p class="sub">No knob moves through the season in either arm.</p>`}</div></section>`;
  }
  function lanePanel() {
    const v = V.view;
    return `<section class="panel"><span class="k">Each arm's move of the day</span><p class="sv-cmp" id="sv-cmp"></p>
      ${SIDES.map((s) => `<div class="sv-lane" id="sv-lane-${s}"><div class="sv-lanehead"><b class="c${s}">${ARM(s)} · ${esc(v.pair.arms[s])}</b><i class="sv-ring" id="sv-ring-${s}"></i><span class="sub" id="sv-say-${s}"></span></div>
        <div class="sv-roster" id="sv-ro-${s}"></div><span class="sv-rider in ${s}" id="sv-in-${s}"></span><span class="sv-rider out" id="sv-out-${s}"></span>
        <ul class="sv-line" id="sv-line-${s}"></ul></div>`).join("")}
      <p class="sub">A lit player arrived today; a dashed one only that arm holds. The slot is the day's lineup's.</p></section>`;
  }
  function matchPanel() {
    const v = V.view;
    const rows = v.points_league
      ? `<p class="sub">A points league's running score is not in the trace: each week's result is on the week strip.</p>`
      : v.cats.map((c, i) => `<div class="cat2"><span>${esc(c.label)}</span><div>${SIDES.map((s) => `<div class="tug2"><i class="b${s}" id="sv-u-${s}${i}"></i><em></em></div>`).join("")}</div></div>`).join("");
    return `<section class="panel"><span class="k" id="sv-mt"></span>
      <div class="sv-score2">${SIDES.map((s) => `<span class="c${s}">${ARM(s)} <b id="sv-sc-${s}"></b></span>`).join("")}</div>${rows}
      <p class="sub">Each bar is the seat's share of the category against its opponent (where the lower total wins, the opponent's); past the centre mark the seat leads. The day's games fill in after the moves.</p></section>`;
  }
  function racePanel() {
    const v = V.view;
    const end = (s) => { const e = v.end[s]; return `<p><b class="c${s}">${ARM(s)}</b> regular season ${esc(ord(e.rank))}${e.record ? ` (${e.record.map(esc).join("–")})` : ""}${e.bracket.length ? " · " + e.bracket.map(esc).join(" · ") : e.title ? " · the title" : ""}${e.breaches ? ` · ${esc(e.breaches)} audit breach(es)` : ""}</p>`; };
    return `<section class="panel"><div class="kchart"><div><b>The season's race: the seat's place before each week</b><span class="kv" id="sv-kvr"></span></div>
      <div class="tiles">${SIDES.map((s) => `<div class="tile ${s}"><span class="k c${s}">${ARM(s)} · ${esc(v.pair.arms[s])}</span><div id="sv-tile-${s}"></div></div>`).join("")}</div>
      <div id="sv-race"></div></div><div class="sv-ends">${SIDES.map(end).join("")}</div></section>`;
  }

  // ------------------------------------------------------------------ charts, at the panel's own width
  const PAD = { l: 44, r: 10, t: 10, b: 22 };
  const X = (day, w) => PAD.l + (day / V.view.days.length) * (w - PAD.l - PAD.r);
  function frame(w, h, id) {
    const v = V.view, N = v.days.length, b0 = v.days.findIndex((d) => d.bracket);
    let s = "";
    if (b0 >= 0) s += `<rect class="po" x="${X(b0, w)}" y="${PAD.t}" width="${X(N, w) - X(b0, w)}" height="${h - PAD.t - PAD.b}"/>`;
    const step = Math.max(1, Math.ceil(v.weeks.length / Math.max(2, Math.floor((w - PAD.l) / 56))));
    v.weeks.forEach((wk, i) => { if (i % step === 0 && wk.first != null) s += `<text class="tick" x="${X(wk.first, w)}" y="${h - 6}">${esc(wk.label)}</text>`; });
    s += `<path class="axis" d="M${PAD.l},${h - PAD.b} H${X(N, w)}"/>`;
    return { s, end: `<path class="nd" id="${id}" d="M0,${PAD.t - 4} V${h - PAD.b}"/>` };
  }
  function steps(vals, Y, w) {
    let d = "", on = false;
    vals.forEach((v, i) => {
      if (!isNum(v)) { on = false; return; }
      const x0 = X(i, w).toFixed(1), x1 = X(i + 1, w).toFixed(1), y = Y(v).toFixed(1);
      d += on ? ` V${y} H${x1}` : ` M${x0},${y} H${x1}`;
      on = true;
    });
    return d.trim();
  }
  function chartSvg(c, i, w) {
    const h = 104, Y = (v) => PAD.t + (1 - (v - c.lo) / (c.hi - c.lo || 1)) * (h - PAD.t - PAD.b);
    const f = frame(w, h, "sv-nd" + i);
    let s = f.s;
    for (const [v, t] of c.ticks) s += `<path class="grid" d="M${PAD.l},${Y(v).toFixed(1)} H${X(V.view.days.length, w)}"/><text class="tick" x="${PAD.l - 4}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${esc(t)}</text>`;
    if (c.cap) for (const sd of c.cap.same ? ["a"] : SIDES) s += `<path class="cap ${c.cap.same ? "" : "l" + sd}" d="${steps(c.cap[sd], Y, w)}"/>`;
    for (const sd of SIDES) s += `<path class="ln l${sd}" d="${steps(c[sd], Y, w)}"/>`;
    return `<svg class="sv-chart" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(c.label)}">${s}${f.end}</svg>`;
  }
  function raceSvg(w) {
    const v = V.view, h = 168, teams = Math.max(2, v.teams), Y = (r) => PAD.t + ((r - 1) / (teams - 1)) * (h - PAD.t - PAD.b), N = v.days.length;
    const f = frame(w, h, "sv-ndr");
    let s = f.s;
    for (const r of [1, teams]) s += `<path class="grid" d="M${PAD.l},${Y(r)} H${X(N, w)}"/><text class="tick" x="${PAD.l - 4}" y="${Y(r) + 4}" text-anchor="end">${esc(ord(r))}</text>`;
    if (isNum(v.playoff_teams) && v.playoff_teams < teams) s += `<path class="cut" d="M${PAD.l},${Y(v.playoff_teams + 0.5)} H${X(N, w)}"/><text class="cutl" x="${PAD.l + 4}" y="${Y(v.playoff_teams + 0.5) - 4}">playoff line</text>`;
    for (const sd of SIDES) {
      const pts = v.weeks.filter((wk) => wk[sd].before && wk.first != null).map((wk) => [X(wk.first, w), Y(wk[sd].before.rank)]);
      if (isNum(v.end[sd].rank)) pts.push([X(N, w), Y(v.end[sd].rank)]);
      if (pts.length) s += `<path class="ln l${sd}" d="${pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ")}"/>`;
    }
    return `<svg class="sv-chart" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="the seat's place by week">${s}${f.end}</svg>`;
  }
  function drawCharts() {
    const box = $("sv-charts"), race = $("sv-race");
    V.W = Math.max(260, Math.floor((box && box.clientWidth) || 560));
    V.RW = Math.max(260, Math.floor((race && race.clientWidth) || V.W));
    V.view.charts.forEach((c, i) => { const e = $("sv-ch" + i); if (e) e.innerHTML = chartSvg(c, i, V.W); });
    if (race) race.innerHTML = raceSvg(V.RW);
  }

  // ------------------------------------------------------------------ the clock
  function now() {
    const v = V.view, N = v.days.length, day = Math.max(0, Math.min(N - EPS, V.t)), di = Math.floor(day), f = day - di;
    const phase = f < RIDE ? 0 : f < GAMES ? 1 : 2;
    return { day, di, f, phase, g: phase === 2 ? (f - GAMES) / (1 - GAMES) : 0, d: v.days[di] };
  }
  const moving = (d) => SIDES.some((s) => d.sides[s] && d.sides[s].rides.length);
  function ride(n, s) {
    const side = n.d.sides[s], inn = $("sv-in-" + s), out = $("sv-out-" + s);
    if (!inn || !out) return;
    if (!side || n.phase !== 1 || !side.rides.length) { inn.style.display = "none"; out.style.display = "none"; return; }
    const k = side.rides.length, q = ((n.f - RIDE) / (GAMES - RIDE)) * k, j = Math.min(k - 1, Math.floor(q)), p = ease(q - j), r = side.rides[j];
    const chip = $(`sv-c-${s}-${r.spot}`), ro = $("sv-ro-" + s), lane = $("sv-lane-" + s);
    const x1 = chip ? chip.offsetLeft : 0, y1 = chip ? chip.offsetTop : 0, y0 = ro ? ro.offsetTop - 26 : 0;
    inn.textContent = short(r.in); inn.style.display = "";
    inn.style.transform = `translate(${lerp(0, x1, p).toFixed(1)}px,${lerp(y0, y1, p).toFixed(1)}px)`;
    if (r.out == null) { out.style.display = "none"; return; }
    out.textContent = short(r.out); out.style.display = ""; out.style.opacity = String(1 - p);
    const x2 = lane ? lane.offsetWidth - (chip ? chip.offsetWidth : 0) : x1, y2 = ro ? ro.offsetTop + ro.offsetHeight : y1;
    out.style.transform = `translate(${lerp(x1, x2, p).toFixed(1)}px,${lerp(y1, y2, p).toFixed(1)}px)`;
  }
  function draw() {
    const v = V.view;
    if (!v || !$("sv-clock")) return;
    const n = now(), { d, di, phase, g } = n;
    $("sv-clock").innerHTML = `${esc(d.label)} · ${esc(d.dow)}<small>day ${di + 1} of ${v.days.length} · ${esc(d.date)}</small>`;
    $("sv-scrub").value = n.day;
    v.charts.forEach((c, i) => { const e = $("sv-nd" + i); if (e) e.setAttribute("transform", `translate(${X(n.day, V.W).toFixed(1)},0)`); });
    const nr = $("sv-ndr"); if (nr) nr.setAttribute("transform", `translate(${X(n.day, V.RW).toFixed(1)},0)`);
    if (!v.points_league) for (const s of SIDES) {
      const side = d.sides[s], am = side && side.am, pm = (side && side.pm) || am;
      v.cats.forEach((c, i) => { const e = $(`sv-u-${s}${i}`); if (e) { e.style.width = am ? (100 * lerp(am.share[i], pm.share[i], g)).toFixed(1) + "%" : "0%"; } });
    }
    for (const s of SIDES) {
      const ring = $("sv-ring-" + s);
      if (ring) { ring.style.transform = `rotate(${phase === 0 ? Math.round(n.f * 1440) : 0}deg)`; ring.className = "sv-ring" + (phase === 0 ? " on" : ""); }
      ride(n, s);
    }
    const key = di + "/" + phase;
    if (key !== V.key) { V.key = key; step(n); }
  }
  // What changes only at a step of the day: the rosters, the words, the scores and the tiles.
  function step(n) {
    const v = V.view, { d, di, phase } = n, wi = v.weeks.findIndex((w) => w.week === d.week);
    if (wi !== V.week) {
      V.week = wi;
      v.weeks.forEach((w, i) => { const e = $("sv-wk" + i); if (e) { e.className = "wk" + (w.bracket ? " po" : "") + (i === wi ? " cur" : ""); e.innerHTML = `<i class="${i < wi ? res(w.a) : ""}"></i><i class="${i < wi ? res(w.b) : ""}"></i>${esc(w.label)}`; } });
      const strip = $("sv-strip"), cur = $("sv-wk" + wi);
      if (strip && cur && isNum(cur.offsetLeft)) strip.scrollLeft = cur.offsetLeft - (strip.clientWidth || 0) / 2;
    }
    for (const s of SIDES) {
      const side = d.sides[s], ro = $("sv-ro-" + s), line = $("sv-line-" + s), say = $("sv-say-" + s);
      if (!side) { if (ro) ro.innerHTML = `<p class="empty">No day recorded for this arm.</p>`; if (line) line.innerHTML = ""; continue; }
      if (ro) ro.innerHTML = side.roster.map((r, k) => {
        const rd = phase < 2 ? side.rides.find((x) => x.spot === k) : null;
        if (rd) return rd.out == null ? `<span class="pc wait" id="sv-c-${s}-${k}"><b>·</b><small>open</small></span>` : `<span class="pc leaving" id="sv-c-${s}-${k}"><b>${esc(short(rd.out))}</b><small>leaving</small></span>`;
        return `<span class="pc${r[3] && phase === 2 ? " fresh " + s : ""}${r[2] ? " only " + s : ""}" id="sv-c-${s}-${k}"><b>${esc(short(r[0]))}</b><small>${esc(r[1])}</small></span>`;
      }).join("");
      if (line) line.innerHTML = side.line.map((x) => `<li>${esc(x)}</li>`).join("");
      if (say) say.textContent = phase === 0 ? "solving the day" : phase === 1 ? (side.rides.length ? "the day's moves ride in" : "no move rides in") : "the games go in";
      const sc = $("sv-sc-" + s), m = phase === 2 ? side.pm || side.am : side.am;
      if (sc) sc.textContent = v.points_league ? "points" : m ? m.score.join("–") : "no matchup";
      const tile = $("sv-tile-" + s), wk = v.weeks[wi], b = wk && wk[s].before;
      if (tile) tile.innerHTML = `<b>${b ? esc(ord(b.rank)) : "—"}</b><small>${b ? esc(b.record.join("–")) : "no week played yet"} · adds this week ${esc(fmt(side.adds[0], 0))} of ${esc(fmt(side.adds[1], 0))}</small>`;
    }
    const cmp = $("sv-cmp");
    if (cmp) { cmp.textContent = d.compare; cmp.className = "sv-cmp" + (d.same ? "" : " diff"); }
    const sa = d.sides.a, sb = d.sides.b, oa = sa && sa.opponent, ob = sb && sb.opponent;
    const mt = $("sv-mt");
    if (mt) mt.textContent = `${d.label} · ` + (oa === ob ? (oa == null ? "no matchup this week" : `both arms against team ${oa}`) : `A against ${oa == null ? "nobody" : "team " + oa}, B against ${ob == null ? "nobody" : "team " + ob}`);
    v.charts.forEach((c, i) => {
      const e = $("sv-kv" + i); if (!e) return;
      e.innerHTML = SIDES.map((sd) => `<i class="l${sd}"></i>${ARM(sd)} ${esc(c.say[sd][di])}`).join("");
    });
    const kr = $("sv-kvr"), wk = v.weeks[wi];
    if (kr && wk) kr.innerHTML = SIDES.map((sd) => `<i class="l${sd}"></i>${ARM(sd)} ${wk[sd].before ? esc(ord(wk[sd].before.rank)) : "—"}`).join("");
    v.jumps.forEach((j, i) => { const e = $("sv-j" + i); if (e) e.className = j.day === di ? "on" : ""; });
  }
  function safeDraw() {
    try { draw(); } catch (e) { const el = $("sv-err"); if (el) el.textContent = "The viewer could not draw this day: " + e.message; }
  }
  function controls() {
    const b = $("sv-play");
    if (b) b.textContent = V.playing ? "Pause" : V.view && V.t >= V.view.days.length - EPS * 2 ? "Replay" : "Play";
    for (const x of SPEEDS) { const e = $("sv-sp" + x); if (e) e.className = x === V.speed ? "on" : ""; }
  }
  function tick(ts) {
    if (!V.playing || !V.view) return;
    const dt = Math.max(0, Math.min(0.1, (ts - V.last) / 1000)), n = now();
    V.last = ts;
    V.t += ((dt * V.speed) / SECONDS) * (n.phase === 1 && moving(n.d) ? SLOW : 1);
    if (V.t >= V.view.days.length) { V.t = V.view.days.length - EPS; V.playing = false; }
    safeDraw(); controls();
    if (V.playing) V.raf = requestAnimationFrame(tick);
  }
  function play(on) {
    cancelAnimationFrame(V.raf);
    V.playing = !!(on && V.view);
    if (V.playing) {
      if (V.t >= V.view.days.length - EPS * 2) V.t = 0;
      V.last = performance.now(); V.raf = requestAnimationFrame(tick);
    }
    controls();
  }
  function stop() { V.playing = false; cancelAnimationFrame(V.raf); }

  // ------------------------------------------------------------------ the tab
  function shell() {
    // Two columns on a wide screen (the pair, then the lanes; the knobs, then the matchup), each
    // as tall as its own parts; one column on a phone in the brief's order.
    V.el.innerHTML = picker() + bar() + head() + `<div class="sv-cols"><div class="sv-col"><div class="o1">${pairPanel()}</div><div class="o3">${lanePanel()}</div></div><div class="sv-col"><div class="o2">${knobPanel()}</div><div class="o4">${matchPanel()}</div></div></div>${racePanel()}`;
    V.key = ""; V.week = -1;
    drawCharts(); safeDraw(); controls();
  }
  function load(name) {
    stop();
    V.name = name; V.view = null; V.error = null;
    V.el.innerHTML = picker() + `<section class="panel"><p class="sub">Reading the trace…</p></section>`;
    return fetch("/api/trace/" + encodeURIComponent(name), { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : r.text().catch(() => "").then((t) => { throw new Error(t.trim() || "the trace answered " + r.status); })))
      .then((v) => { if (V.name !== name) return; V.view = v; V.t = 0; shell(); play(true); })
      .catch((e) => { if (V.name !== name) return; V.error = e.message; V.el.innerHTML = picker() + `<section class="panel"><p class="empty">${esc(e.message)}</p></section>`; });
  }
  function mount(el, M) {
    V.el = el; V.M = M; V.list = (M && M.traces) || [];
    if (!V.list.length) {
      stop(); V.view = null; V.name = null;
      el.innerHTML = `<section class="panel"><p class="empty">No trace on the box yet. A trace is written by the trace command (the lead runs it); the lab plays nothing.</p>${note()}</section>`;
      return null;
    }
    const want = V.list.some((x) => x.name === V.name) ? V.name : V.list[0].name;
    if (V.view && V.view.name === want) { const was = V.playing; shell(); play(was); return null; }
    return load(want);
  }
  // The model was built again while the tab is open: the list changes, the trace plays on.
  function list(M) {
    V.M = M; V.list = (M && M.traces) || [];
    if (!V.el) return null;
    if (!V.list.some((x) => x.name === V.name)) return mount(V.el, M);
    const p = $("sv-pick");
    if (p) p.innerHTML = V.list.map((x) => `<option value="${esc(x.name)}"${x.name === V.name ? " selected" : ""}>${esc(pickLine(x))}</option>`).join("");
    return null;
  }
  // A trace named from the Runs page: played when the Season tab opens.
  function choose(name) { if (V.name !== name) { V.name = name; V.view = null; } }
  function act(what, val) {
    if (what === "pick") return load(val);
    if (!V.view) return null;
    if (what === "play") play(!V.playing);
    else if (what === "speed") { V.speed = +val; controls(); }
    else if (what === "scrub") { V.t = +val; safeDraw(); controls(); }
    else if (what === "jump") { play(false); V.t = +val + RIDE; safeDraw(); controls(); }
    else if (what === "week") { const w = V.view.weeks[+val]; if (w && w.first != null) { V.t = w.first; safeDraw(); controls(); } }
    return null;
  }
  window.addEventListener("resize", () => {
    clearTimeout(V.resize);
    V.resize = setTimeout(() => { if (V.view && $("sv-charts")) { drawCharts(); V.key = ""; safeDraw(); } }, 200);
  });
  window.SeasonView = { mount, list, stop, act, choose, tick, state: () => ({ t: V.t, playing: V.playing, name: V.name, loaded: !!V.view, error: V.error, speed: V.speed }) };
})();
