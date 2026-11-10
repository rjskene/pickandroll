// pickandroll, the add page's alert recorder (#171, 0.8.2; the page's own world, at
// document_start). Yahoo's add page answers a refused drop or a bid out of range with
// ``alert``, which would block the tab, and the routine's pass with it, until someone dismissed
// it. On an add page opened with a moves fragment (the routine's link, its late or evening pass,
// or the side panel's), and on a team page opened with a start-active fragment (#215, 0.9.0) or an
// IL one (#214, 0.9.1), and on my team's drop page opened with a drop fragment (#221, 0.10.0), and on a
// claim's page opened with the cancel fragment (#345 PR 2, 0.11.11), and nowhere else, ``alert`` keeps its text on the root element instead, where the executor
// (lib/moves.js ``alertsOf``, lib/startactive.js) reads it and logs the run with Yahoo's words. A
// page the user opens by hand keeps Yahoo's alerts. On the claim's page opened with the cancel
// fragment ``confirm`` too keeps its words, and answers yes only while the cancel's one press
// holds its flag up (lib/cancel.js ``pressCancel``) and only when the words name cancelling the
// waiver or the claim; any other confirm there is answered no. It reads nothing else on the page
// and sends nothing.
(() => {
  "use strict";
  /** The moves fragments (lib/moves.js ``MOVES_TRIGGERS``), the start-active ones
   * (lib/startactive.js ``START_ACTIVE_TRIGGERS``) and where the texts are kept (``ALERTS_ATTR``);
   * this world loads none of the extension's libraries. */
  const FRAGMENTS = [
    "pickandroll-moves",
    "pickandroll-moves-late",
    "pickandroll-moves-evening",
    "pickandroll-moves-panel",
  ];
  const START_ACTIVE_FRAGMENTS = [
    "pickandroll-start-active",
    "pickandroll-start-active-late",
    "pickandroll-start-active-evening",
    "pickandroll-start-active-daily",
    "pickandroll-start-active-panel",
    "pickandroll-start-active-after-lineup",
    "pickandroll-start-active-comeback",
    "pickandroll-start-active-comeback-late",
  ];
  /** The IL move's (lib/ilmove.js ``IL_TRIGGERS``, #214, 0.9.1). */
  const IL_FRAGMENTS = [
    "pickandroll-il",
    "pickandroll-il-late",
    "pickandroll-il-evening",
    "pickandroll-il-panel",
  ];
  /** The held drop's (lib/drop.js ``DROP_TRIGGERS``, #221 part 3, 0.10.0). */
  const DROP_FRAGMENTS = [
    "pickandroll-drop",
    "pickandroll-drop-late",
    "pickandroll-drop-evening",
    "pickandroll-drop-panel",
    "pickandroll-drop-comeback",
    "pickandroll-drop-comeback-late",
  ];
  /** The claim's cancel (lib/cancel.js ``CANCEL_TRIGGERS``, #345 PR 2, 0.11.11). */
  const CANCEL_FRAGMENTS = ["pickandroll-claim-cancel"];
  const ATTR = "data-pickandroll-alerts";
  /** Where the confirms' words and answers are kept, and the one-shot flag of the press. */
  const CONFIRMS_ATTR = "data-pickandroll-confirms";
  const ARMED_ATTR = "data-pickandroll-confirm-armed";
  const CLAIM_PAGE = /^\/nba\/\d+\/\d+\/viewwaiver\/?$/;
  const ADD_PAGE = /^\/nba\/\d+\/addplayer\/?$/;
  const TEAM_PAGE = /^\/nba\/\d+\/\d+\/?$/;
  const DROP_PAGE = /^\/nba\/\d+\/\d+\/dropplayer\/?$/;
  /** The longest text kept of one alert. */
  const LONGEST = 300;

  /** Whether ``text`` names cancelling the waiver or the claim (lib/cancel.js
   * ``confirmNamesCancel``). */
  function namesCancel(text) {
    const t = String(text ?? "").replace(/\s+/g, " ");
    return /\bcancel/i.test(t) && /\b(waiver|claim)/i.test(t);
  }

  function keep(root, attr, value) {
    let kept;
    try {
      kept = JSON.parse(root.getAttribute(attr) || "[]");
    } catch (_) {
      kept = [];
    }
    if (!Array.isArray(kept)) kept = [];
    kept.push(value);
    root.setAttribute(attr, JSON.stringify(kept));
  }

  /** On the add page of ``win`` opened with a moves fragment, the team page opened with a
   * start-active or IL one, the drop page opened with a drop one, or a claim's page opened with
   * the cancel one, ``alert`` keeps its text instead of showing it; on the claim's page
   * ``confirm`` keeps its words too and answers yes only under the press's flag, for words that
   * name the cancel (the flag is taken down at once). Answers whether it installed. */
  function install(win) {
    const loc = win.location;
    const hash = String(loc.hash || "").replace(/^#/, "");
    const add = ADD_PAGE.test(loc.pathname) && FRAGMENTS.includes(hash);
    const team = TEAM_PAGE.test(loc.pathname) && (START_ACTIVE_FRAGMENTS.includes(hash) || IL_FRAGMENTS.includes(hash));
    const drop = DROP_PAGE.test(loc.pathname) && DROP_FRAGMENTS.includes(hash);
    const cancel = CLAIM_PAGE.test(loc.pathname) && CANCEL_FRAGMENTS.includes(hash);
    if (!add && !team && !drop && !cancel) return false;
    const root = win.document.documentElement;
    win.alert = function alert(message) {
      keep(root, ATTR, String(message ?? "").slice(0, LONGEST));
    };
    if (cancel) {
      win.confirm = function confirm(message) {
        const text = String(message ?? "").slice(0, LONGEST);
        const armed = root.getAttribute(ARMED_ATTR) === "1";
        root.removeAttribute(ARMED_ATTR);
        const yes = armed && namesCancel(text);
        keep(root, CONFIRMS_ATTR, { text, yes, armed });
        return yes;
      };
    }
    return true;
  }

  if (typeof window === "undefined") module.exports = { install, namesCancel, FRAGMENTS, START_ACTIVE_FRAGMENTS, IL_FRAGMENTS, DROP_FRAGMENTS, CANCEL_FRAGMENTS, ATTR, CONFIRMS_ATTR, ARMED_ATTR };
  else install(window);
})();
