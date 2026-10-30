// A churn's held drop (#221 part 3, docs/AUTOPILOT.md section 2): on my team's drop page
// (/nba/<league>/<team>/dropplayer) opened with a drop fragment, the ``drop_first`` item of the
// moves executor's due, the page's controls as Yahoo drew them (step 0c on #221, 2026-10-30), the
// page Yahoo lands on after the submit, and the run the log takes. Pure but for ``dropPlayer``,
// the one step that clicks: the content script (league.js) reads the page into a plain object and
// calls these.
//
// What a drop is (step 0c): the row's visible button (its ``data-check-box-value`` names the
// player, with a trailing space) ticks the hidden box, and Yahoo's own script posts the first stage
// and draws the form again in place: stage 2, one hidden ``dpid`` and the submit "Drop <name>".
// That submit, once, drops him at once, and Yahoo lands on my team page with errno 933 in its
// alerts and the notice "You have successfully dropped <name>". The hidden box is never ticked by
// us and a dry run clicks nothing.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /** The fragments a drop starts from on the drop page, and the fragments the tab then goes on
   * with: the entry's IL move on my team page (#214), or its add page. */
  const DROP_TRIGGERS = {
    "pickandroll-drop": "routine",
    "pickandroll-drop-late": "routine_late",
    "pickandroll-drop-evening": "routine_evening",
    "pickandroll-drop-panel": "panel",
  };
  const DROP_THEN = {
    routine: { il: "pickandroll-il", moves: "pickandroll-moves" },
    routine_late: { il: "pickandroll-il-late", moves: "pickandroll-moves-late" },
    routine_evening: { il: "pickandroll-il-evening", moves: "pickandroll-moves-evening" },
    panel: { il: "pickandroll-il-panel", moves: "pickandroll-moves-panel" },
  };
  /** Yahoo's drop page (step 0c): the form, its stage, the row's button and the attribute naming
   * its player, the row's name link, and the confirm's submit. */
  const DROP_FORM = "form#add-drop-players-form";
  const DROP_ROW_BUTTON = "button.add-drop-trigger-btn";
  const DROP_VALUE_ATTR = "data-check-box-value";
  const DROP_NAME = "a.name[data-ys-playerid]";
  const DROP_FIELD = "dpid";
  const DROP_SUBMIT = "input#submit-add-drop-button";
  const DROP_SUBMIT_NAME = "submit_drop_player";
  const DROP_FIRST_STAGE = "1";
  const DROP_CONFIRM_STAGE = "2";
  /** Yahoo's answer on the landed page: the alert code of a drop, and its notice. */
  const DROP_ERRNO = 933;
  const DROP_NOTICE = /^You have successfully dropped\b/i;
  /** How long the run waits for Yahoo's confirm after the row's button. */
  const DROP_CONFIRM_MS = 15 * 1000;
  /** How long a submit waits for its landed page in the same tab; a drop on record past it whose
   * run was not logged is logged by the next visit, unconfirmed. */
  const DROP_LANDING_MS = 2 * 60 * 1000;
  const DROP_ALERTS_ATTR = "data-pickandroll-alerts";
  /** The longest of the page's words a run keeps. */
  const DROP_WORDS_MAX = 300;

  /** The drop's trigger from the page's fragment (``location.hash``), null when it has none. */
  function dropTriggerOf(hash) {
    return DROP_TRIGGERS[String(hash || "").replace(/^#/, "")] || null;
  }

  /** The drop page ``url`` is (``/nba/<league>/<team>/dropplayer``): ``{league, team}``, null for
   * any other page. */
  function dropPageOf(url) {
    let u;
    try {
      u = new URL(url);
    } catch (_) {
      return null;
    }
    if (u.hostname !== "basketball.fantasysports.yahoo.com") return null;
    const m = /^\/nba\/(\d+)\/(\d+)\/dropplayer\/?$/.exec(u.pathname);
    return m ? { league: m[1], team: Number(m[2]) } : null;
  }

  const pathOf = (url) => {
    try {
      return new URL(url, "https://basketball.fantasysports.yahoo.com").pathname.replace(/\/+$/, "");
    } catch (_) {
      return null;
    }
  };

  /** The first ``drop_first`` item of ``due`` (GET /seasons/{league}/autopilot/moves/due) whose
   * page is ``path`` and that ``done(item)`` does not rule out (this browser ran it today), null
   * when none. One drop page serves every churn of the league: each visit takes the next. */
  function dropItemFor(due, path, done = () => false) {
    return (due.drop_first || []).find((x) => x.page && pathOf(x.page) === pathOf(path) && !done(x)) || null;
  }

  /** The outcomes after which a drop is never made again that day (the API's ``DROP_STICKS``). */
  const DROP_STICKS = ["dropped", "failed", "unconfirmed"];

  /** Whether the run on record for the item (``record``, the worker's) rules it out of this
   * visit: a live drop submitted or sticky that day; otherwise a run of this mode logged that day
   * by this pass (``trigger``), so one pass takes each item once and a later pass retries a skip. */
  function ranToday(record, day, mode, trigger) {
    if (!record || record.day !== day) return false;
    if (record.mode === "live" && (!record.logged || DROP_STICKS.includes(record.outcome))) return true;
    return record.mode === mode && record.trigger === trigger;
  }

  /** The page as the content script read it (``{path, form, stage, rows: [{player, name,
   * visible}], ticked}``) into what the run checks and logs for ``item``: the stage, the player's
   * rows (his id exact, the attribute trimmed), whether his button shows and his name is read. */
  function readDropPage(raw, item) {
    const rows = (raw.rows || []).filter((r) => r.player === String(item.player));
    return {
      path: raw.path || null,
      form: raw.form === true,
      stage: raw.stage ?? null,
      rows: rows.length,
      trigger: rows.length === 1 && rows[0].visible === true,
      name: rows.length === 1 && Boolean(rows[0].name),
      ticked: raw.ticked || 0,
    };
  }

  /** Why the drop may not be made on this page, null when it may. */
  function dropProblem(controls) {
    if (!controls.form) return "the drop form is not on this page";
    if (String(controls.stage) !== DROP_FIRST_STAGE) return `the drop form is at stage ${controls.stage ?? "none"}, not its first`;
    if (controls.rows !== 1) return controls.rows ? "the player shows more than once on this page" : "the player is not on this page";
    if (!controls.trigger) return "the player's drop button is not shown";
    if (!controls.name) return "the player's name is not on his row";
    if (controls.ticked) return "a drop box was ticked before the run";
    return null;
  }

  const visible = (el) => typeof el.getClientRects === "function" && el.getClientRects().length > 0;
  const squash = (s) => String(s ?? "").replace(/\s+/g, " ").trim();

  function alertsOf(doc) {
    let kept;
    try {
      kept = JSON.parse((doc.documentElement && doc.documentElement.getAttribute(DROP_ALERTS_ATTR)) || "[]");
    } catch (_) {
      kept = [];
    }
    return Array.isArray(kept) ? kept.map(String) : [];
  }

  /** The two clicks of the drop, once each: the player's row button, then, once Yahoo's confirm
   * shows stage 2, one hidden ``dpid`` equal to the player and a submit "Drop <his name>", that
   * submit. ``onConfirm`` runs between the read and the submit (league.js puts the drop on record
   * there) and the submit is clicked only when it answers true. Every check is read again before
   * each click. Answers ``{outcome, reason, message, confirm}``: ``skipped`` when nothing was
   * clicked, ``failed`` when the confirm was not as planned or Yahoo answered with an alert (no
   * submit; the page's words in ``message``), null once the submit is clicked (Yahoo lands on
   * another page, whose read is the run's). No field is set and nothing is fetched. */
  async function dropPlayer(doc, item, { onConfirm = async () => true, wait = (ms) => new Promise((r) => setTimeout(r, ms)), every = 200, cap = DROP_CONFIRM_MS } = {}) {
    const id = String(item.player);
    const form = () => doc.querySelector(DROP_FORM);
    const named = (n) => (form() ? [...form().elements].filter((el) => el.name === n) : []);
    const stage = () => named("stage").map((el) => String(el.value));
    const buttons = () => (form() ? [...form().querySelectorAll(DROP_ROW_BUTTON)].filter((b) => String(b.getAttribute(DROP_VALUE_ATTR) ?? "").trim() === id) : []);
    const before = alertsOf(doc).length;
    const yahoo = () => alertsOf(doc).slice(before);
    const words = () => {
      const f = form();
      return squash([...alertsOf(doc).slice(before), f ? f.textContent : ""].filter(Boolean).join(" · ")).slice(0, DROP_WORDS_MAX) || null;
    };
    const skip = (reason) => ({ outcome: "skipped", reason, message: null, confirm: null });
    if (!form()) return skip("the drop form is gone");
    if (stage().join() !== DROP_FIRST_STAGE) return skip(`the drop form is at stage ${stage().join(", ") || "none"}, not its first`);
    const mine = buttons();
    if (mine.length !== 1 || !visible(mine[0])) return skip(`no single shown drop button for ${id} (${mine.length} on the page)`);
    const row = mine[0].closest("tr");
    const link = row ? [...row.querySelectorAll(DROP_NAME)].find((a) => a.getAttribute("data-ys-playerid") === id && squash(a.textContent)) : null;
    if (!link) return skip("the player's name is not on his row");
    const name = squash(link.textContent);
    if (named(DROP_FIELD).some((el) => el.checked)) return skip("a drop box was ticked before the run");
    mine[0].click();
    const confirm = () => {
      const dpid = named(DROP_FIELD);
      const submit = form() ? [...form().querySelectorAll(DROP_SUBMIT)].filter((el) => el.getAttribute("name") === DROP_SUBMIT_NAME) : [];
      return {
        stage: stage().join(", ") || null,
        dpid: dpid.map((el) => `${String(el.type).toLowerCase()}=${el.value}`).join(", ") || null,
        submit: submit.map((el) => squash(el.value)).join(", ") || null,
        shown: submit.length === 1 && visible(submit[0]),
        ok:
          stage().join() === DROP_CONFIRM_STAGE &&
          dpid.length === 1 &&
          String(dpid[0].type).toLowerCase() === "hidden" &&
          String(dpid[0].value) === id &&
          submit.length === 1 &&
          visible(submit[0]) &&
          squash(submit[0].value) === `Drop ${name}`,
        button: submit.length === 1 ? submit[0] : null,
      };
    };
    let c = confirm();
    for (let waited = 0; waited < cap && !c.ok && !yahoo().length; waited += every) {
      await wait(every);
      c = confirm();
    }
    const read = { stage: c.stage, dpid: c.dpid, submit: c.submit, shown: c.shown, name: true };
    const stop = (reason) => ({ outcome: "failed", reason: `stopped before the submit: ${reason}`, message: words(), confirm: read });
    if (yahoo().length) return stop(`Yahoo answered the row's button: "${yahoo()[0]}"`);
    if (!c.ok) return stop(`the confirm did not show stage 2, dpid ${id} and "Drop ${name}" within ${Math.round(cap / 1000)} s`);
    if (!(await onConfirm(read))) return { outcome: "skipped", reason: "the drop could not be put on record", message: null, confirm: read };
    // Read again: the same submit, the only one, still naming him.
    const again = confirm();
    if (!again.ok || again.button !== c.button) return stop("the confirm changed before the submit");
    c.button.click();
    return null;
  }

  /** Yahoo's answer on the page it landed on after the submit (``raw``: ``{path, alerts, notices,
   * shown}``, where ``alerts`` is the ``_global_alerts`` query value): ``dropped`` with errno 933
   * saying he was dropped, or the notice; otherwise ``unconfirmed``, never ``dropped``. */
  function readDropLanded(raw) {
    const codes = alertCodes(raw.alerts);
    const said = codes.find((a) => Number(a.errno) === DROP_ERRNO && /\bdropped\b/i.test((a.params || []).join(" ")));
    const notice = (raw.notices || []).map(squash).find((x) => DROP_NOTICE.test(x));
    const landed = { path: raw.path || null, errnos: codes.map((a) => Number(a.errno)), notice: notice || null, shown: raw.shown ?? null };
    if (said || notice) return { outcome: "dropped", message: notice || squash((said.params || []).join(" ")), landed };
    const words = [...codes.flatMap((a) => a.params || []), ...(raw.notices || [])].map(squash).filter(Boolean)[0] || null;
    return { outcome: "unconfirmed", message: words, landed };
  }

  /** The alerts Yahoo put in the landed URL's ``_global_alerts``: "<signature>|<JSON list>". */
  function alertCodes(value) {
    const s = String(value || "");
    const bar = s.indexOf("|");
    if (bar < 0) return [];
    try {
      const list = JSON.parse(s.slice(bar + 1));
      return Array.isArray(list) ? list.filter((a) => a && typeof a === "object") : [];
    } catch (_) {
      return [];
    }
  }

  /** The run the log takes (``POST /seasons/{league}/autopilot/drop``). */
  function dropRun({ item = null, day, trigger, mode, outcome, reason = null, message = null, controls = null, landed = null, page = null, extension = null }) {
    return {
      day,
      mode,
      trigger,
      outcome,
      reason,
      entry: item ? item.entry : null,
      player: item ? item.player : null,
      page,
      controls,
      landed,
      message,
      extension,
    };
  }

  /** The live run of a submitted drop (``record``, the worker's) once its landed page is read:
   * ``read`` is ``readDropLanded``'s answer, null when the page was never read (unconfirmed). */
  function landedDrop(record, read, extension = null) {
    const item = { entry: record.entry, player: record.player };
    if (!read) return dropRun({ item, day: record.day, trigger: record.trigger, mode: "live", outcome: "unconfirmed", reason: "submitted; Yahoo's answer was not read", controls: record.controls || null, page: record.page || null, extension });
    const reason = read.outcome === "dropped" ? null : "the landed page did not say he was dropped (no errno 933, no notice)";
    return dropRun({ item, day: record.day, trigger: record.trigger, mode: "live", outcome: read.outcome, reason, message: read.message, controls: record.controls || null, landed: read.landed, page: record.page || null, extension });
  }

  /** Where the tab goes after the entry's drop landed, from the due read again: the entry's IL
   * move on my team page when it is behind one, else its add page, with the trigger's fragment;
   * null when the due answer lists neither (its add waits, or the drop did not land). */
  function dropNext(due, entry, trigger, site = "https://basketball.fantasysports.yahoo.com") {
    const then = DROP_THEN[trigger] || DROP_THEN.routine;
    const at = (page, hash) => {
      const u = new URL(page, site);
      return `${site}${u.pathname}${u.search}#${hash}`;
    };
    const il = (due.il_first || []).find((x) => x.entry === entry);
    if (il && il.page) return at(il.page, then.il);
    const e = (due.entries || []).find((x) => x.id === entry);
    return e && e.page ? at(e.page, then.moves) : null;
  }

  /** The panel's links to the league's drop page, one per ``drop_first`` item, with the panel's
   * drop fragment: the user opens each; in a live league whose guard holds, opening one makes the
   * drop and the link says so. The IL move and the claim follow in the same tab. */
  function dropLinks(due, live = false) {
    return (due.drop_first || []).map((x) => ({
      id: x.entry,
      href: `${String(x.page).split("#")[0]}#pickandroll-drop-panel`,
      text: `${live ? "drop: " : ""}${x.player} from ${x.slot || "the roster"}, then its add ${x.add}`,
    }));
  }

  const DROP_STRIP = {
    would_drop: "would drop",
    dropped: "dropped",
    skipped: "skipped",
    failed: "failed",
    unconfirmed: "unconfirmed",
    stopped: "STOP is on: nothing clicked",
  };

  /** The strip's line: the run's mode and outcome with the player, why and Yahoo's words. */
  function dropStripText({ run = null, none = null, error = null, browserOff = false, next = null } = {}) {
    if (browserOff) return "off in this browser (options page)";
    if (error) return `not read: ${error}`;
    if (none) return none;
    if (!run) return "nothing ran";
    const mode = run.mode === "live" ? "live" : "dry run";
    const who = run.player != null ? ` ${run.player}` : "";
    const why = run.reason ? ` (${run.reason})` : "";
    const words = run.message ? ` · ${run.message}` : "";
    return `${mode} · ${DROP_STRIP[run.outcome] || run.outcome}${who}${why}${words}${next ? " · going on" : ""}`;
  }

  return {
    DROP_TRIGGERS,
    DROP_THEN,
    DROP_FORM,
    DROP_ROW_BUTTON,
    DROP_VALUE_ATTR,
    DROP_NAME,
    DROP_SUBMIT,
    DROP_SUBMIT_NAME,
    DROP_ERRNO,
    DROP_CONFIRM_MS,
    DROP_STICKS,
    DROP_LANDING_MS,
    dropTriggerOf,
    dropPageOf,
    dropItemFor,
    ranToday,
    readDropPage,
    dropProblem,
    dropPlayer,
    readDropLanded,
    alertCodes,
    dropRun,
    landedDrop,
    dropNext,
    dropLinks,
    dropStripText,
  };
});
