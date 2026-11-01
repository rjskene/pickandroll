// The lineup executor's page side (#170, docs/AUTOPILOT.md section 2): what the team page's form
// shows, the checks every step passes on it, and the run the log takes. Pure but for ``setLineup``
// and its ``swapStep``: the content script (league.js) extracts the form into a plain object and
// calls these.
//
// A dry run reads the page and logs what it would set. A live run (PR 3) sets the lineup the way
// the IL move does (#214, lib/ilmove.js): per step, a click on the player's slot label starts
// Yahoo's swap and marks the rows he may go to (``tr.swaptarget``), and a click on the target
// row's label swaps the two and saves at once ("All changes saved"). Nothing here sets a field,
// submits the form or reads its crumb.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /** The fragments a run starts from: the routine's link and its late pass before the day's
   * first tip-off. Yahoo never sees a fragment. Any other visit only shows the strip. */
  const LINEUP_TRIGGERS = { "pickandroll-lineup": "routine", "pickandroll-lineup-late": "routine_late" };
  /** The slot codes the API's steps use. */
  const SLOT_CODES = new Set(["PG", "SG", "G", "SF", "PF", "F", "C", "Util", "BN", "IL", "IL+", "NA"]);
  const BENCH = "BN";
  /** The form's fields named by a Yahoo player id: a select for a movable player, a hidden input
   * for one whose game began. */
  const PLAYER_FIELD = /^\d+$/;

  /** The run's trigger from the page's fragment (``location.hash``), null when it has none. */
  function triggerOf(hash) {
    return LINEUP_TRIGGERS[String(hash || "").replace(/^#/, "")] || null;
  }

  /** An option's slot code: its value when that is a slot code, else its text. */
  function slotOf(option) {
    const value = String(option.value ?? "").trim();
    if (SLOT_CODES.has(value)) return value;
    const text = String(option.text ?? "").trim();
    return SLOT_CODES.has(text) ? text : value;
  }

  /** The form as the content script extracted it (``{action, method, editable, swap_method,
   * swap_labels, fields: [{name, tag, type, value, options}]}``, the crumb's value never read)
   * read into the page's lineup: each player's slot, the players whose game began (a hidden
   * field), each movable player's slots, the page's date, and the names of every other field. */
  function readControls(form) {
    const lineup = {};
    const locked = [];
    const options = {};
    const fields = [];
    let date = null;
    for (const f of form.fields || []) {
      if (PLAYER_FIELD.test(f.name)) {
        if (f.tag === "select") {
          const opts = f.options || [];
          const chosen = opts.find((o) => o.selected) || opts[0];
          lineup[f.name] = chosen ? slotOf(chosen) : "";
          options[f.name] = opts.map((o) => ({ slot: slotOf(o), value: o.value, text: o.text }));
        } else if (f.type === "hidden") {
          lineup[f.name] = String(f.value ?? "").trim();
          locked.push(Number(f.name));
        }
        continue;
      }
      fields.push(f.name);
      if (f.name === "date") date = f.value || null;
    }
    return {
      action: form.action || null,
      method: form.method || null,
      editable: form.editable ?? null,
      swap_method: form.swap_method ?? null,
      swap_labels: form.swap_labels ?? 0,
      date,
      lineup,
      locked,
      options,
      fields,
    };
  }

  /** Why the run may not use this page against ``steps``, null when it may: it must be the
   * league's team page for my team, its form the team's own editable lineup for the steps' day. */
  function pageProblem(page, controls, steps) {
    if (!page || page.kind !== "team") return "not a team page";
    if (page.league !== String(steps.league) || page.team !== steps.team) return "not my team's page";
    if (!controls) return "the page has no lineup form";
    if (controls.action !== `/nba/${steps.league}/${steps.team}/editroster`) return "the form is not my team's lineup";
    if (controls.method !== "post") return "the form does not post";
    if (controls.editable !== true) return "the page's lineup is not editable";
    if (controls.date !== steps.date) return `the page is for ${controls.date || "no day"}, the steps for ${steps.date}`;
    return null;
  }

  /** Whether the steps were built from this page's own post: their read is the post's time. */
  function sameRead(read, postedAt) {
    if (!read || !read.at || !Number.isFinite(postedAt)) return false;
    return Date.parse(read.at) === postedAt;
  }

  /** The players whose slot on the page is not the one the steps read, in words; null for none. */
  function lineupDiffers(controls, yahoo) {
    const keys = new Set([...Object.keys(controls.lineup), ...Object.keys(yahoo || {})]);
    const off = [...keys].filter((k) => controls.lineup[k] !== (yahoo || {})[k]);
    if (!off.length) return null;
    return `the page's lineup is not the one read (${off.length} player${off.length === 1 ? "" : "s"} differ)`;
  }

  /** What the page shows for player ``k``: his control, his slot and his options. */
  function controlOf(controls, k) {
    const key = String(k);
    if (!(key in controls.lineup)) return null;
    const locked = controls.locked.includes(Number(k));
    return {
      kind: locked ? "locked" : "select",
      slot: controls.lineup[key],
      options: locked ? [] : (controls.options[key] || []).map((o) => o.slot),
    };
  }

  /** Why ``step`` fails on the lineup as it stands (``lineup``, after the group's earlier steps),
   * null when it passes. ``slots`` are the league's starting slots. */
  function stepProblem(step, lineup, controls, slots, now) {
    const p = controlOf(controls, step.player);
    if (!p) return `player ${step.player} is not on the page`;
    if (p.kind === "locked") return `player ${step.player}'s game began (his slot is fixed)`;
    if (lineup[String(step.player)] !== step.from_slot) {
      return `player ${step.player} is in ${lineup[String(step.player)]} on the page, not ${step.from_slot}`;
    }
    if (!p.options.includes(step.to_slot)) return `${step.to_slot} is not among player ${step.player}'s slots`;
    if (step.tip && Date.parse(step.tip) <= now) return `player ${step.player}'s game began`;
    if (step.with != null) {
      const w = controlOf(controls, step.with);
      if (!w) return `player ${step.with} is not on the page`;
      if (w.kind === "locked") return `player ${step.with}'s game began (his slot is fixed)`;
      if (lineup[String(step.with)] !== step.to_slot) {
        return `player ${step.with} is in ${lineup[String(step.with)]} on the page, not ${step.to_slot}`;
      }
      if (!w.options.includes(step.from_slot)) return `${step.from_slot} is not among player ${step.with}'s slots`;
    } else if (step.to_slot !== BENCH) {
      const held = Object.values(lineup).filter((s) => s === step.to_slot).length;
      if (held >= slots.filter((s) => s === step.to_slot).length) return `no ${step.to_slot} is open on the page`;
    }
    return null;
  }

  /** Every step through the page's checks, a group at a time: a group whose step fails is
   * skipped whole, with that step's reason, and leaves the lineup as it was; the others are
   * applied in order. ``after`` is the lineup the passing groups leave. */
  function checkSteps(controls, steps, slots, now = Date.now()) {
    let lineup = { ...controls.lineup };
    const out = [];
    const groups = [];
    for (const s of steps) {
      const last = groups[groups.length - 1];
      if (last && last.group === s.group) last.steps.push(s);
      else groups.push({ group: s.group, steps: [s] });
    }
    for (const g of groups) {
      const trial = { ...lineup };
      let why = null;
      for (const s of g.steps) {
        why = stepProblem(s, trial, controls, slots, now);
        if (why) break;
        trial[String(s.player)] = s.to_slot;
        if (s.with != null) trial[String(s.with)] = s.from_slot;
      }
      if (!why) lineup = trial;
      for (const s of g.steps) {
        out.push({
          player: s.player,
          from_slot: s.from_slot,
          to_slot: s.to_slot,
          with: s.with ?? null,
          tip: s.tip ?? null,
          group: s.group ?? null,
          outcome: why ? "skipped" : "would_set",
          reason: why,
          control: controlOf(controls, s.player),
        });
      }
    }
    return { steps: out, after: lineup };
  }

  /** The select values the passing steps would set, by field name: each moved player's option
   * for his final slot. Nothing else on the form would change. */
  function planSelects(controls, checked) {
    const out = {};
    for (const [k, slot] of Object.entries(checked.after)) {
      if (controls.lineup[k] === slot || controls.locked.includes(Number(k))) continue;
      const o = (controls.options[k] || []).find((x) => x.slot === slot);
      out[k] = o ? o.value : null;
    }
    return out;
  }

  /** Where a run ends before any step: ``{outcome, reason, after}``, or null when its steps go on
   * to the page's checks. ``steps`` is the steps route's answer, ``problem`` why the page was not
   * used (null: it was). */
  function runEnd({ steps, postedAt, controls, problem = null, error = null }) {
    if (error) return { outcome: "failed", reason: error, after: null };
    if (steps.stop) return { outcome: "stopped", reason: "STOP is on (data/autopilot/STOP)", after: null };
    if (!steps.open || !steps.read) return { outcome: "skipped", reason: steps.reason || "the day takes no changes", after: null };
    if (!sameRead(steps.read, postedAt)) return { outcome: "skipped", reason: "the steps were not built from this page's own post", after: null };
    if (problem) return { outcome: "skipped", reason: problem, after: null };
    const differs = lineupDiffers(controls, steps.yahoo);
    if (differs) return { outcome: "skipped", reason: differs, after: null };
    if (!steps.steps.length && !(steps.returns || []).length) return { outcome: "nothing_to_do", reason: steps.reason, after: controls.lineup };
    return null;
  }

  /** The run's mode: live only where the league is live and its guard holds now (``steps.live``,
   * checked on every steps request); otherwise a dry run, with why live was refused. */
  function lineupMode(steps) {
    if (steps.mode !== "live") return { mode: "dry_run", refused: null };
    if (steps.live && steps.live.ok) return { mode: "live", refused: null };
    return { mode: "dry_run", refused: `live refused: ${(steps.live && steps.live.reason) || "the guard did not answer"}` };
  }

  function runBase({ steps, trigger, page, controls, checked = null, mode = "dry_run", extension = null }) {
    return {
      day: steps.date,
      mode,
      trigger,
      page,
      read_at: steps.read ? steps.read.at : null,
      steps: [],
      skipped: steps.skipped || [],
      controls: controls
        ? {
            action: controls.action,
            method: controls.method,
            editable: controls.editable,
            swap_method: controls.swap_method,
            swap_labels: controls.swap_labels,
            fields: controls.fields,
            players: Object.keys(controls.lineup).length,
            would_set: checked ? planSelects(controls, checked) : {},
          }
        : null,
      before: controls ? controls.lineup : null,
      after: null,
      locked: controls ? controls.locked : [],
      message: null,
      extension,
    };
  }

  /** The run the log takes (the API's ``LineupRun``). ``steps`` is the steps route's answer,
   * ``problem`` why the page was not used (null: it was), ``checked`` ``checkSteps``' answer. A dry
   * run sets nothing, whatever the league's mode; ``refused`` says why a live league ran dry.
   * ``mode`` is "live" only for a live run that ended before any step (``runEnd``). */
  function dryRun({ steps, trigger, page, postedAt, controls, problem = null, checked = null, error = null, extension = null, refused = null, mode = "dry_run" }) {
    const base = runBase({ steps, trigger, page, controls, checked, mode, extension });
    const end = runEnd({ steps, postedAt, controls, problem, error });
    if (end) return { ...base, ...end };
    // Returns alone are a live run's: a dry run has nothing to do.
    if (!steps.steps.length) return { ...base, outcome: "nothing_to_do", reason: steps.reason, after: controls.lineup };
    const would = checked.steps.filter((s) => s.outcome === "would_set").length;
    return {
      ...base,
      steps: checked.steps,
      after: checked.after,
      outcome: would ? "would_set" : "skipped",
      reason: would ? refused : "every step failed a check on the page",
    };
  }

  // ---------------------------------------------------------------- the live run (PR 3)
  /** Yahoo's swap controls, the IL move's (#214): the roster rows, a row's slot label, the save
   * notice; how long a step waits for its target to show after the first click, for the save after
   * the second, and for an open swap to close (Yahoo keeps the saved row marked past its notice,
   * #288); a live run on record whose log never came is logged by the next visit. */
  const ROWS = "table[id^=statTable] tbody tr";
  const LABEL = "span.pos-label";
  const SAVED = ".rostersave-msg";
  const SHOW_MS = 5 * 1000;
  const SAVE_MS = 10 * 1000;
  const SETTLE_MS = 3 * 1000;
  const UNREAD_MS = 60 * 1000;
  const ALERTS_ATTR = "data-pickandroll-alerts";
  /** A cleared held player whose comeback needs a drop is the moves queue's (#124). */
  const NEEDS_DROP = "needs a drop: the comeback is the moves queue's";

  const visible = (el) => typeof el.getClientRects === "function" && el.getClientRects().length > 0;
  const squash = (s) => String(s ?? "").replace(/\s+/g, " ").trim();
  const idOf = (tr) => {
    const el = tr.querySelector("[data-ys-playerid]");
    return el ? Number(el.getAttribute("data-ys-playerid")) : null;
  };
  const shownIn = (tr) => [...tr.querySelectorAll(LABEL)].filter(visible);

  function alertsOf(doc) {
    let kept;
    try {
      kept = JSON.parse((doc.documentElement && doc.documentElement.getAttribute(ALERTS_ATTR)) || "[]");
    } catch (_) {
      kept = [];
    }
    return Array.isArray(kept) ? kept.map(String) : [];
  }

  /** The lineup as the swap labels show it: each player's slot by his row's one visible label
   * (null when it shows none or two), the players whose row takes no swap (not editable, or its
   * label not a button), whether a player shows twice, whether a swap is open, and whether an
   * empty editable row has a bench label. */
  function readLabels(doc) {
    const lineup = {};
    const fixed = [];
    let twice = false;
    let swapping = false;
    let bench = false;
    for (const tr of [...doc.querySelectorAll(ROWS)]) {
      if (tr.classList.contains("swapactive")) swapping = true;
      const k = idOf(tr);
      const editable = tr.classList.contains("editable");
      if (k == null) {
        if (editable && [...tr.querySelectorAll(LABEL)].some((l) => l.getAttribute("data-pos") === BENCH)) bench = true;
        continue;
      }
      const shown = shownIn(tr);
      if (String(k) in lineup) twice = true;
      lineup[String(k)] = shown.length === 1 ? shown[0].getAttribute("data-pos") : null;
      if (!editable || shown.length !== 1 || shown[0].getAttribute("role") !== "button") fixed.push(k);
    }
    return { lineup, fixed, twice, swapping, bench };
  }

  /** One step's two clicks, once each: the player's slot label, then, once the swap marks it, the
   * label of the row he goes to (``with``'s row, or an empty row of ``to_slot``); then Yahoo's save
   * with both players landed. Every check is read again before each click. A first click whose
   * target never shows is cancelled by a click on the player's own label (no row's target: Yahoo
   * leaves the swap, nothing saved). A swap open on the page is waited out first, up to
   * ``settleCap``, and again after the save. Only a notice that came or changed after the click is
   * this step's save: one that showed before it, unchanged, is an earlier step's (#288); when no
   * other comes, the swap is set only once the labels landed and no error came in the whole save
   * window, and the reason says so. Answers ``{outcome, reason, message}``: ``skipped`` when
   * nothing was clicked, ``set`` once saved, ``failed`` after a click. */
  async function swapStep(doc, step, { wait = (ms) => new Promise((r) => setTimeout(r, ms)), every = 200, showCap = SHOW_MS, saveCap = SAVE_MS, settleCap = SETTLE_MS } = {}) {
    const rows = () => [...doc.querySelectorAll(ROWS)];
    const rowOf = (k) => {
      const m = rows().filter((tr) => idOf(tr) === k);
      return m.length === 1 ? m[0] : null;
    };
    const labelOf = (tr) => {
      const s = tr ? shownIn(tr) : [];
      return s.length === 1 ? s[0] : null;
    };
    const posOf = (k) => {
      const l = labelOf(rowOf(k));
      return l ? l.getAttribute("data-pos") : null;
    };
    const start = () => {
      const tr = rowOf(step.player);
      const l = labelOf(tr);
      if (!l || !tr.classList.contains("editable") || l.getAttribute("role") !== "button" || l.getAttribute("data-pos") !== step.from_slot) return null;
      return l;
    };
    const target = () => {
      if (step.with != null) {
        const tr = rowOf(step.with);
        const l = labelOf(tr);
        return l && tr.classList.contains("editable") && tr.classList.contains("swaptarget") && l.getAttribute("data-pos") === step.to_slot ? l : null;
      }
      const empty = rows()
        .filter((tr) => idOf(tr) == null && tr.classList.contains("editable"))
        .flatMap((tr) => shownIn(tr).filter((l) => l.getAttribute("data-pos") === step.to_slot));
      return empty[0] || null;
    };
    const notice = () =>
      [...doc.querySelectorAll(SAVED)]
        .filter(visible)
        .map((el) => ({ el, saved: el.classList.contains("saved"), error: /error|fail/i.test(el.className), text: squash(el.textContent), sig: `${el.className}|${squash(el.textContent)}` }))
        .filter((n) => n.text);
    const landed = () => posOf(step.player) === step.to_slot && (step.with == null || posOf(step.with) === step.from_slot);
    const swapping = () => rows().some((tr) => tr.classList.contains("swapactive"));
    const cancel = () => {
      const tr = rowOf(step.player);
      const l = labelOf(tr);
      if (!l || !tr.classList.contains("swapactive")) return "";
      l.click();
      return "; the swap was cancelled";
    };
    const settle = async () => {
      for (let waited = 0; waited < settleCap && swapping(); waited += every) await wait(every);
    };
    await settle();
    if (swapping()) return { outcome: "skipped", reason: `a swap is open on the page (still after ${Math.round(settleCap / 1000)} s)`, message: null };
    const label = start();
    if (!label) return { outcome: "skipped", reason: `player ${step.player}'s label is not one visible button reading ${step.from_slot} in an editable row`, message: null };
    const before = alertsOf(doc).length;
    const yahoo = () => alertsOf(doc).slice(before);
    // The notices showing before the click, by element: one counts again only once it went away or
    // changed.
    const earlier = new Map(notice().map((n) => [n.el, n.sig]));
    const changed = new Set();
    const fresh = () => {
      const now = notice();
      const shown = new Map(now.map((n) => [n.el, n.sig]));
      for (const [el, sig] of earlier) if (shown.get(el) !== sig) changed.add(el);
      return now.filter((n) => !earlier.has(n.el) || changed.has(n.el));
    };
    label.click();
    let to = target();
    for (let waited = 0; waited < showCap && !to && !yahoo().length; waited += every) {
      await wait(every);
      to = target();
    }
    if (yahoo().length) return { outcome: "failed", reason: `Yahoo answered the first click: "${yahoo()[0]}"${cancel()}`, message: null };
    const where = step.with != null ? `player ${step.with}'s ${step.to_slot}` : `an empty ${step.to_slot}`;
    if (!to) return { outcome: "failed", reason: `${where} did not show as a target within ${Math.round(showCap / 1000)} s (nothing saved${cancel()})`, message: null };
    // Read again: the same label, its row a target still.
    if (target() !== to) return { outcome: "failed", reason: `${where} changed before its click (nothing saved${cancel()})`, message: null };
    to.click();
    for (let waited = 0; waited < saveCap; waited += every) {
      await wait(every);
      if (yahoo().length) return { outcome: "failed", reason: `Yahoo answered the swap: "${yahoo()[0]}"`, message: null };
      const got = fresh();
      const error = got.find((n) => n.error);
      if (error) return { outcome: "failed", reason: "Yahoo did not save the swap", message: error.text };
      const saved = got.find((n) => n.saved);
      if (saved && landed()) {
        await settle();
        return { outcome: "set", reason: null, message: saved.text };
      }
    }
    const kept = notice().find((n) => n.saved && earlier.get(n.el) === n.sig && !changed.has(n.el));
    if (kept && landed()) {
      await settle();
      return { outcome: "set", reason: `the save notice did not change; no error in ${Math.round(saveCap / 1000)} s`, message: kept.text };
    }
    return { outcome: "failed", reason: `clicked; the save was not read in ${Math.round(saveCap / 1000)} s`, message: null };
  }

  /** The page's controls with the lineup and the fixed players as the swap labels show them now:
   * a swap saves through Yahoo's script, and the form's selects need not follow it. */
  function liveControls(controls, labels) {
    return { ...controls, lineup: labels.lineup, locked: [...new Set([...controls.locked, ...labels.fixed])] };
  }

  /** The units a live run takes in order: each cleared held player's return to the bench first
   * (``returns``), then the steps' groups. */
  function unitsOf(steps, returns) {
    const out = returns.map((r) => ({
      kind: "return",
      steps: [{ player: r.player, from_slot: r.slot, to_slot: BENCH, with: null, tip: r.tip ?? null, group: null, kind: "return" }],
    }));
    for (const s of steps) {
      const last = out[out.length - 1];
      if (last && last.kind === "swap" && last.group === s.group) last.steps.push(s);
      else out.push({ kind: "swap", group: s.group, steps: [s] });
    }
    return out;
  }

  /** The live run's steps on the page, a unit at a time (``unitsOf``). Before every unit: STOP, the
   * brake and the league's live guard read again (``stopNow``; a reason stops the run), and every
   * step of it through ``checkSteps`` on the page as the labels show it now: a unit that fails a
   * check is skipped whole, nothing clicked, and the run goes on. Before each click the step is
   * checked again. A step that fails after a click stops the run: the rest is skipped. A return
   * with no empty bench row is skipped (``NEEDS_DROP``). Answers ``{steps, outcome, reason,
   * after}``: each step with its outcome, reason and Yahoo's words; the run's outcome (``set``,
   * ``failed``, ``stopped`` or ``skipped``) and the lineup the labels show after it. */
  async function setLineup(doc, { controls, steps, returns = [], slots }, { stopNow = async () => null, now = () => Date.now(), ...opts } = {}) {
    const out = [];
    const record = (s, outcome, reason, message = null) =>
      out.push({
        player: s.player,
        from_slot: s.from_slot,
        to_slot: s.to_slot,
        with: s.with ?? null,
        tip: s.tip ?? null,
        group: s.group ?? null,
        kind: s.kind || "swap",
        outcome,
        reason,
        message,
        control: controlOf(controls, s.player),
      });
    const units = unitsOf(steps, returns);
    let failed = null;
    let stopped = null;
    let done = 0;
    let skipped = 0;
    for (const u of units) {
      // Read again before every unit, the first included: a click never rests on the steps the
      // run started from.
      if (!failed && !stopped) stopped = await stopNow();
      if (failed || stopped) {
        for (const s of u.steps) record(s, "skipped", failed ? "the run stopped at a failed step" : stopped);
        continue;
      }
      const labels = readLabels(doc);
      if (u.kind === "return" && !labels.bench) {
        for (const s of u.steps) record(s, "skipped", NEEDS_DROP);
        skipped += 1;
        continue;
      }
      const checked = checkSteps(liveControls(controls, labels), u.steps, slots, now());
      const refused = checked.steps.find((s) => s.outcome === "skipped");
      if (labels.twice || refused) {
        for (const s of u.steps) record(s, "skipped", labels.twice ? "a player shows twice on the page" : refused.reason);
        skipped += 1;
        continue;
      }
      let clicked = false;
      for (const s of u.steps) {
        if (failed) {
          record(s, "skipped", "an earlier step of its group failed");
          continue;
        }
        const page = liveControls(controls, readLabels(doc));
        const why = stepProblem(s, page.lineup, page, slots, now());
        const got = why ? { outcome: "skipped", reason: why, message: null } : await swapStep(doc, s, opts);
        if (got.outcome === "set") {
          record(s, "set", got.reason, got.message);
          clicked = true;
        } else if (got.outcome === "skipped" && !clicked) {
          // Nothing of the unit was clicked: skipped whole, the run goes on.
          record(s, "skipped", got.reason, got.message);
          for (const rest of u.steps.slice(u.steps.indexOf(s) + 1)) record(rest, "skipped", "an earlier step of its group was skipped");
          skipped += 1;
          break;
        } else {
          record(s, "failed", got.reason, got.message);
          failed = got.reason;
        }
      }
      if (!failed && clicked && out.slice(-u.steps.length).every((s) => s.outcome === "set")) done += 1;
    }
    const after = readLabels(doc).lineup;
    const n = units.length;
    const sets = `${done} of ${n} ${n === 1 ? "change" : "changes"} set`;
    if (failed) return { steps: out, outcome: "failed", reason: `${failed} (${sets} first)`, after };
    if (stopped) return { steps: out, outcome: "stopped", reason: `${stopped} (${sets} first)`, after };
    if (!done) {
      const first = out.find((s) => s.reason);
      return { steps: out, outcome: "skipped", reason: first ? first.reason : "every step failed a check on the page", after };
    }
    return { steps: out, outcome: "set", reason: skipped ? `${sets}; ${out.find((s) => s.outcome === "skipped").reason}` : null, after };
  }

  /** The live run the log takes: ``result`` is ``setLineup``'s answer. ``diff`` is each player the
   * steps move whose slot after the run is not his target, by the labels; ``messages`` Yahoo's save
   * words; ``after_start_active`` whether the league's Start Active press of the day came before
   * this page's read. */
  function liveRun({ steps, trigger, page, controls, checked, result, afterStartActive = null, extension = null }) {
    const base = runBase({ steps, trigger, page, controls, checked, mode: "live", extension });
    const target = { ...(steps.target || {}) };
    for (const r of steps.returns || []) target[String(r.player)] = BENCH;
    let diff = null;
    if (result.after) {
      diff = {};
      for (const [k, slot] of Object.entries(target)) if (result.after[k] !== slot) diff[k] = result.after[k] ?? null;
    }
    const messages = [...new Set(result.steps.map((s) => s.message).filter(Boolean))];
    return {
      ...base,
      steps: result.steps,
      after: result.after,
      outcome: result.outcome,
      reason: result.reason,
      diff,
      message: messages.join(" · ") || null,
      after_start_active: afterStartActive,
    };
  }

  /** A live run on record whose log never came, as the next visit logs it: clicked, its answer not
   * read; never run again by the same pass. */
  function unreadLineup(record, extension) {
    return {
      day: record.day,
      mode: "live",
      trigger: record.trigger,
      outcome: "failed",
      reason: "clicked; Yahoo's answer was not read",
      page: record.page || null,
      read_at: record.read_at || null,
      steps: [],
      skipped: [],
      controls: null,
      before: null,
      after: null,
      locked: [],
      message: null,
      extension,
    };
  }

  /** Why a live run waits for the league's Start Active press (#215), null when it may go on:
   * ``row`` is the league's row of the Start Active due (its need and mode), ``record`` the press
   * on record in this browser, ``day`` the due's date and ``postedAt`` this page's read. A press
   * due today must have been logged before this page was read: the press resets the lineup. */
  function startActiveWait(row, record, day, postedAt) {
    const pressed = record && record.day === day && record.logged;
    if (pressed && record.at >= postedAt) return "Start Active Players pressed after this page was read: the next pass reads it again";
    if (pressed || !row || !row.need) return null;
    if (row.mode !== "live" || !(row.live && row.live.ok)) return null;
    return "Start Active Players is due in this league first: the lineup waits for its press";
  }

  /** "05:02", a time on this machine's clock. */
  function clock(at) {
    const d = new Date(at);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  const MODE_WORDS = { dry_run: "dry run", live: "live", off: "off" };

  /** The strip's line on the team page: the brake, the league's mode and STOP; a run's outcome
   * (``run``, with its time ``at``), or what a run would do when the visit started none. */
  function stripText({ browserOff = false, steps = null, run = null, at = Date.now(), error = null }) {
    if (browserOff) return "off in this browser (the extension's settings)";
    if (error) return `not reached: ${error}`;
    if (!steps) return "reading the steps…";
    if (steps.mode === "off") return "off in this league";
    if (steps.stop) return "STOP is on: nothing runs";
    const mode = MODE_WORDS[run ? run.mode : steps.mode] || steps.mode;
    if (run) {
      const n = run.steps.filter((s) => s.outcome === "would_set").length;
      const set = run.steps.filter((s) => s.outcome === "set").length;
      if (run.outcome === "would_set") return `${mode} · ${n} move${n === 1 ? "" : "s"} logged ${clock(at)}${run.reason ? ` (${run.reason})` : ""}`;
      if (run.outcome === "set") return `${mode} · ${set} swap${set === 1 ? "" : "s"} set ${clock(at)}${run.reason ? ` (${run.reason})` : ""}`;
      if (run.outcome === "stopped") return `${mode} · stopped: ${run.reason} (${clock(at)})`;
      if (run.outcome === "nothing_to_do") return `${mode} · nothing to do, logged ${clock(at)}`;
      return `${mode} · ${run.outcome === "failed" ? "failed" : "skipped"}: ${run.reason} (${clock(at)})`;
    }
    if (!steps.open || !steps.read) return `${mode} · ${steps.reason || "the day takes no changes"}`;
    const n = steps.steps.length;
    if (!n) return `${mode} · ${steps.reason || "nothing to do"}`;
    const verb = lineupMode(steps).mode === "live" ? "set" : "log";
    return `${mode} · a run would ${verb} ${n} move${n === 1 ? "" : "s"} (the routine's link or the side panel runs it)`;
  }

  const OUTCOME_WORDS = {
    would_set: "would set",
    nothing_to_do: "nothing to do",
    skipped: "skipped",
    set: "set",
    failed: "failed",
    stopped: "stopped by STOP",
  };
  const TRIGGER_WORDS = { routine: "routine", routine_late: "late routine", panel: "side panel" };

  /** The panel's line for the league's last run from this browser (the worker keeps it): "2026-10-24
   * · side panel: would set 2 moves, 3 min ago". ``when`` is its age in words. */
  function lastRunText(last, when) {
    if (!last) return "no run from this browser yet";
    const n = last.moves || 0;
    const moves = ["would_set", "set"].includes(last.outcome) ? ` ${n} move${n === 1 ? "" : "s"}` : "";
    const why = last.reason ? ` (${last.reason})` : "";
    return `${last.day} · ${TRIGGER_WORDS[last.trigger] || last.trigger}: ${OUTCOME_WORDS[last.outcome] || last.outcome}${moves}${why}, ${when}`;
  }

  return {
    LINEUP_TRIGGERS,
    triggerOf,
    slotOf,
    readControls,
    pageProblem,
    sameRead,
    lineupDiffers,
    checkSteps,
    planSelects,
    runEnd,
    lineupMode,
    dryRun,
    LINEUP_ROWS: ROWS,
    LINEUP_LABEL: LABEL,
    LINEUP_SAVED: SAVED,
    LINEUP_UNREAD_MS: UNREAD_MS,
    NEEDS_DROP,
    readLabels,
    swapStep,
    setLineup,
    liveRun,
    unreadLineup,
    startActiveWait,
    stripText,
    lastRunText,
  };
});
