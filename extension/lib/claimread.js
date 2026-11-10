// The read of one pending claim's page (#345 step 0, docs/AUTOPILOT.md section 2): before the
// executor may ever cancel a claim (PR 2), the routine's evening pass opens my team page in one
// public league with the read's fragment; the content script (league.js) follows the Pending
// Transactions box's View Details link to Yahoo's page of that claim (``viewwaiver``) and reads
// it: where it landed, its heading and notices, its forms by name, method and action path, each
// form field by its kind and names, and the buttons and links with the words they show. Never a
// field's value, never a query or a crumb, and nothing is clicked: the read only looks. Pure: the
// content script reads the page into a plain object and calls these.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  /** The fragment the evening pass opens my team page with, and the claim's page then. */
  const CLAIM_READ_FRAGMENT = "pickandroll-claim-read";
  const CLAIM_READ_TRIGGERS = { [CLAIM_READ_FRAGMENT]: "routine_evening" };
  const HOST = "basketball.fantasysports.yahoo.com";
  /** The API's caps (``season_autopilot.ClaimPageRead``): longer words are cut, more rows dropped. */
  const WORDS = 200;
  const MAX_FORMS = 20;
  const MAX_FIELDS = 100;
  const MAX_CONTROLS = 50;
  const MAX_NOTES = 20;
  /** A button's words are its label: an ``input`` button shows its value, and that alone of an
   * input's values is read. */
  const BUTTON_INPUTS = new Set(["submit", "button", "reset", "image"]);

  function claimReadTriggerOf(hash) {
    return CLAIM_READ_TRIGGERS[String(hash || "").replace(/^#/, "")] || null;
  }

  /** Yahoo's page of a claim (``/nba/<league>/<team>/viewwaiver?claim_id=<team>_<add>_<drop>``,
   * the team optional): ``{league, team, claim}``; null for any other page. */
  function claimPageOf(url) {
    let u;
    try {
      u = new URL(url);
    } catch (_) {
      return null;
    }
    if (u.protocol !== "https:" || u.hostname !== HOST) return null;
    const m = /^\/nba\/(\d+)(?:\/(\d+))?\/viewwaiver\/?$/.exec(u.pathname);
    if (!m) return null;
    const claim = u.searchParams.get("claim_id");
    return { league: m[1], team: m[2] ? Number(m[2]) : null, claim: claim && /^\d+_\d+_\d+$/.test(claim) ? claim : null };
  }

  /** The View Details link to follow from the box's ``lines`` (``{href, text}`` each, null: no
   * box): the one whose ``claim_id`` names the due claim's add and drop (an open spot is 0), else
   * the first that names a claim; null when none does. */
  function claimLink(lines, due) {
    if (!Array.isArray(lines)) return null;
    const idOf = (l) => (/[?&]claim_id=(\d+_\d+_\d+)(?:&|$)/.exec((l && l.href) || "") || [])[1] || null;
    const named = lines.filter((l) => idOf(l));
    if (!named.length) return null;
    const want = due && due.add != null ? `_${due.add}_${due.drop == null ? 0 : due.drop}` : null;
    const hit = want ? named.find((l) => idOf(l).endsWith(want)) : null;
    return (hit || named[0]).href;
  }

  /** ``s`` as words: spaces squashed, Yahoo's icon glyphs dropped, cut to the API's cap; null
   * when empty. */
  function words(s) {
    const t = String(s ?? "").replace(/[-]/g, "").replace(/\s+/g, " ").trim();
    return t ? t.slice(0, WORDS) : null;
  }

  /** A link's or an action's path without its query or fragment (a crumb may ride in one); a
   * page of another host keeps its host. Null when it does not read as a URL. */
  function plainPath(href, base) {
    if (href == null || href === "") return null;
    let u;
    try {
      u = new URL(href, base || `https://${HOST}/`);
    } catch (_) {
      return null;
    }
    if (u.protocol !== "https:" && u.protocol !== "http:") return u.protocol;
    const path = u.hostname === HOST ? u.pathname : `//${u.hostname}${u.pathname}`;
    return path.slice(0, WORDS);
  }

  const lower = (s) => (s == null || s === "" ? null : String(s).toLowerCase().slice(0, 40));
  const name = (s) => (s == null || s === "" ? null : String(s).slice(0, WORDS));

  /** A form field by its kind and names: its value is never read, whatever the raw object holds. */
  function fieldOf(raw) {
    return { tag: lower(raw.tag) || "input", type: lower(raw.type), name: name(raw.name), id: name(raw.id) };
  }

  /** A button or a link: its kind, names, the words it shows (an input button's label) and a
   * link's path without its query. */
  function controlOf(raw, base) {
    const tag = lower(raw.tag) || "button";
    const type = lower(raw.type);
    const text = tag === "input" ? (BUTTON_INPUTS.has(type) ? words(raw.label) : null) : words(raw.text);
    return { tag, type, name: name(raw.name), id: name(raw.id), text, path: tag === "a" ? plainPath(raw.href, base) : null };
  }

  /** Words a claim's own link or button shows. */
  const CLAIM_WORDS = /waiver|claim|cancel|bid|save|drop|add/i;

  /** A stats tab of the player's card: a link back to the page's own path whose words are not a
   * claim's ("Stats", "Last 7 Days", "2025-26"): noise the read leaves out (#345 PR 2). */
  function statsTab(c, own) {
    return c.tag === "a" && own != null && c.path === own && !CLAIM_WORDS.test(c.text || "");
  }

  /** The read the API files (``POST /seasons/<league>/autopilot/claim-page``) from the content
   * script's ``raw`` page: ``{url, heading, notes, forms: [{id, name, method, action, fields,
   * controls}], controls}``. Only the names and words listed above are kept. */
  function claimPageRead(raw, { trigger, readAt, extension }) {
    const at = claimPageOf(raw.url);
    const base = raw.url;
    const own = plainPath(raw.url, base);
    const forms = (raw.forms || []).slice(0, MAX_FORMS).map((f) => ({
      id: name(f.id),
      name: name(f.name),
      method: f.method ? String(f.method).toLowerCase().slice(0, 10) : null,
      action: f.action == null ? null : plainPath(f.action, base),
      fields: (f.fields || []).slice(0, MAX_FIELDS).map(fieldOf),
      controls: (f.controls || [])
        .map((c) => controlOf(c, base))
        .filter((c) => !statsTab(c, own))
        .slice(0, MAX_CONTROLS),
    }));
    return {
      trigger,
      read_at: new Date(readAt).toISOString(),
      claim: at ? at.claim : null,
      path: own || "",
      heading: words(raw.heading),
      notes: [...new Set((raw.notes || []).map(words).filter((x) => x && !/^\d+$/.test(x)))].slice(0, MAX_NOTES),
      forms,
      controls: (raw.controls || []).slice(0, MAX_CONTROLS).map((c) => controlOf(c, base)),
      extension: extension == null ? null : String(extension).slice(0, 20),
    };
  }

  /** The strip's line for the read. */
  function claimReadStripText({ error = null, skipped = null, logged = null, forms = 0, controls = 0 } = {}) {
    if (error) return `the claim page's read failed: ${error}`;
    if (skipped) return `no claim page read: ${skipped}`;
    if (logged) return `claim page read and filed: ${forms} form${forms === 1 ? "" : "s"}, ${controls} control${controls === 1 ? "" : "s"}; nothing clicked`;
    return "reading the claim's page; nothing is clicked";
  }

  return {
    CLAIM_READ_FRAGMENT,
    CLAIM_READ_TRIGGERS,
    claimReadTriggerOf,
    claimPageOf,
    claimLink,
    claimPageRead,
    claimReadStripText,
    plainPath,
  };
});
