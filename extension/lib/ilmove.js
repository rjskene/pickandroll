// The IL move an open-spot claim needs first (#214, docs/AUTOPILOT.md section 2): on my team page
// opened with an IL fragment, the ``il_first`` item of the moves executor's due whose page this is,
// the swap controls as Yahoo drew them (step 0's read on #214, 2026-10-27), and the run the log
// takes. Pure but for ``moveToIL``, the one step that clicks: the content script (league.js) reads
// the page into a plain object and calls these.
//
// What a move is (step 0): a click on the player's slot label starts Yahoo's swap; a click on the
// empty IL row's label, which shows once the swap starts, saves at once (Yahoo's own post of the
// roster) and the page says "All changes saved". There is no Save step: the hidden Save button and
// the hidden fallback selects are never touched. A dry run clicks nothing.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /** The fragments a move starts from on my team page, and the moves fragment the tab then goes to
   * the entry's add page with (the ruling on #214: the claim reads the page after the move). */
  const IL_TRIGGERS = {
    "pickandroll-il": "routine",
    "pickandroll-il-late": "routine_late",
    "pickandroll-il-evening": "routine_evening",
    "pickandroll-il-panel": "panel",
  };
  const IL_THEN = {
    routine: "pickandroll-moves",
    routine_late: "pickandroll-moves-late",
    routine_evening: "pickandroll-moves-evening",
    panel: "pickandroll-moves-panel",
  };
  const IL_SLOTS = ["IL", "IL+"];
  /** Yahoo's swap controls (step 0): the manager, a row's slot label, the empty rows, the save
   * notice. */
  const IL_MANAGER = "section.ysf-rosterswap-manager";
  const IL_ROWS = "table[id^=statTable] tbody tr";
  const IL_LABEL = "span.pos-label";
  const IL_SAVED = ".rostersave-msg";
  /** How long the run waits for the IL row's label after the first click, and for Yahoo's save
   * after the second. */
  const IL_SHOW_MS = 5 * 1000;
  const IL_SAVE_MS = 10 * 1000;
  /** A move on record whose run was not logged within this is logged by the next visit. */
  const IL_UNREAD_MS = 60 * 1000;
  const IL_ALERTS_ATTR = "data-pickandroll-alerts";

  /** The move's trigger from the page's fragment (``location.hash``), null when it has none. */
  function ilTriggerOf(hash) {
    return IL_TRIGGERS[String(hash || "").replace(/^#/, "")] || null;
  }

  const pathOf = (url) => {
    try {
      const u = new URL(url, "https://basketball.fantasysports.yahoo.com");
      return u.pathname + u.search;
    } catch (_) {
      return null;
    }
  };

  /** The ``il_first`` item of ``due`` (GET /seasons/{league}/autopilot/moves/due) whose team page
   * is ``path`` (this page's path and query: my team, the item's date), null when none. */
  function ilItemFor(due, path) {
    return (due.il_first || []).find((x) => x.page && pathOf(x.page) === path) || null;
  }

  /** The swap controls as the content script read them (``{path, editable, rows: [{player,
   * editable, labels: [{pos, button, visible}]}]}``) into what the run checks and logs for
   * ``item``: the player's rows, his slot, whether his label is one visible button in an editable
   * row, and the empty rows of the item's slot. */
  function readILPage(raw, item) {
    const rows = raw.rows || [];
    const mine = rows.filter((r) => r.player === item.player);
    const shown = mine.length === 1 ? mine[0].labels.filter((l) => l.visible) : [];
    const empty = rows.filter((r) => r.player == null && r.empty && r.editable && r.labels.some((l) => l.pos === item.slot));
    return {
      path: raw.path || null,
      editable: raw.editable === true,
      rows: mine.length,
      from_slot: shown.length === 1 ? shown[0].pos : null,
      movable: mine.length === 1 && mine[0].editable && shown.length === 1 && shown[0].button,
      targets: empty.length,
    };
  }

  /** Why the move may not be made on this page, null when it may. */
  function ilProblem(item, controls) {
    if (!controls.editable) return "the roster is not editable on this page";
    if (controls.rows !== 1) return controls.rows ? "the player shows more than once on this page" : "the player is not on this page";
    if (IL_SLOTS.includes(controls.from_slot)) return `the player is on ${controls.from_slot} already`;
    if (!controls.movable) return "the player's slot is locked on this page";
    if (!controls.targets) return `no empty ${item.slot} slot on this page`;
    return null;
  }

  const visible = (el) => typeof el.getClientRects === "function" && el.getClientRects().length > 0;
  const squash = (s) => String(s ?? "").replace(/\s+/g, " ").trim();

  function alertsOf(doc) {
    let kept;
    try {
      kept = JSON.parse((doc.documentElement && doc.documentElement.getAttribute(IL_ALERTS_ATTR)) || "[]");
    } catch (_) {
      kept = [];
    }
    return Array.isArray(kept) ? kept.map(String) : [];
  }

  /** The two clicks of the move, once each: the player's slot label, then, once the swap shows
   * it, the one visible label of the item's slot in an empty row; then Yahoo's save. Every check
   * is read again before each click. Answers ``{outcome, reason, message}``: ``skipped`` when
   * nothing was clicked, ``moved`` once the page says it saved with the player in that slot,
   * ``failed`` after a click that did not come back. No field is set and nothing is fetched. */
  async function moveToIL(doc, item, { wait = (ms) => new Promise((r) => setTimeout(r, ms)), every = 200, showCap = IL_SHOW_MS, saveCap = IL_SAVE_MS } = {}) {
    const rows = () => [...doc.querySelectorAll(IL_ROWS)];
    const idOf = (tr) => {
      const el = tr.querySelector("[data-ys-playerid]");
      return el ? Number(el.getAttribute("data-ys-playerid")) : null;
    };
    const mine = () => rows().filter((tr) => idOf(tr) === item.player);
    const shownIn = (tr) => [...tr.querySelectorAll(IL_LABEL)].filter(visible);
    const start = () => {
      const m = mine();
      if (m.length !== 1 || !m[0].classList.contains("editable")) return null;
      const s = shownIn(m[0]);
      if (s.length !== 1 || s[0].getAttribute("role") !== "button" || IL_SLOTS.includes(s[0].getAttribute("data-pos"))) return null;
      return s[0];
    };
    const target = () => {
      const found = rows()
        .filter((tr) => idOf(tr) == null && tr.classList.contains("empty-bench") && tr.classList.contains("editable"))
        .flatMap((tr) => shownIn(tr).filter((l) => l.getAttribute("data-pos") === item.slot));
      return found.length === 1 ? found[0] : null;
    };
    const notice = () =>
      [...doc.querySelectorAll(IL_SAVED)]
        .filter(visible)
        .map((el) => ({ saved: el.classList.contains("saved"), error: /error|fail/i.test(el.className), text: squash(el.textContent) }))
        .filter((n) => n.text);
    const landed = () => {
      const m = mine();
      return m.length === 1 && shownIn(m[0]).some((l) => l.getAttribute("data-pos") === item.slot);
    };
    const label = start();
    if (!label) return { outcome: "skipped", reason: "the player's slot label is not one visible button in an editable row", message: null };
    const before = alertsOf(doc).length;
    const yahoo = () => alertsOf(doc).slice(before);
    const earlier = new Set(notice().map((n) => n.text));
    label.click();
    let to = target();
    for (let waited = 0; waited < showCap && !to && !yahoo().length; waited += every) {
      await wait(every);
      to = target();
    }
    if (yahoo().length) return { outcome: "failed", reason: `Yahoo answered the first click: "${yahoo()[0]}"`, message: null };
    if (!to) return { outcome: "failed", reason: `the ${item.slot} slot did not show within ${Math.round(showCap / 1000)} s (nothing saved)`, message: null };
    // Read again: the same label, the only one, in an empty row still.
    if (target() !== to) return { outcome: "failed", reason: `the ${item.slot} slot changed before its click (nothing saved)`, message: null };
    to.click();
    for (let waited = 0; waited < saveCap; waited += every) {
      await wait(every);
      if (yahoo().length) return { outcome: "failed", reason: `Yahoo answered the save: "${yahoo()[0]}"`, message: null };
      const fresh = notice().filter((n) => !earlier.has(n.text) || n.saved);
      const error = fresh.find((n) => n.error);
      if (error) return { outcome: "failed", reason: "Yahoo did not save the move", message: error.text };
      const saved = fresh.find((n) => n.saved);
      if (saved && landed()) return { outcome: "moved", reason: null, message: saved.text };
    }
    return { outcome: "failed", reason: `clicked; the save was not read in ${Math.round(saveCap / 1000)} s`, message: null };
  }

  /** The run the log takes (``POST /seasons/{league}/autopilot/il``). */
  function ilRun({ item = null, day, trigger, mode, outcome, reason = null, message = null, controls = null, page = null, extension = null }) {
    return {
      day,
      mode,
      trigger,
      outcome,
      reason,
      entry: item ? item.entry : null,
      player: item ? item.player : null,
      from_slot: controls ? controls.from_slot : null,
      to_slot: item ? item.slot : null,
      dated: item ? item.date : null,
      page,
      controls,
      message,
      extension,
    };
  }

  /** A move on record whose run was never logged, as the next visit logs it: clicked, its answer
   * not read; never made again (the API also refuses a second move after a failed one). */
  function unreadIL(record, extension) {
    return ilRun({
      item: { entry: record.entry, player: record.player, slot: record.slot, date: record.dated },
      day: record.day,
      trigger: record.trigger,
      mode: "live",
      outcome: "failed",
      reason: "clicked; Yahoo's answer was not read",
      page: record.page || null,
      extension,
    });
  }

  /** The entry's add page the tab goes to after a logged run (not a stop), with the moves fragment
   * of the run's trigger; null when the due answer lists no such entry. */
  function ilNext(due, item, trigger, site = "https://basketball.fantasysports.yahoo.com") {
    const entry = (due.entries || []).find((e) => e.id === item.entry);
    return entry && entry.page ? `${site}${pathOf(entry.page)}#${IL_THEN[trigger] || IL_THEN.routine}` : null;
  }

  /** The claim's skip on a full roster when this browser moved the held player on a later day's
   * page (the ruling on #214): "move dated <day>, claim waits", and the morning pass retries.
   * ``record`` is the move on record for the entry, ``day`` the pass's. */
  function claimWaits(check, record, day) {
    if (!check || check.outcome !== "skipped" || !/^the roster is full/.test(check.reason || "")) return check;
    if (!record || !record.run || record.run.outcome !== "moved" || !record.dated || record.dated <= day) return check;
    return { ...check, reason: `move dated ${record.dated}, claim waits` };
  }

  /** The panel's links to the league's ``il_first`` team pages, with the panel's IL fragment: the
   * user opens each; in a live league whose guard holds, opening one makes the move and the link
   * says so. The claim's add page follows in the same tab. */
  function ilLinks(due, live = false) {
    return (due.il_first || []).map((x) => ({
      id: x.entry,
      href: `${String(x.page).split("#")[0]}#pickandroll-il-panel`,
      text: `${live ? "move: " : ""}${x.player} to ${x.slot} (dated ${x.date}), then its claim`,
    }));
  }

  const IL_STRIP = {
    would_move: "would move",
    moved: "moved",
    skipped: "skipped",
    failed: "failed",
    stopped: "STOP is on: nothing clicked",
  };

  /** The strip's line: the run's mode and outcome with the move, why and Yahoo's words. */
  function ilStripText({ run = null, none = null, error = null, browserOff = false, next = null } = {}) {
    if (browserOff) return "off in this browser (options page)";
    if (error) return `not read: ${error}`;
    if (none) return none;
    if (!run) return "nothing ran";
    const mode = run.mode === "live" ? "live" : "dry run";
    const move = run.player != null ? ` ${run.player}${run.from_slot ? ` ${run.from_slot}` : ""} → ${run.to_slot} (dated ${run.dated})` : "";
    const why = run.reason ? ` (${run.reason})` : "";
    const words = run.message ? ` · ${run.message}` : "";
    return `${mode} · ${IL_STRIP[run.outcome] || run.outcome}${move}${why}${words}${next ? " · opening the claim" : ""}`;
  }

  return {
    IL_TRIGGERS,
    IL_THEN,
    IL_SLOTS,
    IL_MANAGER,
    IL_ROWS,
    IL_LABEL,
    IL_SAVED,
    IL_SHOW_MS,
    IL_SAVE_MS,
    IL_UNREAD_MS,
    ilTriggerOf,
    ilItemFor,
    readILPage,
    ilProblem,
    moveToIL,
    ilRun,
    unreadIL,
    ilNext,
    claimWaits,
    ilLinks,
    ilStripText,
  };
});
