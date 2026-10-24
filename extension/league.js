// pickandroll, league page reader (#98, isolated world). On a Yahoo league's own pages (the
// league page, a team page or a team's page for a day, the players page, a matchup, the
// transactions, the draft results, the settings page) it posts the page as
// the user's Chrome rendered it to the season's snapshot route, through the service worker; the
// API parses it (sources/yahoo/pages.py). This is how the private league, whose pages answer only
// when signed in, reaches the season view; a public league's pages post the same way.
//
// On my own team page it is also the lineup executor's dry run (#170, lib/lineup.js): opened from
// the routine's link (#pickandroll-lineup) or the side panel's button, it posts the page, takes
// the API's steps built from that post, checks each on the page's form and logs what it would
// set. Any other visit only shows the strip, a line saying what a run would do.
//
// It is also the moves executor's dry run there (#171, lib/moves.js): opened from the routine's
// link (#pickandroll-moves) or the side panel's button, it reads the league's due queue entries
// and, one at a time, GETs each entry's add page from Yahoo with this page's own session, parses
// it without rendering it (none of Yahoo's script runs), checks the entry on the page's claim form
// and logs the claim it would place.
//
// It never clicks anything, never sets a field, never reads a form's crumb (an add page's is taken
// out before the page is read), never posts to Yahoo and never runs on the draft client. It
// navigates only to follow the players page's Next 25 link during a multi-page read the user armed
// from the side panel.
(() => {
  "use strict";
  const PR = globalThis.PickAndRoll;
  const KEY = "__pickandrollLeague";
  const STRIP = "pickandroll-strip";
  const MOVES_STRIP = "pickandroll-moves-strip";
  const page = PR.leaguePage(location.href);
  if (!page || window[KEY]) return;
  window[KEY] = true;

  // Yahoo's league pages are served whole; a moment after load leaves room for anything the
  // page fills in late.
  const SETTLE_MS = 1500;

  // Held open while the page is: the panel stops showing this tab when it closes or leaves.
  try {
    chrome.runtime.connect({ name: "league" });
  } catch (_) {
    return; // the extension was reloaded under this page
  }

  async function send(msg) {
    try {
      return await chrome.runtime.sendMessage(msg);
    } catch (_) {
      return null; // the extension was reloaded: the next page load posts again
    }
  }

  /** The page without its scripts, styles, frames, form fields and the strip: all the parsers
   * read, and none of the page's own code or tokens (Yahoo's forms carry a hidden crumb). */
  function pageHtml() {
    const root = document.documentElement.cloneNode(true);
    const drop = `script, style, noscript, iframe, svg, link, template, input, textarea, #${STRIP}, #${MOVES_STRIP}`;
    for (const el of root.querySelectorAll(drop)) el.remove();
    return "<!doctype html>" + root.outerHTML;
  }

  /** The players page's Next 25 link, if it has one. */
  function nextLink() {
    const a = [...document.querySelectorAll("a[href]")].find((x) => /^next\s+25$/i.test(x.textContent.trim()));
    return a ? a.href : null;
  }

  /** Post the page; answers the time it was posted as and whether the API took it. */
  async function post() {
    const at = Date.now();
    const r = await send({
      op: "season_page",
      url: location.href,
      html: pageHtml(),
      fetched_at: at,
      next: page.kind === "players" ? nextLink() : null,
    });
    if (r && r.ok && r.data && r.data.follow) location.assign(r.data.follow);
    const accepted = Boolean(r && r.ok && r.data && r.data.post && !r.data.post.error && (r.data.post.accepted || []).length);
    return { at, accepted };
  }

  // ---------------------------------------------------------------- the lineup executor (#170)
  /** The lineup form as a plain object for ``readControls``: its action, its fields' names and
   * values, each select's options. The crumb's value is never read. */
  function formControls() {
    const form = document.querySelector("form#roster-edit-form");
    if (!form) return null;
    const manager = document.querySelector("section.ysf-rosterswap-manager");
    let action = null;
    try {
      action = new URL(form.getAttribute("action") || "", location.href).pathname;
    } catch (_) {
      action = null;
    }
    const fields = [...form.elements]
      .filter((el) => el.name)
      .map((el) => ({
        name: el.name,
        tag: el.tagName.toLowerCase(),
        type: String(el.type || "").toLowerCase(),
        value: /crumb/i.test(el.name) ? null : el.value,
        options: el.tagName === "SELECT" ? [...el.options].map((o) => ({ value: o.value, text: o.textContent.trim(), selected: o.selected })) : null,
      }));
    return {
      action,
      method: String(form.getAttribute("method") || "get").toLowerCase(),
      editable: manager ? manager.getAttribute("data-is-editable") === "true" : null,
      swap_method: manager ? manager.getAttribute("data-swapmethod") : null,
      swap_labels: document.querySelectorAll("span.pos-label[role=button]").length,
      fields,
    };
  }

  function strip(line, { id = STRIP, label = "lineup", bottom = 8 } = {}) {
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement("div");
      el.id = id;
      el.setAttribute("role", "status");
      el.style.cssText =
        `position:fixed;left:8px;bottom:${bottom}px;z-index:2147483647;max-width:60vw;padding:4px 8px;border-radius:4px;` +
        "font:12px/1.4 system-ui,sans-serif;background:#1f2933;color:#f5f7fa;opacity:.92;pointer-events:none";
      document.documentElement.append(el);
    }
    el.textContent = `pickandroll ${label}: ${line}`;
  }

  const movesStrip = (line) => strip(line, { id: MOVES_STRIP, label: "moves", bottom: 36 });

  function extensionVersion() {
    try {
      return chrome.runtime.getManifest().version;
    } catch (_) {
      return null;
    }
  }

  let running = false;

  /** A visit to my team page: the strip, and a dry run when ``trigger`` says one was asked for.
   * ``posted`` is the page's own post. Answers the run logged, or null. */
  async function lineup(trigger, posted) {
    const raw = formControls();
    if (!raw || page.kind !== "team") return null;
    const settings = await send({ op: "settings" });
    if (settings && settings.ok && settings.data.lineup_executor === "off") {
      strip(PR.stripText({ browserOff: true }));
      return null;
    }
    const controls = PR.readControls(raw);
    const day = controls.date || page.date;
    if (!day) return null;
    const r = await send({ op: "lineup_steps", league: page.league, date: day });
    if (!r || !r.ok) {
      strip(PR.stripText({ error: (r && r.error) || "no answer from the extension" }));
      return null;
    }
    const steps = r.data;
    // Another team's page: nothing to show.
    if (steps.team !== page.team) return null;
    if (steps.mode === "off" || !trigger) {
      strip(PR.stripText({ steps }));
      return null;
    }
    const problem = PR.pageProblem(page, controls, steps);
    const checked = problem ? null : PR.checkSteps(controls, steps.steps, steps.slots || []);
    const where = location.pathname + location.search;
    const extension = extensionVersion();
    const run = PR.dryRun({
      steps,
      trigger,
      page: where,
      postedAt: posted.accepted ? posted.at : NaN,
      controls,
      problem,
      checked,
      extension,
    });
    const logged = await send({ op: "lineup_log", league: page.league, run });
    if (!logged || !logged.ok) {
      strip(`not logged: ${(logged && logged.error) || "no answer from the extension"}`);
      return null;
    }
    strip(PR.stripText({ steps, run }));
    return run;
  }

  // ---------------------------------------------------------------- the moves executor (#171)
  /** The pause between two add pages (one page at a time) and the most one may take. */
  const PAGE_GAP_MS = 2000;
  const PAGE_TIMEOUT_MS = 20000;
  const textOf = (el) => (el ? el.textContent.trim().replace(/\s+/g, " ") : "");
  const CRUMB = 'input[name*="crumb" i]';

  /** An add page parsed from its HTML (``doc``) as a plain object for ``readAddPage``. The crumb
   * inputs are taken out before anything is read: only that the page had one is kept. */
  function addControls(doc, path) {
    const token = doc.querySelectorAll(CRUMB).length > 0;
    for (const el of doc.querySelectorAll(CRUMB)) el.remove();
    const form = doc.querySelector(`form#${PR.FORM_ID}`);
    const heading = [...doc.querySelectorAll("h1, h2, h3")].map(textOf).find((x) => /claim player|add player/i.test(x)) || null;
    const hint = form ? [...form.querySelectorAll("p, span, div")].map(textOf).find((x) => /^must be between \$\d+ and \$\d+$/i.test(x)) || null : null;
    // The submit sits in a noscript: parsed markup here, where no script runs; text on a live page.
    const box = doc.getElementById("add-drop-submit-container");
    const button = doc.querySelector("#submit-add-drop-button");
    const submit = button ? button.getAttribute("name") : box ? (/name="([^"]+)"/.exec(box.textContent || box.innerHTML || "") || [])[1] || null : null;
    const message =
      [...doc.querySelectorAll(".Alert, .alert, .error, .Error, .F-negative, .Bg-note, p")]
        .map(textOf)
        .find((x) => x && x.length < 200 && /available|already|roster|owned/i.test(x)) || null;
    return {
      path,
      heading,
      token,
      form: form
        ? {
            action: (() => {
              try {
                return new URL(form.getAttribute("action") || "", location.href).pathname;
              } catch (_) {
                return null;
              }
            })(),
            method: form.getAttribute("method") || "get",
            fields: [...form.elements]
              .filter((el) => el.name)
              .map((el) => ({ name: el.name, tag: el.tagName.toLowerCase(), type: String(el.type || "").toLowerCase(), value: el.value, checked: Boolean(el.checked) })),
          }
        : null,
      submit,
      panel: textOf(doc.getElementById("faab-bid-fieldset")) || null,
      hint,
      cantcut: form ? form.querySelectorAll('.T-action-icon-cantcut:not([class*="-show"])').length : 0,
      no_moves: Boolean(form && form.querySelector('.T-action-icon-no-add:not([class*="-show"])')),
      message,
    };
  }

  /** GET the add page at ``path`` with this page's own session: ``{raw}``, or ``{error}`` when it
   * could not be read (not signed in, a network failure, an error status). */
  async function readAdd(path) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), PAGE_TIMEOUT_MS);
    try {
      const r = await fetch(new URL(path, location.href).href, { credentials: "same-origin", redirect: "follow", signal: ctl.signal });
      const at = new URL(r.url || path, location.href);
      if (at.origin !== location.origin) return { error: "the add page went to another site (signed out of Yahoo?)" };
      if (!r.ok) return { error: `the add page answered HTTP ${r.status}` };
      const doc = new DOMParser().parseFromString(await r.text(), "text/html");
      return { raw: addControls(doc, at.pathname + at.search) };
    } catch (e) {
      return { error: `the add page could not be read: ${(e && e.message) || e}` };
    } finally {
      clearTimeout(timer);
    }
  }

  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /** A pass of the moves executor on my team page, when ``trigger`` says one was asked for: the
   * due entries, each through the checks before its page and then on its add page, one page at a
   * time; a page that cannot be read stops the pass. Answers the pass logged, or null. */
  async function moves(trigger) {
    if (!trigger || page.kind !== "team") return null;
    const settings = await send({ op: "settings" });
    if (settings && settings.ok && settings.data.moves_executor === "off") {
      movesStrip(PR.movesStripText({ browserOff: true }));
      return null;
    }
    const r = await send({ op: "moves_due", league: page.league });
    if (!r || !r.ok) {
      movesStrip(PR.movesStripText({ error: (r && r.error) || "no answer from the extension" }));
      return null;
    }
    const due = r.data;
    // Another team's page: nothing to run.
    if (due.team !== page.team) return null;
    if (due.mode === "off") {
      movesStrip(PR.movesStripText({ due }));
      return null;
    }
    const checks = [];
    const pass = [];
    let error = null;
    let read = 0;
    for (const entry of due.stop ? [] : due.entries || []) {
      if (error) {
        checks.push(PR.moveCheck(entry, { outcome: "skipped", reason: "the pass stopped at an add page it could not read" }));
        continue;
      }
      const why = PR.entryProblem(entry, due, pass);
      if (why) {
        checks.push(PR.moveCheck(entry, { outcome: "skipped", reason: why }));
        continue;
      }
      if (read++) await pause(PAGE_GAP_MS);
      const got = await readAdd(entry.page || PR.addPath(due.league, entry.add));
      if (got.error) {
        error = got.error;
        checks.push(PR.moveCheck(entry, { outcome: "failed", reason: got.error }));
        continue;
      }
      const seen = PR.readAddPage(got.raw, entry.from);
      const check = PR.pageCheck(entry, seen, due);
      checks.push(PR.moveCheck(entry, check, seen));
      if (check.outcome === "would_claim") pass.push(entry);
    }
    const run = PR.movesPass({ due, trigger, checks, error, extension: extensionVersion() });
    const logged = await send({ op: "moves_log", league: page.league, run });
    if (!logged || !logged.ok) {
      movesStrip(`not logged: ${(logged && logged.error) || "no answer from the extension"}`);
      return null;
    }
    movesStrip(PR.movesStripText({ due, run }));
    return run;
  }

  async function visit(trigger, movesTrigger = null) {
    if (running) return null;
    running = true;
    try {
      const posted = await post();
      const run = await lineup(trigger, posted);
      const pass = await moves(movesTrigger);
      // A routine's run happens once: a reload of the page is a plain visit.
      if ((trigger || movesTrigger) && location.hash) history.replaceState(null, "", location.pathname + location.search);
      return { run, pass };
    } finally {
      running = false;
    }
  }

  // The side panel's "Set lineup now" and "Check moves now": post the page again and run from
  // that post.
  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (!msg || (msg.op !== "lineup_run" && msg.op !== "moves_run")) return false;
    const lineupRun = msg.op === "lineup_run";
    visit(lineupRun ? "panel" : null, lineupRun ? null : "panel").then(
      (out) => reply({ ok: true, data: lineupRun ? { run: out && out.run } : { pass: out && out.pass } }),
      (e) => reply({ ok: false, error: String((e && e.message) || e) }),
    );
    return true;
  });

  setTimeout(() => visit(PR.triggerOf(location.hash), PR.movesTriggerOf(location.hash)), SETTLE_MS);
})();
