// Season Sim Lab: the pages, drawn from /api/model. Every figure shown is in the model
// (src/pickandroll/sim/lab/model.py); this file only formats and lays it out.
(function () {
  "use strict";
  let M = null;
  const page = document.getElementById("page"), tipEl = document.getElementById("tip");
  const TIPS = [];
  const tip = (html) => { TIPS.push(html); return ` data-tip="${TIPS.length - 1}"`; };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c]));
  const NR = `<span class="empty">not recorded</span>`;

  // ------------------------------------------------------------------ formatting
  const O = (o) => M.outcomes[o];
  const isNum = (v) => typeof v === "number" && isFinite(v);
  const fx = (v, d) => (isNum(v) ? v.toFixed(d) : "n/a");
  const val = (v, o) => (!isNum(v) ? "n/a" : O(o).share ? fx(100 * v, 1) + "%" : fx(v, 2));
  const pm = (v, o) => (!isNum(v) ? "n/a" : O(o).share ? fx(100 * v, 1) + " pts" : fx(v, 2));
  const signed = (v, o) => (!isNum(v) ? "n/a" : (v > 0 ? "+" : v < 0 ? "−" : "") + pm(Math.abs(v), o));
  const ses = (r) => (!isNum(r) ? "n/a" : fx(Math.abs(r), 1) + " SE");
  const lever = (k) => (M.levers[k] || {}).label || k;
  const vals = (r) => (r.values ? `${esc(r.values.a)} → ${esc(r.values.b)}` : "");
  const tier = (t) => M.tiers[t] || t || "";
  const wordsOf = (s) => esc(s).replace(/^(.)/, (c) => c.toUpperCase());
  const ruleset = (k) => M.rulesets.find((x) => x.key === k);
  const tone = (k) => { const x = ruleset(k); return x ? x.tone % 4 : 3; };
  const day = (t) => (t ? esc(new Date(t).toLocaleString("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })) + " CT" : "n/a");
  const notes = () => M.notes;
  const levelBadge = (l) => `<span class="badge ${esc(l)}">${l === "ok" ? "✓ ok" : l === "watch" ? "! watch" : "✕ problem"}</span>`;
  const noNotes = (what) => `<p class="empty">${what}: no notes file.</p>`;

  function rowTip(r, o) {
    const row = (k, v) => `<div class="row"><span>${k}</span><span>${v}</span></div>`;
    const head = `<b>${esc(r.label)}</b> <code>${esc(r.key)}</code><div style="color:var(--muted)">${esc(r.nudge)}</div>${r.values ? `<div>${vals(r)}</div>` : ""}`;
    if (!r.played) return `${head}<hr><div>${esc(r.status || "not played")}${r.why ? ": " + esc(r.why) : ""}</div>`;
    const d = r.diff[o], c = r.counts || {}, f = (v) => fx(v, 2);
    return `${head}<hr>
      ${row(esc(r.cell), esc(r.paths) + " paths")}
      ${r.a ? row(esc(O(o).label) + ", A", val(r.a[o].mean, o)) + row(esc(O(o).label) + ", B", val(r.b[o].mean, o)) : ""}
      ${row("difference", signed(d.mean, o) + " ± " + pm(d.se, o))}${row("in SEs", fx(d.ratio, 2))}<hr>
      ${r.a ? row("playoff odds", val(r.a.made_playoffs.mean, "made_playoffs") + " → " + val(r.b.made_playoffs.mean, "made_playoffs")) : ""}
      ${row("adds a week", f((c.a || {}).adds_per_week) + " → " + f((c.b || {}).adds_per_week))}
      ${row("survives (the screen's rule)", r.survives ? "yes" : "no")}
      ${row("audit", esc(r.breaches) + " breaches, " + esc(r.voided) + " voided")}`;
  }
  function chips(x) { return x.chips.map((c) => `<span class="chip">${esc(c)}</span>`).join(""); }
  function worldLine(x) {
    const w = x.world;
    if (!w) return NR;
    return `${w.seasons.map(esc).join(", ") || "no season"} · ${esc(w.paths)} paths · seed ${esc(w.seed)} · ${w.tiers.map(esc).join(", ")}`;
  }

  // ------------------------------------------------------------------ results (PR results tab)
  // One card a screen or tune, newest first, in plain words: every figure and every line is the
  // model's (model.results_of); a difference inside one SE is level, never better or worse.
  const sideOf = (d) => (d.side === "better" ? "up" : d.side === "worse" ? "down" : "lvl");
  const judged = (d, o) => `<b class="${sideOf(d)}">${signed(d.mean, o)}</b> ± ${pm(d.se, o)} <small class="sub">${esc(d.words)}</small>`;
  const cellOf = (x, m, many) => `<div>${many ? `<span class="sub">${esc(x.season_words)} ${esc(x.forecaster)}: </span>` : ""}${judged(x.measure, m)}<br><span class="sub">playoff odds</span> ${judged(x.made_playoffs, "made_playoffs")}</div>`;
  const change = (e, m, many) => `<li><b>${esc(e.label)}</b>${e.values ? ` <span class="sub">${vals(e)}</span>` : ""}${e.cells.map((x) => cellOf(x, m, many)).join("")}</li>`;
  function resScreen(c) {
    const s = c.screen, m = c.measure, n = s.counts, many = s.cells > 1;
    const base = s.baseline.map((b) => `<div class="hero"><div><div class="big">${val(b.measure.mean, m)}<span class="pm">± ${pm(b.measure.se, m)}</span></div><small class="sub">${esc(c.measure_words)} a season</small></div>
        <div class="stat"><b>${val(b.made_playoffs.mean, "made_playoffs")}</b><small>makes the playoffs</small></div></div>
      <p class="sub">${esc(b.season_words)} · ${esc(b.forecaster)} · ${esc(b.paths)} paths${s.baseline_tier ? " · " + esc(s.baseline_tier) : ""}</p>`).join("") || `<p class="empty">${esc(s.no_baseline)}</p>`;
    const tally = [["up", n.up, "cleared one SE, better"], ["down", n.down, "cleared one SE, worse"], ["lvl", n.level, "inside one SE: level"], ["lvl", n.did_nothing, "did nothing"]]
      .map(([k, v, w]) => `<div class="stat"><b class="${k}">${esc(v)}</b><small>${w}</small></div>`).join("");
    const rest = [n.mixed ? `${esc(n.mixed)} better in one cell and worse in another` : "", n.not_played ? `${esc(n.not_played)} not played` : "", n.left ? `${esc(n.left)} left to play` : ""].filter(Boolean).join(" · ");
    const up = s.up.length ? `<div class="k">Every change that cleared one SE upward, best first</div><ul class="res-list">${s.up.map((e) => change(e, m, many)).join("")}</ul>` : `<p class="sub">No change cleared one SE upward.</p>`;
    const down = s.down.length ? `<div class="k">The largest that cleared one SE downward${s.down_more ? `, and ${esc(s.down_more)} more` : ""}</div><ul class="res-list">${s.down.map((e) => change(e, m, many)).join("")}</ul>` : "";
    const en = s.engine;
    const engine = !en ? "" : `<div class="res-engine"><div class="k">The engine's own update</div><p>${esc(en.words)} <span class="res-q"${tip(`<b>What the update changed</b>${en.knobs.map((k) => `<div>${esc(k)}</div>`).join("")}`)}>what it changed</span></p>${!en.played ? `<p class="empty">${esc(en.status || "not played")}</p>` : en.did_nothing ? `<p class="sub">did nothing</p>` : `<p class="sub">${esc(en.on)}</p>` + en.cells.map((x) => cellOf(x, m, many)).join("")}</div>`;
    return `<div class="k">Today's settings</div>${base}
      <div class="k">The single changes played, on ${esc(c.measure_words)}</div><div class="stats res-tally">${tally}</div>${rest ? `<p class="sub">${rest}</p>` : ""}
      ${up}${down}${engine}`;
  }
  function resTune(c) {
    const t = c.tune, m = c.measure, f = t.final, cf = t.confirmation;
    const levers = t.levers.map((l) => `<li><b>${esc(l.label)}</b> <span class="sub">${l.from != null ? "from " + esc(l.from) : ""}${t.stages > 1 && l.stage ? " · " + esc(l.stage) : ""}</span> · <b class="${l.moved ? "up" : "lvl"}">${esc(l.words)}</b>${l.written_words ? `<br><span class="sub">${esc(l.written_words)}</span>` : ""}${l.held_words ? `<br><span class="sub">${esc(l.held_words)}</span>` : ""}${l.values.length ? `<ul>${l.values.map((v) => `<li>${v.values ? vals(v) : esc(v.nudge)}: ${v.mean == null ? esc(v.status || "") : judged(v, m)}${v.standing ? ` <span class="sub">(${esc(v.standing)})</span>` : ""}</li>`).join("")}</ul>` : ""}</li>`).join("");
    const set = f ? (f.set.length ? f.set.map((x) => `${esc(x.label)} <b>${esc(x.value)}</b>`).join(" · ") : esc(f.words)) : esc(t.final_words);
    // A test cell: the record's finish first (what the verdict reads), on playoff odds and final
    // rank; the league's measure last, labelled and without a side's colour (it decides nothing).
    const cells = cf.cells.map((x) => `<div class="stat res-conf"><span class="k">Against ${esc(x.rivals)} · ${esc(x.forecaster)}</span><span class="sub">finish</span> <b class="res-finish ${sideOf({ side: x.finish_side })}">${esc(x.finish || "not recorded")}</b><span class="sub">playoff odds</span> ${judged(x.made_playoffs, "made_playoffs")}<br><span class="sub">final rank, lower is better</span> ${judged(x.rank, "rank")}<div class="res-aside"><span class="sub">${esc(cf.aside)}</span><br>${signed(x.measure.mean, m)} ± ${pm(x.measure.se, m)} <small>${esc(x.measure.words)}</small></div>${x.read ? "" : `<small>not read</small>`}</div>`).join("");
    return `${t.next ? `<p class="res-next">${esc(t.next)}</p>` : ""}<div class="k">The search, lever by lever, on ${esc(c.measure_words)}</div><ul class="res-list">${levers || `<li class="empty">No lever in its order.</li>`}</ul>
      <div class="k">Final set</div><p>${set}</p>
      <div class="k">The test${cf.season_words ? ` on ${esc(cf.season_words)}` : ""}: ${esc(cf.status)}</div>
      ${cf.reads ? `<p class="res-reads">${esc(cf.reads)}</p>` : ""}${cells ? `<div class="stats">${cells}</div>` : ""}
      ${cf.verdict ? `<p class="verdict">${esc(cf.verdict.words || cf.verdict.state)}</p>` : ""}`;
  }
  function resCard(c) {
    const r = c.reading;
    const read = r ? `<div class="entry"><div class="when"><span class="badge ${esc(r.level)}">${esc(r.level)}</span>${esc(r.date)}</div><p>${esc(r.text)}</p></div>` : `<p class="empty">${esc(c.no_reading)}</p>`;
    const watch = c.kind === "screen" && c.folder ? ` <a href="#screen" data-screen="${esc(c.folder)}">Watch it on the Screen tab.</a>` : "";
    return `<details class="panel res rs t${tone(c.ruleset)}"${c.folded ? "" : " open"}><summary><h2>${esc(c.title)}</h2><span class="sub">${esc(c.days || "no piece yet")} · <code>${esc(c.name)}</code> · <b class="res-state">${esc(c.state_words)}</b></span>
        <span class="sub">played on ${capw(c.capability)}${c.folded ? " · folded: of an engine live has left" : ""}</span></summary>
      ${c.earlier ? `<p class="caution">${esc(c.earlier)}</p>` : ""}
      <p class="did">${esc(c.did)}${watch}</p>
      ${c.kind === "screen" ? resScreen(c) : resTune(c)}
      <div class="k">The lead's reading</div>${read}
      <div class="k">What this does not show</div><ul class="res-not">${c.not_shown.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></details>`;
  }
  function resultsPage() {
    const R = M.results;
    const how = `<section class="panel res-how"><h2>How to read this</h2><ul>${R.how.map((h) => `<li><b>${esc(h.term)}</b>: ${esc(h.words)}</li>`).join("")}</ul></section>`;
    // The lead's own summary across runs, from the notes: drawn only when the notes hold one.
    const st = R.stands;
    const stands = !st ? "" : `<section class="panel res-stands"><h2>Where it stands</h2><p class="sub">${esc(st.label)} Written ${esc(st.date)}.</p><ul>${st.lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></section>`;
    return `<p class="lede">What each screen and tune found, in plain words, newest first. <b>Every figure is read from the records</b>; a run played on an engine live has left is folded shut.</p>
      ${how}${stands}${R.cards.length ? R.cards.map(resCard).join("") : `<section class="panel"><p class="empty">${esc(R.none)}</p></section>`}`;
  }

  // ------------------------------------------------------------------ overview
  function rsCard(x) {
    const m = x.measure, b = x.baseline && x.baseline.cells[0];
    const spark = x.spark.map((s) => {
      const z = !isNum(s.z) ? 0 : Math.max(-3.8, Math.min(3.8, s.z));
      return `<i class="${s.cleared ? "s " + esc(s.side) : ""}"${tip(`<b>${esc(s.label)}</b><div>${esc(s.nudge)}</div><div>${fx(s.z, 2)} SE</div>`)}><u style="top:${50 - (z / 4) * 50}%"></u></i>`;
    }).join("");
    const t = x.tried, st = x.strongest;
    const hero = b
      ? `<div class="hero"><div class="big">${val(b.outcomes[m].mean, m)}<span class="pm">± ${pm(b.outcomes[m].se, m)}</span></div>
        <div class="stats">
          <div class="stat"><b>${val(b.outcomes.made_playoffs.mean, "made_playoffs")}</b><small>makes the playoffs</small></div>
          <div class="stat"><b>${val(b.outcomes.rank.mean, "rank")}</b><small>average finish${x.teams ? " of " + esc(x.teams) : ""}</small></div>
          <div class="stat"><b>${val(b.outcomes.title.mean, "title")}</b><small>wins the title</small></div>
        </div></div><p class="sub">${esc(b.season_words)} · ${esc(b.forecaster)} · ${esc(b.paths)} paths · the baseline from <code>${esc(x.baseline.run)}</code> row <code>${esc(x.baseline.row)}</code></p>`
      : `<p class="empty">The baseline is not recorded: no played screen row sets nothing but its tier in both arms.</p>`;
    return `<section class="panel rs t${x.tone % 4}">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:start"><div><h2>${esc(x.name)}</h2><p class="sub">${esc(x.label)}</p></div>
      <a href="#checks" class="badge ${esc(x.checks.level)}" style="text-decoration:none">checks: ${esc(x.checks.level)}</a></div>
      <div class="chips">${chips(x)}</div>
      <div class="k">${esc(O(m).label)} a season · current settings</div>${hero}
      <p class="sub">${worldLine(x)}</p>
      <div class="rule"></div>
      <div class="k">Changes tried in the latest screen${x.screen ? ` (<code>${esc(x.screen)}</code>)` : ""}</div>
      ${x.screen ? `<div class="tried"><div><span class="n">${esc(t.cleared)}</span> of ${esc(t.done)} cleared one SE
        <div class="sub"><span class="up">▲ ${esc(t.better)} better</span> · <span class="down">▼ ${esc(t.worse)} worse</span> · luck alone ≈ ${fx(t.luck, 1)} · ${esc(t.did_nothing)} did nothing · ${esc(t.not_played)} not played</div></div>
        <div class="spark" title="each change: its effect in SEs, best to worst"><span class="band"></span><em class="hi">better</em><em class="lo">worse</em>${spark}</div></div>
      <p class="sub" style="text-align:right">each dot a change, best to worst · grey band: within one SE, the noise</p>
      ${st ? `<p class="strong">Strongest: <b>${esc(st.label)}, ${vals(st)}</b> at ${signed(st.diff.mean, m)} (${ses(st.diff.ratio)}). ${wordsOf(st.words)}.</p>` : ""}` : `<p class="empty">No screen yet.</p>`}
    </section>`;
  }
  function stage(s, m) {
    let big = "?", small = esc(s.words);
    if (s.id === "baseline" && s.value) { big = val(s.value.mean, m); small = `± ${pm(s.value.se, m)} · ${esc(s.words)}`; }
    else if (s.id === "screen" && s.diff) { big = val(s.value && s.value.mean, m); small = `${esc(s.label)}, ${signed(s.diff.mean, m)} ± ${pm(s.diff.se, m)} · ${esc(s.words)}`; }
    else if (s.id === "searched" && !s.ghost) { big = signed(s.value.mean, m); small = esc(s.words); }
    else if (s.id === "unseen" && !s.ghost) {
      const kept = s.kept && isNum(s.kept.run) ? ` · kept ${fx(100 * s.kept.run, 0)}% of the search's gain` : "";
      const st = s.static ? ` · rivals as recorded: ${signed(s.static.mean, m)} ± ${pm(s.static.se, m)}` : "";
      big = signed(s.value.mean, m); small = `± ${pm(s.value.se, m)} on ${esc(s.season)}${st}${kept}${s.verdict ? " · " + esc(s.verdict.words || s.verdict.state) : ""}`;
    }
    return `<div class="stage ${s.ghost ? "ghost" : ""}"><span class="tag">${esc(s.tag)}</span><span class="k">${esc(s.title)}</span><b>${big}</b><small>${small}</small>${s.capability ? `<small class="capt">played on ${capw(s.capability)}</small>` : ""}</div>`;
  }
  // ------------------------------------------------------------------ capabilities (PR capabilities)
  const capw = (c) => (c ? `version ${esc(c.replay_version)} · ${esc(c.title)}` : "no recorded version");
  const stepped = (m) => [["replay", m.replay_version], ["screen", m.screen_version], ["tune", m.tune_version]].filter(([, v]) => v != null).map(([k, v]) => `${k} ${esc(v)}`).join(", ");
  function shiftBlock(x) {
    const m = x.measure;
    return (x.shifts || []).map((h) => `<div class="shift"><b>Across a capability.</b> <code>${esc(h.from.run)}</code> (${capw(h.from.capability)}) to <code>${esc(h.to.run)}</code> (${capw(h.to.capability)}): ${esc(h.words)}${h.same_world ? "" : "; their seed or paths differ too, so part of it is the draw"}.
      <ul>${h.baseline.map((b) => `<li>The baseline on ${esc(b.season_words)} ${esc(b.forecaster)}: ${val(b.before.mean, m)} to ${val(b.after.mean, m)} (${signed(b.shift, m)})</li>`).join("")}${h.rows.map((r) => `<li>${esc(r.label)} ${vals(r)} on ${esc(r.cell)}: ${signed(r.before.mean, m)} to ${signed(r.after.mean, m)} (${signed(r.shift, m)})</li>`).join("")}</ul></div>`).join("");
  }
  const stages = (x) => `<div class="rsname c${x.tone % 4}">${esc(x.name)} · ${esc(O(x.measure).label.toLowerCase())}</div><div class="stages">${x.stages.map((s) => stage(s, x.measure)).join("")}</div>${x.crosses ? `<p class="crosses">${esc(x.crosses)}</p>` : ""}${shiftBlock(x)}`;
  function capStrip() {
    const C = M.capabilities;
    if (!C) return "";
    const now = C.current, last = C.latest;
    const behind = C.behind.length ? C.behind.map((e) => `<b>${esc(e.issue)}</b> ${esc(e.title)} <span class="sub">(${esc(e.date)})</span>`).join(" · ") : C.engine.length ? "nothing outstanding" : C.noted ? "the notes list no live-engine change" : "no notes file";
    return `<section class="panel"><h2>The simulator's capabilities</h2><p class="sub">Each change to what the simulator can do is a mark (the log is under Runs), and every run says which one it was played on. A figure that crosses a mark moved partly because the simulator did.</p>
      <div class="capgrid"><div><span class="k">Now</span><b>${now ? `version ${esc(now.replay_version)}` : "n/a"}</b><small>${now ? `${esc(now.title)} · ${esc(now.date)}` : ""}</small></div>
      <div><span class="k">Last update</span><b>${last ? esc(last.title) : "n/a"}</b><small>${last ? `${esc(last.date)} · ${esc(last.kind)} · ${stepped(last) || "no version stepped"}` : ""}</small></div>
      <div><span class="k">Behind live in</span><small class="behind">${behind}</small>${C.earlier && C.earlier.length ? `<small>${C.earlier.length === C.of ? "every run with a version is" : `${C.earlier.map((n) => `<code>${esc(n)}</code>`).join(", ")} ${C.earlier.length === 1 ? "is" : "are"}`} of an engine live has left</small>` : ""}</div></div></section>`;
  }
  const queueItem = (q) => `<div class="item"><b>${esc(q.title)}</b><span class="badge ${q.state === "word" ? "word" : ""}">${q.state === "word" ? "waits on your word" : esc(q.state)}</span>
    <p>${esc(q.what)}</p><span class="sub" style="text-align:right">${esc(q.size || "")}</span>${q.say ? `<p class="say">say: “${esc(q.say)}”</p>` : ""}</div>`;
  const entry = (a) => `<div class="entry"><div class="when"><span class="badge ${esc(a.level)}">${esc(a.level)}</span>${esc(a.date)}${a.run ? ` · <code>${esc(a.run)}</code>` : ""}</div><p>${esc(a.text)}</p></div>`;
  // A ruleset with no screen and no tune is left off Overview and Checks; its runs stay on Runs.
  const listed = () => M.rulesets.filter((x) => x.listed);
  function overview() {
    const n = notes(), rs = listed();
    const cards = rs.length ? `<div class="grid2">${rs.map(rsCard).join("")}</div>` : `<section class="panel"><p class="empty">No screen or tune is recorded yet.</p></section>`;
    return `<p class="lede">What the simulator has played, what it found, and how far to trust it. <b>Every figure is read from the records</b> on the box, built again when they change.</p>
      ${cards}
      ${capStrip()}
      <section class="panel"><h2>Is the seat getting better?</h2><p class="sub">Each ruleset's own measure, from today's settings to a tuned set checked on a season no search has seen.</p>
        ${rs.map(stages).join("") || `<p class="empty">Nothing recorded.</p>`}</section>
      <div class="grid2">
        <section class="panel"><h2>Queue</h2><p class="sub">Every run over an hour is announced first and starts only on your word.</p>${n ? n.queue.map(queueItem).join("") || `<p class="empty">Nothing queued.</p>` : noNotes("The queue")}</section>
        <section class="panel"><h2>Latest assessments</h2><p class="sub">Written by the lead after every run. Full log under Checks.</p>${n ? n.assessments.slice(0, 3).map(entry).join("") || `<p class="empty">None yet.</p>` : noNotes("The assessments")}</section>
      </div>`;
  }

  // ------------------------------------------------------------------ knobs
  const K = { rs: "", out: "measure", unit: "raw", sort: "lever" };
  new URLSearchParams(location.search).forEach((v, k) => { if (k in K) K[k] = v; });
  const outOf = (x) => (K.out === "measure" ? x.measure : K.out);
  const rowsOf = (x) => M.knobs.rows.filter((r) => r.run === x.screen);
  const zOf = (r, o) => (r && r.played && !r.did_nothing && r.diff[o].z != null ? r.diff[o].z : -Infinity);
  function track(r, o, dom, unit) {
    if (!r) return `<div class="track"><span class="none">not in this screen</span></div>`;
    if (!r.played) return `<div class="track"><span class="none">${esc(r.status || "not played")}</span></div>`;
    if (r.did_nothing) return `<div class="track"><span class="none">did nothing: no decision changed</span></div>`;
    const d = r.diff[o];
    if (d.mean == null) return `<div class="track"><span class="none">not recorded</span></div>`;
    const b = O(o).better, se = d.se || 0, c = d.mean * b, u = unit === "se" ? se || 1 : 1;
    const x = (v) => 50 + 50 * Math.max(-1, Math.min(1, v / u / dom));
    const seg = (cls, lo, hi) => `<i class="${cls}" style="left:${x(lo)}%;width:${Math.max(0.6, x(hi) - x(lo))}%"></i>`;
    return `<div class="track ${d.clears ? "s " + d.side : ""}"><i class="zero"></i>${seg("w2", c - 2 * se, c + 2 * se)}${seg("w1", c - se, c + se)}<i class="pt" style="left:${x(c)}%"></i></div>`;
  }
  const lab = (r) => `<div class="lab"><b>${esc(r.label)}</b><small>${r.values ? `<i>${vals(r)}</i> · ` : ""}${esc(r.nudge)}${r.cell ? " · " + esc(r.cell) : ""}</small></div>`;
  const axis = (dom, unit, o) => { const t = (v) => (unit === "se" ? v + " SE" : O(o).share ? (100 * v).toFixed(0) + " pts" : String(+v.toPrecision(2))); return `<div class="axis"><span>◀ worse ${t(dom)}</span><span>0</span><span>${t(dom)} better ▶</span></div>`; };
  const order = (rows, o) => (K.sort === "strength" ? [...rows].sort((a, b) => zOf(b, o) - zOf(a, o)) : rows);
  function forestOne(x) {
    const o = outOf(x), d = M.knobs.domains[x.screen][o], dom = K.unit === "se" ? d.se : d.raw;
    const rows = order(rowsOf(x), o).map((r) => {
      let v = `<div class="val"><small>${r.played ? "did nothing" : esc(r.status || "not played")}</small></div>`;
      if (r.played && !r.did_nothing) {
        const e = r.diff[o];
        v = `<div class="val">${signed(e.mean, o)} ± ${pm(e.se, o)}<small>${ses(e.ratio)} · ${e.clears ? e.side : "inside the noise"}${o === r.measure ? "" : " · not the screen's rule"}</small></div>`;
      }
      return `<div class="frow ${r.played && !r.did_nothing ? "" : "off"}"${tip(rowTip(r, o))}>${lab(r)}${track(r, o, dom, K.unit)}${v}</div>`;
    }).join("");
    return `<div class="forest"><div class="fhead"><span class="c${x.tone % 4}">${esc(x.name)} · B against A</span>${axis(dom, K.unit, o)}<span class="val">${esc(O(o).label)}</span></div>${rows || `<p class="empty">No rows.</p>`}</div>`;
  }
  function forestTwo(a, b) {
    const oa = outOf(a), ob = outOf(b), dom = Math.max(M.knobs.domains[a.screen][oa].se, M.knobs.domains[b.screen][ob].se);
    const ra = rowsOf(a), rb = rowsOf(b), keys = [...new Set([...ra.map((r) => r.key), ...rb.map((r) => r.key)])];
    const sh = Object.fromEntries(M.knobs.shared.filter((s) => s.by_ruleset[a.key] && s.by_ruleset[b.key]).map((s) => [s.key, s]));
    let list = keys.map((k) => ({ k, x: ra.find((r) => r.key === k), y: rb.find((r) => r.key === k) }));
    if (K.sort === "strength") list.sort((p, q) => zOf(q.x, oa) - zOf(p.x, oa));
    const rows = list.map(({ k, x, y }) => {
      const s = sh[k];
      const ag = !s ? "" : s.cleared === "agree" ? `<span class="${s.by_ruleset[a.key].side === "better" ? "up" : "down"}">agree</span>` : s.cleared === "split" ? `<span style="color:var(--accent)">split</span>` : s.signs === "differ" ? `<span class="sub">signs differ</span>` : "";
      const t = (x ? `<div class="k c${a.tone % 4}">${esc(a.name)}</div>` + rowTip(x, oa) : "") + (x && y ? "<hr>" : "") + (y ? `<div class="k c${b.tone % 4}">${esc(b.name)}</div>` + rowTip(y, ob) : "");
      return `<div class="frow"${tip(t)}>${lab(x || y)}${track(x, oa, dom, "se")}${track(y, ob, dom, "se")}<div class="agree">${ag}</div></div>`;
    }).join("");
    return `<div class="forest two"><div class="fhead"><span>B against A, in SEs</span><div><span class="c${a.tone % 4}">${esc(a.name)} · ${esc(O(oa).label.toLowerCase())}</span>${axis(dom, "se", oa)}</div><div><span class="c${b.tone % 4}">${esc(b.name)} · ${esc(O(ob).label.toLowerCase())}</span>${axis(dom, "se", ob)}</div><span class="agree">both</span></div>${rows}</div>`;
  }
  const seg = (name, opts) => `<span class="seg">${opts.map(([v, t]) => `<button data-k="${name}" data-v="${esc(v)}" class="${K[name] === v ? "on" : ""}">${esc(t)}</button>`).join("")}</span>`;
  function knobs() {
    const withScreen = listed().filter((x) => x.screen);
    if (!withScreen.length) return `<section class="panel"><p class="empty">No screen is recorded yet.</p></section>`;
    const pair = withScreen.length > 1 ? withScreen.slice(0, 2) : null;
    if (K.rs !== "both" && !withScreen.some((x) => x.key === K.rs)) K.rs = withScreen[0].key;
    if (K.rs === "both" && !pair) K.rs = withScreen[0].key;
    const opts = withScreen.map((x) => [x.key, x.name]).concat(pair ? [["both", "Side by side"]] : []);
    const one = withScreen.find((x) => x.key === K.rs);
    return `<p class="caution">${esc(M.knobs.line)}</p><p class="lede">Every change the screens tried, B (the change) against A (the baseline) on the same simulated seasons. A dot is the change's effect; its bar is one SE either side, the thin line two. <b>Right is better for the seat.</b></p>
      <section class="panel"><div class="controls">
        <div class="ctl"><span class="k">Ruleset</span>${seg("rs", opts)}</div>
        <div class="ctl"><span class="k">Outcome</span>${seg("out", [["measure", "League's measure"], ...Object.keys(M.outcomes).map((o) => [o, M.outcomes[o].label])])}</div>
        ${K.rs === "both" ? "" : `<div class="ctl"><span class="k">Scale</span>${seg("unit", [["raw", "Raw"], ["se", "In SEs"]])}</div>`}
        <div class="ctl"><span class="k">Order</span>${seg("sort", [["lever", "By lever"], ["strength", "Best first"]])}</div></div>
        ${K.rs === "both" ? forestTwo(pair[0], pair[1]) : forestOne(one)}
        <div class="legend"><span><i class="lg-pt better"></i>cleared one SE, better</span><span><i class="lg-pt worse"></i>cleared one SE, worse</span><span><i class="lg-pt"></i>inside the noise</span><span><i class="lg-w1"></i>± 1 SE</span><span><i class="lg-w2"></i>± 2 SE</span></div>
      </section>
      <p class="caution">A screen judges no lever and recommends nothing: it picks what the tune tests. "Survives" is the screen's own rule on the league's measure; on another outcome, clearing one SE is worked out here and is not the screen's rule.</p>`;
  }

  // ------------------------------------------------------------------ checks
  function luckPanel(x) {
    const L = x.checks.luck, n = notes(), a = n && n.assessments.find((e) => e.ruleset === x.key || x.runs.includes(e.run));
    const bars = L.tries ? L.bars.map((b) => `<div><b style="font-weight:500">${esc(b.name)}</b>${b.note ? `<br><small>${esc(b.note)}</small>` : ""}</div>
      <div class="bar"><span style="width:${(100 * b.seen) / L.tries}%"></span><em style="left:${Math.min(100, (100 * b.luck) / L.tries)}%" title="by luck alone"></em></div>
      <small>seen <b style="color:var(--text)">${esc(b.seen)}</b> · luck ${fx(b.luck, 1)}</small>`).join("") : `<p class="empty">No try yet.</p>`;
    return `<section class="panel rs t${x.tone % 4}"><h2>${esc(x.name)}</h2><p class="sub">${esc(L.tries)} changes that did something in <code>${esc(x.screen || "no screen")}</code> · measured on ${esc(O(x.measure).label.toLowerCase())}</p>
      <div class="k" style="margin-top:12px">Seen against luck alone <span style="color:var(--accent)">▏</span>= expected by luck</div><div class="luck">${bars}</div>
      ${a ? `<p class="verdict">${esc(a.text)}</p>` : ""}<div class="rule"></div>
      ${x.checks.flags.map((f) => `<div class="flag">${levelBadge(f.level)}<p><b>${esc(f.title)}.</b> ${esc(f.text)}${f.from === "notes" ? ` <span class="sub">(the lead's notes)</span>` : ""}</p></div>`).join("")}</section>`;
  }
  function checksPage() {
    const roleName = { search: "search", confirm: "confirmation", holdout: "hold-out · locked", current: "this season", replay: "replay only" };
    const n = notes();
    return `<p class="lede">Is this real, or did we go looking until something turned up? These checks are <b>recomputed on every build</b> from the records. The lead writes a dated assessment <b>after every run</b>.</p>
      <p class="sub">${esc(M.checks.rule)}.</p>
      <div class="grid2">${listed().map(luckPanel).join("") || `<section class="panel"><p class="empty">Nothing recorded.</p></section>`}</div>
      <div class="grid2">
        <section class="panel"><h2>Seasons' ledger</h2><p class="sub">A season that has been searched cannot also confirm. The hold-out is never touched.</p><div class="tablewrap"><table>
          <tr><th>Season</th><th>Role</th><th class="n">Screens</th><th class="n">Searches</th><th class="n">Confirmations</th><th class="n">Replays</th><th class="n">Traces</th><th class="n">Looks</th><th>Note</th></tr>
          ${M.seasons.map((s) => `<tr><td><b>${esc(s.words)}</b></td><td><span class="role ${esc(s.role)}">${esc(roleName[s.role] || s.role)}</span></td><td class="n">${esc(s.screens)}</td><td class="n">${esc(s.searches)}</td><td class="n">${esc(s.confirmations)}</td><td class="n">${esc(s.replays)}</td><td class="n">${esc(s.traces)}</td><td class="n">${esc(s.looks)}</td><td class="sub">${esc(s.note || "")}${s.from === "notes" ? "" : ` (from the ${esc(s.from)})`}</td></tr>`).join("")}
        </table></div></section>
        <section class="panel"><h2>Assessment log</h2><p class="sub">The lead's reading after each run, newest first.</p>${n ? n.assessments.map(entry).join("") || `<p class="empty">None yet.</p>` : noNotes("The log")}</section>
      </div>`;
  }

  // ------------------------------------------------------------------ runs
  function tuneTable(t) {
    const m = t.measure;
    const steps = t.steps.map((s) => s.values.map((v, i) => `<tr class="${v.taken ? "taken" : ""}"><td>${i ? "" : `<b>${esc(s.label)}</b><br><span class="sub">pass ${esc(s.pass)} · from ${esc(s.from)}</span>`}</td>
      <td>${v.values ? `${esc(v.values.a)} → ${esc(v.values.b)}` : esc(v.nudge)}</td><td class="n">${v.mean == null ? esc(v.status || "") : signed(v.mean, m)}</td><td class="n">${v.se == null ? "" : pm(v.se, m)}</td>
      <td>${esc(v.standing || "")}${v.taken ? " · taken" : ""}</td></tr>`).join("")).join("");
    const c = t.confirmation;
    const cells = c.cells.map((e) => `<tr><td>${esc(e.kind)}</td><td>${esc(e.forecaster)}</td><td class="n">${signed(e.measure.mean, m)} ± ${pm(e.measure.se, m)}</td><td class="n">${signed(e.made_playoffs.mean, "made_playoffs")}</td><td>${e.read ? "read" : "not read"}</td></tr>`).join("");
    const f = t.final;
    return `<section class="panel"><h2>Tune <code>${esc(t.name)}</code></h2><p class="sub">${esc(ruleset(t.ruleset) ? ruleset(t.ruleset).name : t.ruleset)} · searched ${t.searched.map(esc).join(", ") || "n/a"} · ${esc(t.status)} · audit ${esc(t.audit.breaches)} breaches, ${esc(t.audit.voided)} voided</p>
      <div class="k" style="margin-top:10px">The search, lever by lever</div>
      <div class="tablewrap"><table><tr><th>Lever</th><th>Value</th><th class="n">${esc(O(m).label)}</th><th class="n">SE</th><th>Standing</th></tr>${steps || `<tr><td colspan="5" class="empty">No step yet.</td></tr>`}</table></div>
      <p class="sub" style="margin-top:8px">Final set: ${f ? Object.entries(f.set).map(([k, v]) => `${esc(lever(k))} ${esc(v)}`).join(" · ") || "the baseline" : "not yet"}.</p>
      <div class="k" style="margin-top:12px">The confirmation${c.season_words ? ` on ${esc(c.season_words)}` : ""}: ${esc(c.status || "not played")}</div>
      ${cells ? `<div class="tablewrap"><table><tr><th>Rivals</th><th>Forecaster</th><th class="n">${esc(O(m).label)}</th><th class="n">Playoff odds</th><th>Read</th></tr>${cells}</table></div>` : ""}
      ${c.verdict ? `<p class="verdict">${esc(c.verdict.words || c.verdict.state)}</p>` : ""}</section>`;
  }
  function traceTable() {
    const rows = M.traces.map((x) => `<tr><td><a href="#season" data-trace="${esc(x.name)}"><b>${esc(x.name)}</b></a><br><span class="sub">${esc(x.form)}${x.from ? " " + esc(x.from) : ""}${x.row ? " · " + esc(x.row) : ""}</span></td>
      <td>${esc(x.label || "no lever")}${x.values ? `<br><span class="sub">${esc(x.values.a)} → ${esc(x.values.b)}</span>` : ""}</td><td>${esc(x.season_words || "n/a")}<br><span class="sub">${esc(x.forecaster)}</span></td>
      <td class="n">${esc(x.path)}<br><span class="sub">seed ${esc(x.seed)}</span></td><td class="n">${esc(x.differ_days)}</td><td>${levelBadge(x.check.level)}<br><span class="sub">${esc(x.check.status)}</span></td>
      <td><code>${esc(x.code_sha || "")}</code><br><span class="sub">${day(x.made)}</span></td></tr>`).join("");
    return rows ? `<div class="tablewrap"><table><tr><th>Trace</th><th>Pair</th><th>Season</th><th class="n">Path</th><th class="n">Days apart</th><th>Check</th><th>Code</th></tr>${rows}</table></div>` : `<p class="empty">No trace on the box yet.</p>`;
  }
  function runsPage() {
    const runs = M.runs, n = notes();
    const rows = runs.map((r) => {
      const x = ruleset(r.ruleset);
      const nm = r.kind === "screen" && r.folder ? `<a href="#screen" data-screen="${esc(r.folder)}"><b>${esc(r.name)}</b></a>` : `<b>${esc(r.name)}</b>`;
      return `<tr><td>${nm}<br><span class="sub">${esc(r.kind)}${r.design ? " · " + esc(r.design) : ""}</span></td><td><span class="c${tone(r.ruleset)}">${esc(x ? x.name : r.ruleset)}</span></td>
      <td>${r.season_words.map(esc).join(", ") || "n/a"}<br><span class="sub">${esc(r.forecasters)}</span></td><td class="n">${esc(r.paths)}<br><span class="sub">seed ${esc(r.seed)}</span></td>
      <td class="n">${esc(r.pairs_done)}${r.pairs_left ? " · " + esc(r.pairs_left) + " left" : ""}<br><span class="sub">${esc(r.not_played)} not played</span></td><td class="n">${esc(r.cleared)}</td>
      <td class="n">${isNum(r.hours) ? fx(r.hours, 1) + " h" : "n/a"}<br><span class="sub">${r.pieces.length} piece(s)</span></td><td>${levelBadge(r.audit.level)}<br><span class="sub">${esc(r.audit.breaches)} breaches, ${esc(r.audit.voided)} voided</span></td><td>${capw(r.capability)}${r.behind_live && r.behind_live.length ? `<br><span class="sub">behind live: ${r.behind_live.map((e) => esc(e.issue)).join(", ")}</span>` : ""}${r.live_since && r.live_since.length ? `<br><span class="sub">live changed since: ${r.live_since.map((e) => esc(e.issue)).join(", ")}</span>` : ""}</td><td><code>${esc(r.code_sha || "")}</code><br><span class="sub">${esc(r.status)}</span></td></tr>`;
    }).join("");
    const span = M.timeline || {};
    // The capability log's marks and live's changes on the time line, one line a day (PR capabilities).
    const C = M.capabilities || { log: [], engine: [] }, onDay = {};
    const put = (d, at) => (onDay[d] = onDay[d] || { at, marks: [], live: [] });
    C.log.forEach((m) => { if (m.at != null) put(m.date, m.at).marks.push(m); });
    C.engine.forEach((e) => { if (e.at != null) put(e.date, e.at).live.push(e); });
    const days = Object.entries(onDay);
    const lines = days.map(([, d]) => `<i class="mk${d.marks.length ? "" : " live"}" style="left:${100 * d.at}%"></i>`).join("");
    const marksRow = days.length ? `<div class="grow gmk"><span class="sub">marks</span><div class="gtrack">${days.map(([dd, d]) => `<b class="mkl${d.marks.length ? "" : " live"}" style="left:${100 * d.at}%"${tip(`<b>${esc(dd)}</b>` + d.marks.map((m) => `<div>${esc(m.title)} <span class="sub">${esc(m.kind)}${stepped(m) ? " · " + stepped(m) : ""}</span></div>`).join("") + d.live.map((e) => `<div>live ${esc(e.issue)}: ${esc(e.title)}</div>`).join(""))}>${d.marks.length ? esc(d.marks.length) : ""}${d.live.length ? "◆" : ""}</b>`).join("")}</div></div>` : "";
    const gantt = marksRow + runs.filter((r) => r.pieces.some((p) => p.at)).map((r) => `<div class="grow"><span>${esc(r.name)}</span><div class="gtrack">${lines}${r.pieces.filter((p) => p.at).map((p) => `<i class="t${tone(r.ruleset)}" style="left:${100 * p.at[0]}%;width:${Math.max(0.5, 100 * (p.at[1] - p.at[0]))}%" title="${day(p.started_at)} to ${day(p.finished_at)}"></i>`).join("")}</div></div>`).join("");
    const logRows = [...C.log].reverse().map((m) => `<tr><td>${esc(m.date)}</td><td>#${esc(m.pr)}</td><td>${esc(m.kind)}</td><td>${stepped(m) || `<span class="sub">none stepped</span>`}</td><td><b>${esc(m.title)}</b><br><span class="sub">${esc(m.words)}</span></td><td>${m.takes_in.map(esc).join(", ")}</td></tr>`).join("");
    const liveRows = (C.engine || []).map((e) => `<tr><td>${esc(e.date)}</td><td>${esc(e.issue)}</td><td><b>${esc(e.title)}</b><br><span class="sub">${esc(e.words)}</span></td><td>${e.taken_in == null ? "not yet" : `version ${esc(e.taken_in)}${e.closed_by && e.closed_by !== "notes" ? ` <span class="sub">(${esc(e.closed_by)})</span>` : ""}`}</td></tr>`).join("");
    const looks = n ? n.looks.map((l) => `<tr><td><b>${esc(l.name)}</b></td><td>${esc(l.date)}</td><td>${esc(l.what)}</td><td>${esc(l.result)}</td><td>${esc(l.issue || "")}</td></tr>`).join("") : "";
    return `<p class="lede">Everything the simulator has recorded on the box. Long runs go in pieces between the live routines' quiet windows.</p>
      <section class="panel"><h2>Runs</h2>${rows ? `<div class="tablewrap"><table><tr><th>Run</th><th>Ruleset</th><th>Seasons</th><th class="n">Paths</th><th class="n">Pairs</th><th class="n">Cleared</th><th class="n">Box time</th><th>Audit</th><th>Capability</th><th>Code</th></tr>${rows}</table></div>
        <div class="gantt">${gantt}<div class="gaxis"><span>${day(span.start)}</span><span>${day(span.end)}</span></div></div>
        <p class="sub">A line on the time line is a day the simulator changed (its count of marks; tap it for what), a diamond a change to the live engine.</p>` : `<p class="empty">No run recorded.</p>`}</section>
      <section class="panel"><h2>The capability log</h2><p class="sub">Every change to what the simulator can do, newest first: its world, what the seat can do, a live rule it mirrors, how it counts. A version step without a mark fails the simulator's tests.</p>
        <div class="tablewrap"><table><tr><th>Date</th><th>PR</th><th>Kind</th><th>Versions</th><th>What changed</th><th>Takes in</th></tr>${logRows}</table></div>
        <h3>The live engine's changes</h3><p class="sub">From the lead's notes; a mark that takes one in closes it.</p>
        ${liveRows ? `<div class="tablewrap"><table><tr><th>Date</th><th>Issue</th><th>Change</th><th>Taken in</th></tr>${liveRows}</table></div>` : `<p class="empty">${C.noted ? "The notes list no live-engine change." : "No notes file."}</p>`}</section>
      <section class="panel"><h2>Short looks</h2><p class="sub">One path, one seed: never a finding.</p>${n ? `<div class="tablewrap"><table><tr><th>Look</th><th>Date</th><th>What</th><th>Result</th><th>Record</th></tr>${looks}</table></div>` : noNotes("The looks")}</section>
      <section class="panel"><h2>Traces</h2><p class="sub">One path of one pair, written day by day for the Season tab by the trace command (the lead runs it); the lab plays nothing. One path proves nothing.</p>${traceTable()}</section>
      ${M.tunes.length ? M.tunes.map(tuneTable).join("") : `<section class="panel"><h2>Tunes</h2><p class="sub">None recorded yet. Each tune will show its search, lever by lever, and its one confirmation on the unseen season.</p></section>`}`;
  }

  // ------------------------------------------------------------------ season, openings, explainer
  // The Season tab is season.js's: a trace played day by day (PR viewer).
  const seasonPage = () => `<p class="lede">${esc(M.viewer.words)}</p><div id="season-view" class="sv"></div>`;
  // The Screen tab is screen.js's: a screen as it is played (PR live screen).
  const screenPage = () => `<p class="lede">${esc(M.screen_view.words)}</p><div id="screen-view" class="sv"></div>`;
  function openingsPage() {
    const n = notes(), st = { asked: "word", planned: "ok" };
    const props = n ? n.proposals.map((p) => `<div class="item"><b>${esc(p.title)}</b><span class="badge">${esc(p.state || p.date)}</span><p>${esc(p.text)}</p></div>`).join("") : "";
    return `<p class="lede">Where the simulated world could change so the search has more to find, and what the sims support changing live. <b>Nothing is recommended until a tune confirms it.</b></p>
      <section class="panel"><h2>Proposals for the live settings</h2>${n ? props || `<p class="sub">None yet. Each proposal will carry its evidence (search gain, confirmation gain, checks) and wait for your ruling.</p>` : noNotes("The proposals")}</section>
      <section class="panel"><h2>Openings in the sim's world</h2>${n ? n.openings.map((o) => `<div class="item"><b>${esc(o.title)}</b><span class="badge ${st[o.state] || ""}">${o.state === "asked" ? "asked of you" : esc(o.state)}</span><p>${esc(o.why)}</p><span class="sub" style="text-align:right">${esc(o.cost || "")}</span></div>`).join("") || `<p class="empty">None yet.</p>` : noNotes("The openings")}</section>`;
  }
  const explainer = () => `<iframe class="exframe" src="/explainer" title="Season Sim Explained" referrerpolicy="no-referrer"></iframe>`;

  // ------------------------------------------------------------------ shell
  const PAGES = { results: ["Results", resultsPage], overview: ["Overview", overview], knobs: ["Knobs", knobs], checks: ["Checks", checksPage], runs: ["Runs", runsPage], season: ["Season", seasonPage], screen: ["Screen", screenPage], openings: ["Openings", openingsPage], explainer: ["Explainer", explainer] };
  let stale = null;
  // The first tab, Results, is the page a bare address opens (PR results tab).
  const pageKey = () => { const id = (location.hash || "#results").slice(1); return PAGES[id] ? id : "results"; };
  function header() {
    const s = M.notes && M.notes.state, g = M.generated;
    // The status text yields to the tabs: cut when the page is narrow, its full text on hover.
    const text = stale ? `${stale}; the page shows the last model` : s ? s.text : `no notes file · built ${day(g.at)}`;
    const el = document.getElementById("state");
    el.innerHTML = `<span class="dot ${stale ? "bad" : s && s.running ? "run" : ""}"></span><span class="st">${esc(text)}</span>`;
    el.title = text;
    topHeight();
  }
  // The top bar's height, for what sticks under it: it grows when the status text wraps under the tabs.
  function topHeight() { document.documentElement.style.setProperty("--toph", document.querySelector(".top").offsetHeight + "px"); }
  window.addEventListener("resize", topHeight);
  // keep: a redraw of the same tab after the model changed keeps the reader's scroll.
  function render(keep) {
    const key = pageKey(), y = window.scrollY;
    document.getElementById("nav").innerHTML = Object.entries(PAGES).map(([k, [t]]) => `<a href="#${k}" class="${k === key ? "on" : ""}">${t}</a>`).join("");
    header();
    TIPS.length = 0; tipEl.hidden = true;
    page.classList.toggle("bleed", key === "explainer");
    topHeight();
    page.innerHTML = PAGES[key][1]();
    if (window.SeasonView) { if (key === "season") window.SeasonView.mount(document.getElementById("season-view"), M); else window.SeasonView.stop(); }
    if (window.ScreenView) { if (key === "screen") window.ScreenView.mount(document.getElementById("screen-view"), M); else window.ScreenView.stop(); }
    if (keep) window.scrollTo(0, y);
  }
  function showTip(el, x, y) {
    tipEl.innerHTML = TIPS[+el.dataset.tip] || ""; tipEl.hidden = false;
    const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    tipEl.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x + 14)) + "px";
    tipEl.style.top = Math.max(8, Math.min(window.innerHeight - h - 8, y + 14)) + "px";
  }
  // A tap (or a click) on a row shows its tip; a tap elsewhere hides it. A mouse shows it on hover.
  page.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-k]");
    if (b) { K[b.dataset.k] = b.dataset.v; render(); return; }
    const sv = e.target.closest("button[data-sv]");
    if (sv && window.SeasonView) { window.SeasonView.act(sv.dataset.sv, sv.dataset.v); return; }
    const sc = e.target.closest("button[data-sc]");
    if (sc && window.ScreenView) { window.ScreenView.act(sc.dataset.sc, sc.dataset.v); return; }
    const tr = e.target.closest("a[data-trace]");
    if (tr && window.SeasonView) window.SeasonView.choose(tr.dataset.trace);
    const sn = e.target.closest("a[data-screen]");
    if (sn && window.ScreenView) window.ScreenView.choose(sn.dataset.screen);
    const el = e.target.closest("[data-tip]");
    if (el) showTip(el, e.clientX, e.clientY); else tipEl.hidden = true;
  });
  document.addEventListener("click", (e) => { if (!page.contains(e.target)) tipEl.hidden = true; });
  page.addEventListener("mousemove", (e) => {
    const el = e.target.closest("[data-tip]");
    if (el) showTip(el, e.clientX, e.clientY); else tipEl.hidden = true;
  });
  page.addEventListener("mouseleave", () => { tipEl.hidden = true; });
  page.addEventListener("input", (e) => {
    if (e.target.dataset && e.target.dataset.sv === "scrub" && window.SeasonView) window.SeasonView.act("scrub", e.target.value);
    if (e.target.dataset && e.target.dataset.sc === "scrub" && window.ScreenView) window.ScreenView.act("scrub", e.target.value);
  });
  page.addEventListener("change", (e) => {
    if (e.target.dataset && e.target.dataset.sv === "pick" && window.SeasonView) window.SeasonView.act("pick", e.target.value);
    if (e.target.dataset && e.target.dataset.sc === "pick" && window.ScreenView) window.ScreenView.act("pick", e.target.value);
  });
  window.addEventListener("hashchange", () => { if (M) render(); });
  // The model is read again about once a minute while the tab is visible, and the page is drawn
  // again only when the model was built again (the server keeps it until the records change).
  function load() {
    return fetch("/api/model", { cache: "no-store" })
      .then((r) => {
        if (r.ok) return r.json();
        return r.text().catch(() => "").then((t) => {
          throw new Error(r.status === 500 ? "The model could not be built" + (t.trim() ? " (" + t.trim() + ")" : "") : "The model answered " + r.status);
        });
      })
      .then((m) => {
        const was = stale; stale = null;
        if (M && m.generated.at === M.generated.at) { if (was) header(); return; }
        const first = !M; M = m;
        if (!first && pageKey() === "explainer") { header(); return; }
        // On the Season tab a new model changes the traces' list; the trace plays on.
        if (!first && pageKey() === "season" && window.SeasonView) { header(); window.SeasonView.list(M); return; }
        // On the Screen tab likewise: the picker's lines change; the screen's own poll moves it.
        if (!first && pageKey() === "screen" && window.ScreenView) { header(); window.ScreenView.list(M); return; }
        render(!first);
      })
      .catch((e) => {
        stale = e.message;
        if (M) header(); else page.innerHTML = `<section class="panel"><p class="empty">${esc(e.message)}.</p></section>`;
      });
  }
  setInterval(() => { if (document.visibilityState === "visible") load(); }, 60 * 1000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
  load();
})();
