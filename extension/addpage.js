// pickandroll, the add page's alert recorder (#171, 0.8.2; the page's own world, at
// document_start). Yahoo's add page answers a refused drop or a bid out of range with
// ``alert``, which would block the tab, and the routine's pass with it, until someone dismissed
// it. On an add page opened with a moves fragment (the routine's link, its late or evening pass,
// or the side panel's), and on a team page opened with a start-active fragment (#215, 0.9.0), and
// nowhere else, ``alert`` keeps its text on the root element instead, where the executor
// (lib/moves.js ``alertsOf``, lib/startactive.js) reads it and logs the run with Yahoo's words. A
// page the user opens by hand keeps Yahoo's alerts. It reads nothing on the page and sends
// nothing.
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
  ];
  const ATTR = "data-pickandroll-alerts";
  const ADD_PAGE = /^\/nba\/\d+\/addplayer\/?$/;
  const TEAM_PAGE = /^\/nba\/\d+\/\d+\/?$/;
  /** The longest text kept of one alert. */
  const LONGEST = 300;

  /** On the add page of ``win`` opened with a moves fragment, or the team page opened with a
   * start-active one, ``alert`` keeps its text instead of showing it. Answers whether it does. */
  function install(win) {
    const loc = win.location;
    const hash = String(loc.hash || "").replace(/^#/, "");
    const add = ADD_PAGE.test(loc.pathname) && FRAGMENTS.includes(hash);
    const team = TEAM_PAGE.test(loc.pathname) && START_ACTIVE_FRAGMENTS.includes(hash);
    if (!add && !team) return false;
    const root = win.document.documentElement;
    win.alert = function alert(message) {
      let kept;
      try {
        kept = JSON.parse(root.getAttribute(ATTR) || "[]");
      } catch (_) {
        kept = [];
      }
      if (!Array.isArray(kept)) kept = [];
      kept.push(String(message ?? "").slice(0, LONGEST));
      root.setAttribute(ATTR, JSON.stringify(kept));
    };
    return true;
  }

  if (typeof window === "undefined") module.exports = { install, FRAGMENTS, START_ACTIVE_FRAGMENTS, ATTR };
  else install(window);
})();
