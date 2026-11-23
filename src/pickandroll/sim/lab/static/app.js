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
    return `<div class="stage ${s.ghost ? "ghost" : ""}"><span class="tag">${esc(s.tag)}</span><span class="k">${esc(s.title)}</span><b>${big}</b><small>${small}</small></div>`;
  }
  const stages = (x) => `<div class="rsname c${x.tone % 4}">${esc(x.name)} · ${esc(O(x.measure).label.toLowerCase())}</div><div class="stages">${x.stages.map((s) => stage(s, x.measure)).join("")}</div>`;
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
    return `<p class="lede">Every change the screens tried, B (the change) against A (the baseline) on the same simulated seasons. A dot is the change's effect; its bar is one SE either side, the thin line two. <b>Right is better for the seat.</b></p>
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
          <tr><th>Season</th><th>Role</th><th class="n">Screens</th><th class="n">Searches</th><th class="n">Confirmations</th><th class="n">Replays</th><th class="n">Looks</th><th>Note</th></tr>
          ${M.seasons.map((s) => `<tr><td><b>${esc(s.words)}</b></td><td><span class="role ${esc(s.role)}">${esc(roleName[s.role] || s.role)}</span></td><td class="n">${esc(s.screens)}</td><td class="n">${esc(s.searches)}</td><td class="n">${esc(s.confirmations)}</td><td class="n">${esc(s.replays)}</td><td class="n">${esc(s.looks)}</td><td class="sub">${esc(s.note || "")}${s.from === "notes" ? "" : ` (from the ${esc(s.from)})`}</td></tr>`).join("")}
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
  function runsPage() {
    const runs = M.runs, n = notes();
    const rows = runs.map((r) => {
      const x = ruleset(r.ruleset);
      return `<tr><td><b>${esc(r.name)}</b><br><span class="sub">${esc(r.kind)}${r.design ? " · " + esc(r.design) : ""}</span></td><td><span class="c${tone(r.ruleset)}">${esc(x ? x.name : r.ruleset)}</span></td>
      <td>${r.season_words.map(esc).join(", ") || "n/a"}<br><span class="sub">${esc(r.forecasters)}</span></td><td class="n">${esc(r.paths)}<br><span class="sub">seed ${esc(r.seed)}</span></td>
      <td class="n">${esc(r.pairs_done)}${r.pairs_left ? " · " + esc(r.pairs_left) + " left" : ""}<br><span class="sub">${esc(r.not_played)} not played</span></td><td class="n">${esc(r.cleared)}</td>
      <td class="n">${isNum(r.hours) ? fx(r.hours, 1) + " h" : "n/a"}<br><span class="sub">${r.pieces.length} piece(s)</span></td><td>${levelBadge(r.audit.level)}<br><span class="sub">${esc(r.audit.breaches)} breaches, ${esc(r.audit.voided)} voided</span></td><td><code>${esc(r.code_sha || "")}</code><br><span class="sub">${esc(r.status)}</span></td></tr>`;
    }).join("");
    const span = M.timeline || {};
    const gantt = runs.filter((r) => r.pieces.some((p) => p.at)).map((r) => `<div class="grow"><span>${esc(r.name)}</span><div class="gtrack">${r.pieces.filter((p) => p.at).map((p) => `<i class="t${tone(r.ruleset)}" style="left:${100 * p.at[0]}%;width:${Math.max(0.5, 100 * (p.at[1] - p.at[0]))}%" title="${day(p.started_at)} to ${day(p.finished_at)}"></i>`).join("")}</div></div>`).join("");
    const looks = n ? n.looks.map((l) => `<tr><td><b>${esc(l.name)}</b></td><td>${esc(l.date)}</td><td>${esc(l.what)}</td><td>${esc(l.result)}</td><td>${esc(l.issue || "")}</td></tr>`).join("") : "";
    return `<p class="lede">Everything the simulator has recorded on the box. Long runs go in pieces between the live routines' quiet windows.</p>
      <section class="panel"><h2>Runs</h2>${rows ? `<div class="tablewrap"><table><tr><th>Run</th><th>Ruleset</th><th>Seasons</th><th class="n">Paths</th><th class="n">Pairs</th><th class="n">Cleared</th><th class="n">Box time</th><th>Audit</th><th>Code</th></tr>${rows}</table></div>
        <div class="gantt">${gantt}<div class="gaxis"><span>${day(span.start)}</span><span>${day(span.end)}</span></div></div>` : `<p class="empty">No run recorded.</p>`}</section>
      <section class="panel"><h2>Short looks</h2><p class="sub">One path, one seed: never a finding.</p>${n ? `<div class="tablewrap"><table><tr><th>Look</th><th>Date</th><th>What</th><th>Result</th><th>Record</th></tr>${looks}</table></div>` : noNotes("The looks")}</section>
      ${M.tunes.length ? M.tunes.map(tuneTable).join("") : `<section class="panel"><h2>Tunes</h2><p class="sub">None recorded yet. Each tune will show its search, lever by lever, and its one confirmation on the unseen season.</p></section>`}`;
  }

  // ------------------------------------------------------------------ season, openings, explainer
  const seasonPage = () => `<section class="panel"><h2>${esc(M.viewer.title)}</h2><p class="sub">${esc(M.viewer.words)}</p></section>`;
  function openingsPage() {
    const n = notes(), st = { asked: "word", planned: "ok" };
    const props = n ? n.proposals.map((p) => `<div class="item"><b>${esc(p.title)}</b><span class="badge">${esc(p.state || p.date)}</span><p>${esc(p.text)}</p></div>`).join("") : "";
    return `<p class="lede">Where the simulated world could change so the search has more to find, and what the sims support changing live. <b>Nothing is recommended until a tune confirms it.</b></p>
      <section class="panel"><h2>Proposals for the live settings</h2>${n ? props || `<p class="sub">None yet. Each proposal will carry its evidence (search gain, confirmation gain, checks) and wait for your ruling.</p>` : noNotes("The proposals")}</section>
      <section class="panel"><h2>Openings in the sim's world</h2>${n ? n.openings.map((o) => `<div class="item"><b>${esc(o.title)}</b><span class="badge ${st[o.state] || ""}">${o.state === "asked" ? "asked of you" : esc(o.state)}</span><p>${esc(o.why)}</p><span class="sub" style="text-align:right">${esc(o.cost || "")}</span></div>`).join("") || `<p class="empty">None yet.</p>` : noNotes("The openings")}</section>`;
  }
  const explainer = () => `<iframe class="exframe" src="/explainer" title="Season Sim Explained" referrerpolicy="no-referrer"></iframe>`;

  // ------------------------------------------------------------------ shell
  const PAGES = { overview: ["Overview", overview], knobs: ["Knobs", knobs], checks: ["Checks", checksPage], runs: ["Runs", runsPage], season: ["Season", seasonPage], openings: ["Openings", openingsPage], explainer: ["Explainer", explainer] };
  let stale = null;
  const pageKey = () => { const id = (location.hash || "#overview").slice(1); return PAGES[id] ? id : "overview"; };
  function header() {
    const s = M.notes && M.notes.state, g = M.generated;
    const line = s ? `<span class="dot ${s.running ? "run" : ""}"></span>${esc(s.text)}` : `<span class="dot"></span>no notes file · built ${day(g.at)}`;
    document.getElementById("state").innerHTML = stale ? `<span class="dot bad"></span>${esc(stale)}; the page shows the last model` : line;
  }
  // keep: a redraw of the same tab after the model changed keeps the reader's scroll.
  function render(keep) {
    const key = pageKey(), y = window.scrollY;
    document.getElementById("nav").innerHTML = Object.entries(PAGES).map(([k, [t]]) => `<a href="#${k}" class="${k === key ? "on" : ""}">${t}</a>`).join("");
    header();
    TIPS.length = 0; tipEl.hidden = true;
    page.classList.toggle("bleed", key === "explainer");
    document.documentElement.style.setProperty("--toph", document.querySelector(".top").offsetHeight + "px");
    page.innerHTML = PAGES[key][1]();
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
    const el = e.target.closest("[data-tip]");
    if (el) showTip(el, e.clientX, e.clientY); else tipEl.hidden = true;
  });
  document.addEventListener("click", (e) => { if (!page.contains(e.target)) tipEl.hidden = true; });
  page.addEventListener("mousemove", (e) => {
    const el = e.target.closest("[data-tip]");
    if (el) showTip(el, e.clientX, e.clientY); else tipEl.hidden = true;
  });
  page.addEventListener("mouseleave", () => { tipEl.hidden = true; });
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
