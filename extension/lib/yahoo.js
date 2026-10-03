// Reading Yahoo's draft-client player table: which row is a candidate, and whether a Draft
// button's label names the player we mean; which controls are the queue's; and what a change of
// the Autodraft switch means. Pure: rows are passed in as {id, text}, so node's tests cover the
// matching that the content script runs on the live DOM.
//
// The client's class names are hashed; rows are anchored on the headshot image id
// (/{yahooId}.png, usually the Yahoo player id but not always) and on their text
// ("V. Wembanyama SAS - C", folded to ASCII lower case).
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const fold = (s) =>
    String(s || "")
      .normalize("NFD")
      .replace(/[̀-ͯ]/g, "")
      .toLowerCase();

  /** The Yahoo id in a headshot URL (…/10094.png or …/10094.1.png), else null. */
  function imageId(src) {
    const m = /\/(\d{3,7})(?:\.\d+)?\.png/.exec(src || "");
    return m ? m[1] : null;
  }

  /** Index of the row for candidate ``c`` ({yahoo_player_id, ini, last, team}) in ``rows``
   * ([{id, text}]), or -1. The image id counts only with the last name in the row text; then
   * "f. last" with the team; then last name, team and initial; then "f. last" if unique. */
  function matchRow(rows, c) {
    const last = fold(c.last);
    const ini = fold(c.ini);
    const team = fold(c.team);
    const abbr = `${ini}. ${last}`;
    const texts = rows.map((r) => fold(r.text));
    if (c.yahoo_player_id != null) {
      const i = rows.findIndex((r, j) => r.id === String(c.yahoo_player_id) && (!last || texts[j].includes(last)));
      if (i >= 0) return i;
    }
    if (!last) return -1;
    let i = texts.findIndex((t) => t.includes(abbr) && (!team || t.includes(team)));
    if (i < 0 && team) i = texts.findIndex((t) => t.includes(last) && t.includes(team) && t.includes(`${ini}.`));
    if (i < 0) {
      const only = texts.map((t, j) => (t.includes(abbr) ? j : -1)).filter((j) => j >= 0);
      if (only.length === 1) i = only[0];
    }
    return i;
  }

  /** A Draft button's label is safe to click for ``c``: bare ("Draft"), or naming him. */
  function labelNames(label, c) {
    const rest = String(label || "")
      .replace(/^\s*draft\s*/i, "")
      .trim();
    if (!/[a-z]{2,}\s+[a-z]/i.test(rest)) return true;
    return fold(rest).includes(fold(c.last));
  }

  const isDraftLabel = (label) => /^\s*draft\b/i.test(String(label || ""));

  /** A control is the queue's only when one of its labels (aria-label, title, text) names the
   * queue and none of them is a Draft label; an unlabelled control is never the queue's. */
  const isQueueControl = (labels) => {
    const parts = (labels || []).map((x) => String(x || "").trim()).filter(Boolean);
    return parts.some((x) => /\bqueue\b/i.test(x)) && !parts.some(isDraftLabel);
  };

  /** A queue entry's control that takes it off the queue: one of its labels names remove,
   * delete or the queue, and none is a Draft label. An unlabelled control is never clicked: on
   * my turn an entry's last button can be its Draft button. */
  const isRemoveControl = (labels) => {
    const parts = (labels || []).map((x) => String(x || "").trim()).filter(Boolean);
    return parts.some((x) => /\b(remove|delete|queue)\b/i.test(x)) && !parts.some(isDraftLabel);
  };

  /** What a change of Yahoo's Autodraft switch from ``was`` to ``on`` (true, false, or null:
   * not found) means, or null when it did not change. ``ours``: the drafter's backstop switched
   * it; ``byHand``: a trusted click on it just before. ``autopick`` true hands the seat to Yahoo
   * (control absent, the drafter stands down); null leaves it as it was. Only a flip nobody here
   * made is Yahoo's ("autopick", which G5 counts); on at entry or by hand is the user's; the
   * drafter's own is neither and leaves the seat armed. */
  function autodraftSeen(was, on, { ours = false, byHand = false } = {}) {
    if (on === null || on === undefined || was === on) return null;
    if (was === null || was === undefined) {
      return on
        ? { autopick: true, reason: "autodraft at entry", note: "autodraft switch seen" }
        : { autopick: null, reason: null, note: "autodraft switch seen" };
    }
    if (!on) return { autopick: false, reason: null, note: "autodraft off" };
    if (ours) return { autopick: false, reason: "autodraft by pickandroll", note: "autodraft on by pickandroll" };
    if (byHand) return { autopick: true, reason: "autodraft by hand", note: "autodraft on by hand" };
    return { autopick: true, reason: "autopick", note: "autodraft on by Yahoo" };
  }

  /** What the guard undoes between my turns: the Autodraft switch when Yahoo flipped it (a
   * missed pick) or the drafter left it on, and the queue, never while the switch stays on.
   * A switch the user turned on (by hand, or on at entry) is theirs, and so is its queue. */
  function guardActions({ on, reason, ours = false, queued = 0 }) {
    const autodraftOff = on === true && (ours || reason === "autopick");
    return { autodraftOff, clearQueue: queued > 0 && (on !== true || autodraftOff) };
  }

  /** The queue probe's outcome. A Draft-labelled control that landed nothing lost the click
   * ("dropped"), so "failed" is left for the star path: a star that queued nothing readable. */
  const probeOutcome = (drafted, queued, labels) =>
    drafted ? "drafted" : queued ? "queued" : (labels || []).some(isDraftLabel) ? "dropped" : "failed";

  /** The plan's candidates for a turn, best first, without players the room has taken. */
  function candidatesFor(plan, taken) {
    const out = [];
    const seen = new Set();
    for (const c of (plan && plan.candidates) || []) {
      const yid = String(c.yahoo_player_id);
      if (taken.has(yid) || seen.has(yid)) continue;
      seen.add(yid);
      out.push({ ...c, yahoo_player_id: yid });
    }
    return out;
  }

  return {
    fold,
    imageId,
    matchRow,
    labelNames,
    isDraftLabel,
    isQueueControl,
    isRemoveControl,
    autodraftSeen,
    guardActions,
    probeOutcome,
    candidatesFor,
  };
});
