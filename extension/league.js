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
// On an add page (/nba/<league>/addplayer?apid=<player>) it is the moves executor's dry run
// (#171, lib/moves.js), and only when the page was opened with the routine's fragment
// (#pickandroll-moves, #pickandroll-moves-late) or the side panel's link: the routine opens each
// due queue entry's add page in a tab of its own. It drops the fragment, fetches the league's due
// entries, checks the one whose add is this page's on the rendered claim form and logs the claim it
// would place. It posts nothing for the add page.
//
// It never clicks anything, never sets a field, never reads a form's crumb, never fetches a Yahoo
// page and never runs on the draft client. It navigates only to follow the players page's Next 25
// link during a multi-page read the user armed from the side panel.
(() => {
  "use strict";
  const PR = globalThis.PickAndRoll;
  const KEY = "__pickandrollLeague";
  const STRIP = "pickandroll-strip";
  const page = PR.leaguePage(location.href);
  const addPage = page ? null : PR.addPageOf(location.href);
  if ((!page && !addPage) || window[KEY]) return;
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
    const drop = `script, style, noscript, iframe, svg, link, template, input, textarea, #${STRIP}`;
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

  function strip(line, label = "lineup") {
    let el = document.getElementById(STRIP);
    if (!el) {
      el = document.createElement("div");
      el.id = STRIP;
      el.setAttribute("role", "status");
      el.style.cssText =
        "position:fixed;left:8px;bottom:8px;z-index:2147483647;max-width:60vw;padding:4px 8px;border-radius:4px;" +
        "font:12px/1.4 system-ui,sans-serif;background:#1f2933;color:#f5f7fa;opacity:.92;pointer-events:none";
      document.documentElement.append(el);
    }
    el.textContent = `pickandroll ${label}: ${line}`;
  }

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

  async function visit(trigger) {
    if (running) return null;
    running = true;
    try {
      const posted = await post();
      const run = await lineup(trigger, posted);
      // A routine's run happens once: a reload of the page is a plain visit.
      if (trigger && location.hash) history.replaceState(null, "", location.pathname + location.search);
      return run;
    } finally {
      running = false;
    }
  }

  // The side panel's "Set lineup now": post the page again and run from that post.
  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (!msg || msg.op !== "lineup_run") return false;
    visit("panel").then(
      (run) => reply({ ok: true, data: { run } }),
      (e) => reply({ ok: false, error: String((e && e.message) || e) }),
    );
    return true;
  });

  // ---------------------------------------------------------------- the moves executor (#171)
  const textOf = (el) => (el ? el.textContent.trim().replace(/\s+/g, " ") : "");
  const movesStrip = (line) => strip(line, "moves");

  /** The rendered add page as a plain object for ``readAddPage``: the claim form's action, its
   * fields' names and values less the anti-forgery field (only whether the form has it, as
   * ``token``), the heading, the bid panel and its hint, the submit's name (in a noscript until a
   * drop is picked), the add's row and my roster's rows with their player ids and marker icons.
   * The waiver-order table is never read. */
  function addControls() {
    const form = document.querySelector(`form#${PR.FORM_ID}`);
    const named = form ? [...form.elements].filter((el) => el.name) : [];
    const fields = named.filter((el) => !PR.TOKEN.test(el.name));
    let action = null;
    try {
      action = form ? new URL(form.getAttribute("action") || "", location.href).pathname : null;
    } catch (_) {
      action = null;
    }
    const icons = (tr) => [...tr.querySelectorAll('[class*="T-action-icon-"]')].map((x) => x.className).join(" ");
    const row = (tr) => {
      const id = tr.querySelector("[data-ys-playerid]");
      return id ? { id: id.getAttribute("data-ys-playerid"), classes: icons(tr) } : null;
    };
    const addRow = document.querySelector("table#statTable-add tbody tr [data-ys-playerid]");
    const box = document.getElementById("add-drop-submit-container");
    const button = document.querySelector("#submit-add-drop-button");
    const submit = button ? button.getAttribute("name") : box ? (/name="([^"]+)"/.exec(box.textContent || "") || [])[1] || null : null;
    return {
      path: location.pathname + location.search,
      heading: [...document.querySelectorAll("h1, h2, h3")].map(textOf).find((x) => /(?:claim|add|drop) player/i.test(x)) || null,
      form: form
        ? {
            action,
            method: form.getAttribute("method") || "get",
            fields: fields.map((el) => ({
              name: el.name,
              tag: el.tagName.toLowerCase(),
              type: String(el.type || "").toLowerCase(),
              value: el.value,
              checked: Boolean(el.checked),
            })),
            token: fields.length < named.length,
          }
        : null,
      submit,
      panel: textOf(document.getElementById("faab-bid-fieldset")) || null,
      hint: form ? [...form.querySelectorAll("p, span, div")].map(textOf).find((x) => /^must be between \$\d+ and \$\d+$/i.test(x)) || null : null,
      add_row: addRow ? row(addRow.closest("tr")) : null,
      rows: [...document.querySelectorAll("table.statTable-drop tbody tr")].map(row).filter(Boolean),
      message: form ? null : [...document.querySelectorAll(".Alert, .alert, .error, .Error, .F-negative, p")].map(textOf).find((x) => x && x.length < 200) || null,
    };
  }

  /** The moves executor's dry run on this add page, opened with ``trigger``'s fragment: the
   * league's due entries, the one whose add is this page's checked on the rendered form, and the
   * pass logged. No entry for this player: nothing is logged. Answers the pass logged, or null. */
  async function claim(trigger) {
    // A routine's pass happens once: a reload of the page is a plain visit.
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    const settings = await send({ op: "settings" });
    if (settings && settings.ok && settings.data.moves_executor === "off") {
      movesStrip(PR.movesStripText({ browserOff: true }));
      return null;
    }
    const r = await send({ op: "moves_due", league: addPage.league });
    if (!r || !r.ok) {
      movesStrip(PR.movesStripText({ error: (r && r.error) || "no answer from the extension" }));
      return null;
    }
    const due = r.data;
    if (due.mode === "off") {
      movesStrip(PR.movesStripText({ due }));
      return null;
    }
    const extension = extensionVersion();
    let run;
    if (due.stop) run = PR.movesPass({ due, trigger, extension });
    else {
      const entry = (due.entries || []).find((e) => e.add === addPage.add);
      if (!entry) {
        movesStrip(PR.movesStripText({ due, none: true }));
        return null;
      }
      const readAt = new Date().toISOString();
      const seen = PR.readAddPage(addControls(), entry.from);
      const why = PR.entryProblem(entry, due);
      const check = why ? { outcome: "skipped", reason: why } : PR.pageCheck(entry, seen, due);
      run = PR.movesPass({ due, trigger, checks: [PR.moveCheck(entry, check, seen, due, readAt)], extension });
    }
    const logged = await send({ op: "moves_log", league: addPage.league, run });
    if (!logged || !logged.ok) {
      movesStrip(`not logged: ${(logged && logged.error) || "no answer from the extension"}`);
      return null;
    }
    movesStrip(PR.movesStripText({ due, run }));
    return run;
  }

  if (addPage) {
    const trigger = PR.movesTriggerOf(location.hash);
    if (trigger) setTimeout(() => claim(trigger), SETTLE_MS);
    return;
  }

  setTimeout(() => visit(PR.triggerOf(location.hash)), SETTLE_MS);
})();
