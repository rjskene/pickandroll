// A pending claim's cancel (#345 PR 2, docs/AUTOPILOT.md section 2): once the 21:00 build judged a
// placed claim again and it no longer pays, the evening pass opens my team page with the cancel's
// fragment, the content script (league.js) follows that claim's own View Details link in the
// Pending Transactions box to Yahoo's page of it (``viewwaiver``), checks the page as the read on
// file showed it (step 0, 2026-11-09: ``form#edit-waiver-form`` posting to ``/editwaiver``, the
// player's ``a#playernote-<add>`` in it, and one submit named ``s`` whose label is "Cancel
// Waiver"), and presses that button once in a live league whose guard holds. A dry run clicks
// nothing. Yahoo's ``confirm``, if it asks, is answered yes only for that press and only when its
// words name cancelling the waiver or claim (addpage.js); any other is answered no. My team page's
// box then says whether the claim is gone. The bid field is never touched, no form is submitted by
// script and nothing is fetched. Pure but for ``pressCancel``, the one step that clicks.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /** The fragment the evening pass opens my team page with, and the claim's page then. */
  const CANCEL_FRAGMENT = "pickandroll-claim-cancel";
  const CANCEL_TRIGGERS = { [CANCEL_FRAGMENT]: "routine_evening" };
  /** Yahoo's page of a claim as step 0 read it. */
  const CANCEL_FORM = "form#edit-waiver-form";
  const CANCEL_ACTION = /^\/nba\/(\d+)\/(\d+)\/editwaiver\/?$/;
  const CANCEL_BUTTON_NAME = "s";
  const CANCEL_LABEL = "Cancel Waiver";
  /** Where addpage.js keeps the confirm's words, and the one-shot flag that lets it say yes. */
  const CONFIRM_ARMED_ATTR = "data-pickandroll-confirm-armed";
  const CONFIRMS_ATTR = "data-pickandroll-confirms";
  const ALERTS_ATTR = "data-pickandroll-alerts";
  /** How long a press waits for its landed page in the same tab; a press on record past it whose
   * run was not logged is logged by the next visit, unconfirmed. */
  const CANCEL_LANDING_MS = 2 * 60 * 1000;
  /** A press whose page has not left after this long goes to my team page to read the box. */
  const CANCEL_STAY_MS = 20 * 1000;
  /** A live cancel's outcomes after which it is never pressed again (the API's ``CANCEL_STICKS``). */
  const CANCEL_STICKS = ["cancelled", "not_cancelled", "failed", "unconfirmed"];
  /** The longest of the page's words a run keeps. */
  const WORDS_MAX = 300;
  const HOST = "basketball.fantasysports.yahoo.com";

  const squash = (s) => String(s ?? "").replace(/[-]/g, "").replace(/\s+/g, " ").trim();
  const cut = (s) => squash(s).slice(0, WORDS_MAX) || null;

  /** The cancel's trigger from the page's fragment (``location.hash``), null when it has none. */
  function cancelTriggerOf(hash) {
    return CANCEL_TRIGGERS[String(hash || "").replace(/^#/, "")] || null;
  }

  /** Yahoo's id of a claim of ``team``: ``<team>_<add>_<drop>``, 0 for an open spot. */
  function claimIdOf(team, item) {
    if (team == null || !item || item.add == null) return null;
    return `${team}_${item.add}_${item.drop == null ? 0 : item.drop}`;
  }

  /** The ``claim_id`` a View Details link names, null when none. */
  function claimIdIn(href) {
    return (/[?&]claim_id=(\d+_\d+_\d+)(?:&|$)/.exec(String(href || "")) || [])[1] || null;
  }

  /** The View Details link of exactly this claim in the box's ``lines`` (``{href, text}`` each,
   * null: no box): my team, its add and its drop. Never another claim's: null when none matches. */
  function cancelLink(lines, team, item) {
    const want = claimIdOf(team, item);
    if (!want || !Array.isArray(lines)) return null;
    const hit = lines.find((l) => claimIdIn(l && l.href) === want);
    return hit ? hit.href : null;
  }

  /** Whether the run on record for the item (``record``, the worker's) rules it out of this
   * visit: a live press not yet logged, or one that holds (``CANCEL_STICKS``); otherwise a run of
   * this mode logged that day, so one pass takes each claim once. */
  function cancelRanToday(record, day, mode) {
    if (!record) return false;
    if (record.mode === "live" && (!record.logged || CANCEL_STICKS.includes(record.outcome))) return true;
    return record.day === day && record.mode === mode;
  }

  /** The first cancel of ``due`` (GET /seasons/{league}/autopilot/cancels) that ``done(item)``
   * does not rule out, null when none. */
  function cancelItemFor(due, done = () => false) {
    return (due.cancels || []).find((x) => !done(x)) || null;
  }

  /** Yahoo's page of a claim (``/nba/<league>/<team>/viewwaiver?claim_id=…``): ``{league, team,
   * claim}``; null for any other page. */
  function cancelPageOf(url) {
    let u;
    try {
      u = new URL(url);
    } catch (_) {
      return null;
    }
    if (u.protocol !== "https:" || u.hostname !== HOST) return null;
    const m = /^\/nba\/(\d+)\/(\d+)\/viewwaiver\/?$/.exec(u.pathname);
    if (!m) return null;
    const claim = u.searchParams.get("claim_id");
    return { league: m[1], team: Number(m[2]), claim: claim && /^\d+_\d+_\d+$/.test(claim) ? claim : null };
  }

  const pathOf = (href) => {
    try {
      const u = new URL(href, `https://${HOST}/`);
      return u.hostname === HOST ? u.pathname : null;
    } catch (_) {
      return null;
    }
  };

  /** The claim's page as the content script read it (``{url, forms: [{id, action, players,
   * buttons: [{name, type, label}]}]}``, ``players`` the ids of the form's ``a[id^=playernote-]``)
   * into what the run checks and logs: the claim the URL names, the form, its action path, the
   * add's link in it, and the "Cancel Waiver" submits. Never a field's value. */
  function readCancelPage(raw) {
    const at = cancelPageOf(raw.url) || {};
    const forms = (raw.forms || []).filter((f) => f.id === "edit-waiver-form");
    const form = forms.length === 1 ? forms[0] : null;
    const buttons = form ? form.buttons || [] : [];
    const cancels = buttons.filter((b) => b.name === CANCEL_BUTTON_NAME && b.type === "submit" && squash(b.label) === CANCEL_LABEL);
    return {
      path: pathOf(raw.url),
      claim: at.claim || null,
      team: at.team ?? null,
      league: at.league || null,
      forms: forms.length,
      action: form ? pathOf(form.action) : null,
      players: form ? (form.players || []).map(String) : [],
      buttons: buttons.map((b) => cut(b.label)).filter(Boolean),
      cancel: cancels.length,
    };
  }

  /** Why the cancel may not be pressed on this page for ``item`` of my ``team`` in ``league``,
   * null when it may: the URL's claim is exactly this one, the one form posts to my team's
   * ``/editwaiver``, the add's link is in it, and it has one "Cancel Waiver" submit. */
  function cancelProblem(controls, { league, team, item }) {
    const want = claimIdOf(team, item);
    if (!want) return "no claim id for this entry";
    if (controls.claim !== want) return `the page is claim ${controls.claim || "none"}, not ${want}`;
    if (String(controls.league) !== String(league) || controls.team !== Number(team)) return "the page is not my team's in this league";
    if (controls.forms !== 1) return controls.forms ? "the claim's form shows more than once" : "the claim's form is not on this page";
    const action = CANCEL_ACTION.exec(controls.action || "");
    if (!action || action[1] !== String(league) || Number(action[2]) !== Number(team)) return `the form posts to ${controls.action || "nowhere"}, not my team's editwaiver`;
    if (!controls.players.includes(String(item.add))) return `the add ${item.add} is not named in the form`;
    if (controls.cancel !== 1) return controls.cancel ? "more than one Cancel Waiver button" : "no Cancel Waiver button on the page";
    return null;
  }

  /** Whether Yahoo's confirm names cancelling the waiver or the claim: the only one said yes to. */
  function confirmNamesCancel(text) {
    const t = squash(text);
    return /\bcancel/i.test(t) && /\b(waiver|claim)/i.test(t);
  }

  function keptOf(doc, attr) {
    let kept;
    try {
      kept = JSON.parse((doc.documentElement && doc.documentElement.getAttribute(attr)) || "[]");
    } catch (_) {
      kept = [];
    }
    return Array.isArray(kept) ? kept : [];
  }

  /** The confirms addpage.js answered on this page, each ``{text, yes}``. */
  const confirmsOf = (doc) => keptOf(doc, CONFIRMS_ATTR).filter((c) => c && typeof c === "object");

  /** The "Cancel Waiver" submit of ``form`` (the page's own, read live), and the add's link. */
  function liveControls(doc, item) {
    const forms = [...doc.querySelectorAll(CANCEL_FORM)];
    const form = forms.length === 1 ? forms[0] : null;
    const submit = (b) => (b.tagName === "INPUT" ? String(b.getAttribute("type") || "").toLowerCase() === "submit" : String(b.getAttribute("type") || "submit").toLowerCase() === "submit");
    const buttons = form
      ? [...form.querySelectorAll("input, button")].filter(
          (b) => submit(b) && b.getAttribute("name") === CANCEL_BUTTON_NAME && squash(b.tagName === "INPUT" ? b.getAttribute("value") : b.textContent) === CANCEL_LABEL
        )
      : [];
    const named = form ? [...form.querySelectorAll(`a[id="playernote-${item.add}"]`)].length > 0 : false;
    return { form, buttons, named };
  }

  /** The cancel's one press: the page's form, the add's link and its one "Cancel Waiver" submit
   * read again, ``onPress`` (league.js puts the press on record there, answering whether it took),
   * then the confirm flag up, the button clicked once (the submitter's ``s`` goes with the post)
   * and the flag down. Answers ``{outcome, reason, confirm}`` when the press is over here: a skip
   * (nothing clicked), ``not_cancelled`` when Yahoo's confirm did not name the cancel and was
   * answered no, or ``failed`` when Yahoo answered with an alert; ``{pressed: true, confirm}``
   * once the press went (Yahoo lands on another page, whose read is the run's). */
  async function pressCancel(doc, item, { onPress = async () => true } = {}) {
    const skip = (reason) => ({ outcome: "skipped", reason, confirm: null });
    const first = liveControls(doc, item);
    if (!first.form) return skip("the claim's form is gone");
    if (!first.named) return skip(`the add ${item.add} is not named in the form`);
    if (first.buttons.length !== 1) return skip(`${first.buttons.length} Cancel Waiver buttons on the page`);
    if (!(await onPress())) return skip("the press could not be put on record");
    const again = liveControls(doc, item);
    if (again.buttons.length !== 1 || again.buttons[0] !== first.buttons[0] || !again.named) {
      return { outcome: "failed", reason: "stopped before the press: the page changed", confirm: null };
    }
    const root = doc.documentElement;
    const confirmsBefore = confirmsOf(doc).length;
    const alertsBefore = keptOf(doc, ALERTS_ATTR).length;
    root.setAttribute(CONFIRM_ARMED_ATTR, "1");
    try {
      again.buttons[0].click();
    } finally {
      root.removeAttribute(CONFIRM_ARMED_ATTR);
    }
    const asked = confirmsOf(doc).slice(confirmsBefore);
    const confirm = asked.length ? asked.map((c) => cut(c.text)).join(" · ") : null;
    const refused = asked.find((c) => !c.yes);
    if (refused) return { outcome: "not_cancelled", reason: `Yahoo's confirm did not name the cancel and was answered no: "${cut(refused.text)}"`, confirm };
    const alerts = keptOf(doc, ALERTS_ATTR).slice(alertsBefore).map(cut).filter(Boolean);
    if (alerts.length) return { outcome: "failed", reason: `Yahoo answered the press: "${alerts[0]}"`, confirm };
    return { pressed: true, confirm };
  }

  /** The page Yahoo landed on after the press (``raw``: ``{path, form, heading, notes,
   * errors}``, ``form`` whether a claim form is there): ``not_cancelled`` when Yahoo drew a form
   * again on the claim's pages (another stage: nothing more is clicked), else null (my team
   * page's box decides). */
  function readCancelLanded(raw) {
    const words = [raw.heading, ...(raw.errors || []), ...(raw.notes || [])].map(cut).filter(Boolean).join(" · ").slice(0, WORDS_MAX) || null;
    if (raw.form && /\/(viewwaiver|editwaiver)\/?$/.test(raw.path || "")) {
      return { outcome: "not_cancelled", reason: "Yahoo showed a form again after the press: nothing more is clicked", message: words };
    }
    return null;
  }

  /** How many claims the Pending Transactions box lists (``lines``, null: no box): each distinct
   * ``claim_id`` among its links; null with no box. */
  function pendingCount(lines) {
    if (!Array.isArray(lines)) return null;
    return new Set(lines.map((l) => claimIdIn(l && l.href)).filter(Boolean)).size;
  }

  /** The answer on my team page (#341's settle): the claim's link in the Pending Transactions box
   * (``lines``, null: no box) is ``not_cancelled``; the box without it is ``cancelled``. No box is
   * ``cancelled`` only when the box listed this claim alone before the press (``before``, the
   * count kept on the press's record) and the page shows my roster: a box that failed to draw, or
   * drew late, while the claim still stands is never taken for a cancel. Otherwise
   * ``unconfirmed``. */
  function settleCancel(lines, claim, roster, before = null) {
    if (Array.isArray(lines)) {
      if (lines.some((l) => claimIdIn(l && l.href) === claim)) return { outcome: "not_cancelled", reason: "the claim is still among Yahoo's pending transactions" };
      return { outcome: "cancelled", reason: null };
    }
    if (!roster) return { outcome: "unconfirmed", reason: "pressed; my team page showed neither the box nor my roster" };
    if (before === 1) return { outcome: "cancelled", reason: null };
    if (before == null) return { outcome: "unconfirmed", reason: "the box is gone and no count of it was kept before the press" };
    return { outcome: "unconfirmed", reason: `the box is gone but listed ${before} claims before the press` };
  }

  /** The run the log takes (the API's ``CancelRun``). */
  function cancelRun({ day, mode, trigger, outcome, reason = null, item = null, claim = null, page = null, controls = null, landed = null, message = null, extension = null }) {
    return {
      day,
      mode,
      trigger,
      outcome,
      reason: reason == null ? null : String(reason).slice(0, 500),
      entry: item ? item.entry : null,
      add: item ? item.add : null,
      drop: item ? (item.drop == null ? null : item.drop) : null,
      claim,
      page,
      controls,
      landed,
      message: message == null ? null : String(message).slice(0, 500),
      extension: extension == null ? null : String(extension).slice(0, 20),
    };
  }

  /** The run of a press on record whose answer never came: pressed, Yahoo's answer not read. */
  function unreadCancel(record, extension) {
    return cancelRun({
      day: record.day,
      mode: "live",
      trigger: record.trigger,
      outcome: "unconfirmed",
      reason: "pressed; Yahoo's answer was not read: check the pending claims",
      item: record.item,
      claim: record.claim,
      page: record.page,
      controls: record.controls,
      landed: record.settle ? record.settle.seen : null,
      extension,
    });
  }

  /** The strip's line. */
  function cancelStripText({ error = null, none = null, browserOff = false, run = null, pressing = null } = {}) {
    if (error) return `the cancel failed: ${error}`;
    if (browserOff) return "the browser's brake is on: nothing is cancelled";
    if (none) return `nothing to cancel: ${none}`;
    if (pressing) return `live · cancel of claim ${pressing} pressed: reading Yahoo's answer…`;
    if (run) {
      const what = run.claim || run.entry || "";
      if (run.outcome === "would_cancel") return `dry run · would cancel claim ${what}${run.reason ? ` (${run.reason})` : ""}; nothing clicked`;
      if (run.outcome === "cancelled") return `live · claim ${what} cancelled on Yahoo`;
      return `${run.mode === "live" ? "live" : "dry run"} · claim ${what}: ${run.outcome}${run.reason ? ` (${run.reason})` : ""}`;
    }
    return "reading the claim's page…";
  }

  return {
    CANCEL_FRAGMENT,
    CANCEL_TRIGGERS,
    CANCEL_FORM,
    CANCEL_LABEL,
    CONFIRM_ARMED_ATTR,
    CONFIRMS_ATTR,
    CANCEL_LANDING_MS,
    CANCEL_STAY_MS,
    CANCEL_STICKS,
    cancelTriggerOf,
    claimIdOf,
    claimIdIn,
    cancelLink,
    cancelRanToday,
    cancelItemFor,
    cancelPageOf,
    readCancelPage,
    cancelProblem,
    confirmNamesCancel,
    confirmsOf,
    pressCancel,
    readCancelLanded,
    pendingCount,
    settleCancel,
    cancelRun,
    unreadCancel,
    cancelStripText,
  };
});
