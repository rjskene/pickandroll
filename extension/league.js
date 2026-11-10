// pickandroll, league page reader (#98, isolated world). On a Yahoo league's own pages (the
// league page, a team page or a team's page for a day, the players page, a matchup, the
// transactions, the draft results, the settings page) it posts the page as
// the user's Chrome rendered it to the season's snapshot route, through the service worker; the
// API parses it (sources/yahoo/pages.py). This is how the private league, whose pages answer only
// when signed in, reaches the season view; a public league's pages post the same way.
//
// On my own team page it is also the lineup executor (#170, lib/lineup.js): opened from the
// routine's link (#pickandroll-lineup, -lineup-late) or the side panel's button, it posts the page,
// takes the API's steps built from that post, checks each on the page's form and logs what it
// would set; in a live league whose guard holds (PR 3) it sets them instead (``setLineup``: per
// step the player's slot label, then his target row's, once each), once per pass, and logs what
// Yahoo saved. Any other visit only shows the strip, a line saying what a run would do.
//
// On an add page (/nba/<league>/addplayer?apid=<player>) it is the moves executor (#171,
// lib/moves.js), and only when the page was opened with the routine's fragment
// (#pickandroll-moves, #pickandroll-moves-late, #pickandroll-moves-evening) or the side panel's
// link: the routine opens each due queue entry's add page in a tab of its own. It drops the fragment, fetches the league's due
// entries, checks the one whose add is this page's on the rendered claim form, and logs the claim it
// would place; in a live league whose guard holds (PR 3) it places it instead (``fillClaim``), and
// the page Yahoo lands on in the same tab, any page of the league, logs what Yahoo answered. It
// posts nothing for the add page.
//
// On my team page opened with a start-active fragment (#pickandroll-start-active, -late, -evening,
// -daily, or the side panel's button) it is Yahoo's Start Active Players for the rest of the week
// (#215, lib/startactive.js): it posts the page, reads the API's due fresh, and in a live league
// whose guard holds and whose need rule says so, presses Yahoo's button and the dialog's Rest of
// Week Start once each (``pressStartActive``) and logs Yahoo's words; a dry run presses nothing.
//
// On my team page opened with an IL fragment (#pickandroll-il, -il-late, -il-evening, -il-panel)
// it is the IL move an open-spot claim needs first (#214, lib/ilmove.js): it posts the page, reads
// the moves executor's due fresh, and in a live league whose guard holds makes the ``il_first``
// item's move (``moveToIL``: the player's slot label, then the empty IL row's, once each), logs
// it, then goes to the entry's add page with the moves fragment; a dry run clicks nothing.
//
// On my team's drop page (/nba/<league>/<team>/dropplayer) opened with a drop fragment
// (#pickandroll-drop, -drop-late, -drop-evening, -drop-panel) it is a churn's held drop (#221 part
// 3, lib/drop.js): it reads the moves executor's due fresh, takes the next ``drop_first`` item, and
// in a live league whose guard holds drops the held player (``dropPlayer``: the row's button, then
// Yahoo's confirm "Drop <name>" once it reads as planned), put on record before the submit; the
// page Yahoo lands on in the same tab logs what Yahoo answered and goes on to the entry's IL move
// or add page. A dry run clicks nothing.
//
// On my team page opened with the claim read's fragment (#pickandroll-claim-read, #345 step 0,
// lib/claimread.js) it follows the Pending Transactions box's View Details link of the claim the
// API names to Yahoo's page of that claim, and there reads the page's forms, fields and buttons by
// name and words only (never a value) and files the read; it clicks nothing.
//
// Outside ``setLineup``, ``pressStartActive``, ``moveToIL`` and ``dropPlayer`` it clicks and sets only on a page
// opened with a moves fragment: the entry's one drop
// button, the bid and Yahoo's final button, once each (addpage.js keeps Yahoo's alerts on such a
// page as text, so an alert is logged and never blocks the tab). It never reads a form's crumb,
// never fetches a Yahoo page (the tick's post is Yahoo's own script's) and never runs on the draft
// client. It navigates only to follow the players page's Next 25 link during a multi-page read the
// user armed from the side panel, from an IL move's team page to its claim's add page, from
// a held drop's landed page to the entry's IL move or add page, and from my team page to a
// pending claim's page for the claim read.
(() => {
  "use strict";
  const PR = globalThis.PickAndRoll;
  const KEY = "__pickandrollLeague";
  const STRIP = "pickandroll-strip";
  const page = PR.leaguePage(location.href);
  const addPage = page ? null : PR.addPageOf(location.href);
  const dropPage = page || addPage ? null : PR.dropPageOf(location.href);
  // Any page of a league may be the one a claim's submit lands on (#171 PR 3).
  const league = PR.leagueOfPage(location.href);
  if (!league || window[KEY]) return;
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
  let leaving = false;

  /** The live lineup run on record in this browser for the league, logging first one whose log
   * never came (the tab closed mid-run, a log that failed): its run as read, else clicked with its
   * answer not read. The same pass never runs it again. */
  async function lineupRecord(extension) {
    const read = async () => {
      const r = await send({ op: "lineup_record", league: page.league });
      return (r && r.ok && r.data) || null;
    };
    const record = await read();
    if (!record || record.logged || Date.now() - record.at < PR.LINEUP_UNREAD_MS) return record;
    await send({ op: "lineup_log", league: page.league, run: record.run || PR.unreadLineup(record, extension), clicked: true });
    return read();
  }

  /** The live run of ``steps`` on this page (PR 3): the day's tip-offs read, the league's Start
   * Active press of the day before this page's read (``startActiveWait``), the run put on record
   * before the page is touched (once per pass), then ``setLineup`` with STOP, the browser's brake
   * and the league's live guard read again from the API before every change, the first included:
   * no click rests on the steps this visit started from. Answers ``{run, clicked, release}``. */
  async function setRun({ steps, trigger, where, posted, controls, checked, extension, comeback = null }) {
    const runOf = (result, afterStartActive = null) => PR.liveRun({ steps, trigger, page: where, controls, checked, result, afterStartActive, extension });
    const skip = (reason, afterStartActive = null) => ({ run: runOf({ steps: [], outcome: "skipped", reason, after: null }, afterStartActive), clicked: false, release: false });
    if (!steps.tips) return skip("the day's tip-offs are not read: a live run sets nothing without them");
    const sa = await send({ op: "start_active_due" });
    if (!sa || !sa.ok) return skip(`Start Active's due did not answer: ${(sa && sa.error) || "no answer from the extension"}`);
    const row = (sa.data.leagues || []).find((x) => String(x.league) === String(page.league)) || null;
    const pressed = await send({ op: "start_active_record", league: page.league });
    const press = (pressed && pressed.ok && pressed.data) || null;
    const after = Boolean(press && press.day === sa.data.date && press.logged);
    const waits = PR.startActiveWait(row, press, sa.data.date, posted.at);
    if (waits) return skip(waits, after);
    await lineupRecord(extension);
    // On record before the page is touched: the same pass never sets this league again.
    // A comeback's move is its own record (#318): the pass's lineup run still comes after it.
    const guard = comeback ? { trigger: `comeback:${comeback.player}:${trigger}`, run_trigger: trigger } : { trigger };
    const put = await send({ op: "lineup_setting", league: page.league, record: { day: steps.date, mode: "live", ...guard, page: where, read_at: steps.read.at, extension } });
    if (!put || !put.ok) return skip(`the run could not be put on record: ${(put && put.error) || "no answer from the extension"}`, after);
    const stopNow = async () => {
      const brake = await send({ op: "settings" });
      if (brake && brake.ok && brake.data.lineup_executor === "off") return "the browser's brake came on";
      const r = await send({ op: "lineup_steps", league: page.league, date: steps.date });
      if (!r || !r.ok) return "the steps did not answer before a change";
      if (r.data.stop) return "STOP came on";
      const m = PR.lineupMode(r.data);
      if (comeback && !(r.data.comebacks || []).some((x) => x.player === comeback.player && x.drop === comeback.drop && x.stage === "move")) return "the comeback is no longer due";
      return m.mode === "live" ? null : m.refused || "the league is no longer live";
    };
    const result = await PR.setLineup(document, { controls, steps: steps.steps, returns: steps.returns || [], slots: steps.slots || [] }, { stopNow });
    const clicked = result.steps.some((x) => x.outcome === "set" || x.outcome === "failed");
    return { run: runOf(result, after), clicked, release: !clicked };
  }

  /** A visit to my team page: the strip, and a run when ``trigger`` says one was asked for: live
   * where the league is live and its guard holds, else a dry run. ``posted`` is the page's own
   * post. Answers the run logged, or null. */
  /** To ``url`` as a fresh load: a URL differing only by its fragment would run no script. */
  function goOn(url) {
    leaving = true;
    const to = new URL(url, location.href);
    if (to.pathname + to.search !== location.pathname + location.search) location.assign(url);
    else {
      history.replaceState(null, "", to.pathname + to.search + to.hash);
      location.reload();
    }
  }

  /** Today's dated team page with ``fragment``, the page the routine opens: the lineup run needs
   * its post, since a plain page's writes no lineup for the steps to read. */
  async function lineupPage(league, fragment) {
    const r = await send({ op: "lineup_steps", league });
    const url = r && r.ok && r.data.page;
    return url ? `${String(url).split("#")[0]}#${fragment}` : null;
  }

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
    const postedAt = posted.accepted ? posted.at : NaN;
    const mode = PR.lineupMode(steps);
    const chained = PR.comebackChained(location.hash);
    // A comeback runs alone, first (#318): the drop page, this page again for his move, the press,
    // then this run again. His move rests on this page's own read: the steps offer it only once
    // that read no longer shows the drop.
    if (mode.mode === "live" && !chained && !PR.runEnd({ steps, postedAt, controls, problem })) {
      const back = PR.comebackOf(steps, trigger, mode.mode);
      const dropUrl = PR.comebackDropUrl(steps, trigger);
      if (back && dropUrl && back.stage === "drop") {
        strip("live · a comeback's drop comes first: on to the drop page");
        goOn(dropUrl);
        return null;
      }
      if (back && back.stage === "move") {
        const one = PR.comebackSteps(steps, back);
        const done = await setRun({ steps: one, trigger, where, posted, controls, checked: PR.checkSteps(controls, [], steps.slots || []), extension, comeback: back });
        const log = await send({ op: "lineup_log", league: page.league, run: done.run, clicked: done.clicked, release: done.release });
        if (!log || !log.ok) {
          strip(`${done.clicked ? "clicked, " : ""}not logged: ${(log && log.error) || "no answer from the extension"}`);
          return null;
        }
        const moved = done.run.steps.find((x) => x.kind === "return");
        const press = moved && moved.outcome === "set" ? PR.comebackPress(steps.back, trigger) : null;
        if (press) {
          strip(`${PR.stripText({ steps, run: done.run })} · on to the press`);
          goOn(press);
          return null;
        }
        // A move answered any other way leaves the page unknown: the pass's run goes on from a
        // fresh load, with no comeback in it, so a move Yahoo refuses never costs the lineup, and
        // the next pass resumes at the move.
        if (moved && moved.outcome !== "skipped") {
          strip(PR.stripText({ steps, run: done.run }));
          goOn(`${where}#${PR.comebackChainOf(trigger)}`);
          return null;
        }
      }
    }
    // Live, a run that ends before any step logs as live; one that goes on sets the steps. A
    // comeback the steps offered and this visit did not run is under the run's skipped (#346).
    const rest = PR.comebackDone(steps, PR.comebackWhy({ mode: mode.mode, trigger, chained }));
    const end = mode.mode === "live" ? PR.runEnd({ steps: rest, postedAt, controls, problem }) : null;
    let run;
    let clicked = false;
    let release = false;
    if (mode.mode !== "live" || end) {
      run = PR.dryRun({ steps: rest, trigger, page: where, postedAt, controls, problem, checked, extension, refused: mode.refused, mode: end ? "live" : "dry_run" });
    } else ({ run, clicked, release } = await setRun({ steps: rest, trigger, where, posted, controls, checked, extension }));
    const logged = await send({ op: "lineup_log", league: page.league, run, clicked, release });
    if (!logged || !logged.ok) {
      strip(`${clicked ? "clicked, " : ""}not logged: ${(logged && logged.error) || "no answer from the extension"}`);
      return null;
    }
    strip(PR.stripText({ steps, run }));
    return run;
  }

  async function visit(trigger) {
    if (running) return null;
    running = true;
    let run;
    try {
      const posted = await post();
      run = await lineup(trigger, posted);
      // A routine's run happens once: a reload of the page is a plain visit.
      if (trigger && location.hash && !leaving) history.replaceState(null, "", location.pathname + location.search);
    } finally {
      running = false;
    }
    // A live run that set a swap: Start Active carries it to the rest of the week (#289).
    if (PR.pressAfterLineup(run)) await afterLineup(run);
    return run;
  }

  /** After a live lineup run that set a swap on a later day than today (#289, the master's
   * ruling): this page's labels read once settled for the set day's diff, kept in the worker for
   * the press, and the tab goes to today's team page with the after-lineup fragment, where Start
   * Active runs as on any start-active page. A set of today, a league not due or live, or STOP:
   * the tab stays. Pressing from today's page keeps Today Only off the day just set; Rest of
   * Week covers it either way. */
  async function afterLineup(run) {
    const r = await send({ op: "start_active_due" });
    if (!r || !r.ok) return;
    const row = (r.data.leagues || []).find((x) => String(x.league) === String(page.league));
    if (r.data.stop || !row || row.error || !row.need || row.mode !== "live" || !PR.laterDay(run.day, r.data.date)) return;
    const next = PR.afterLineupUrl(row.page);
    if (!next) return;
    const labels = await PR.settledLabels(document, { cap: AFTER_LINEUP_SETTLE_MS });
    const kept = await send({ op: "after_lineup_put", league: page.league, handoff: { set_day: run.day, diff: PR.setDayDiff(run.steps, labels.lineup) } });
    if (!kept || !kept.ok) return;
    strip(`${PR.stripText({ run })} · Start Active from today's page`);
    location.assign(next);
  }

  // The side panel's "Set lineup now": post the page again and run from that post.
  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (!msg || msg.op !== "lineup_run" || !page) return false;
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
      // Yahoo's open-spot words only (#214), never the rest of the page's text.
      empty: (/you currently have \d+ empty spots? on your roster/i.exec(textOf(document.body)) || [])[0] || null,
    };
  }

  /** The team page's "Pending Transactions" box (#239), found by its heading: each View Details
   * link's href and words, for ``PR.pendingBid``; null when the page has no such box. */
  function pendingLines() {
    const LINK = 'a[href*="viewwaiver"]';
    let box = [...document.querySelectorAll("span, h2, h3, h4")].find((h) => textOf(h) === PR.PENDING_HEADING) || null;
    for (let up = 0; box && up < 5 && !box.querySelector(LINK); up++) box = box.parentElement;
    if (!box || !box.querySelector(LINK)) return null;
    return [...box.querySelectorAll(LINK)].map((a) => ({ href: a.getAttribute("href") || "", text: textOf(a) }));
  }

  /** The page Yahoo landed on after a claim's submit, for ``readLanded``: its path, heading (not
   * one of Yahoo's header or navigation), whether the claim form is back, its notices and errors,
   * whether it shows the add with the word "pending", and whether it links the claim (``line``'s
   * add and drop) among the pending transactions: Yahoo's View Waiver link carries the claim's id,
   * ``<team>_<add>_<drop>``. The claim's bid is read twice: off the "Pending Transactions" box
   * (``bid_box``, #239) and off the link's own text (``bid_link``, #214). Ids and Yahoo's own short
   * messages only. */
  function landedControls(line) {
    const texts = (sel) => [...document.querySelectorAll(sel)].map(textOf).filter((x) => x && x.length < 300);
    const errors = texts(".error, .Error, .F-negative, [class*='Alert-error'], [class*='alert-error']");
    const shown = Boolean(document.querySelector(`[data-ys-playerid="${line.add}"]`));
    const chrome = (h) => typeof h.closest === "function" && Boolean(h.closest("header, nav, [role=navigation], #ybar"));
    const id = new RegExp(`[?&]claim_id=\\d+_${line.add}_${line.drop == null ? 0 : line.drop}(?:&|$)`);
    return {
      path: location.pathname + location.search,
      heading: [...document.querySelectorAll("h1, h2, h3")].filter((h) => !chrome(h)).map(textOf).find((x) => x && !/^yahoo/i.test(x)) || null,
      form: Boolean(document.querySelector(`form#${PR.FORM_ID}`)),
      notes: texts(".Alert, .alert, [role=alert], .F-positive, .success, .Success, .notice, .Notice").filter((x) => !errors.includes(x)),
      errors,
      pending: shown && /pending/i.test(textOf(document.body)),
      claim: [...document.querySelectorAll('a[href*="viewwaiver"]')].some((a) => id.test(a.getAttribute("href") || "")),
      // The claim's bid on the "Pending Transactions" box's line (#239), by ``PR.pendingBid``.
      bid_box: PR.pendingBid(pendingLines(), line),
      // The claim's bid on its pending line, the link's own text (#214): "Waiver 1 (Oct 29): Bid $1
      // for …", no "Bid $" when it is $0; null when the link is not there or not in those words.
      bid_link: (() => {
        const link = [...document.querySelectorAll('a[href*="viewwaiver"]')].find((a) => id.test(a.getAttribute("href") || ""));
        const text = link ? textOf(link) : "";
        if (!/^Waiver \d+ \(/.test(text)) return null;
        const m = /\bBid \$(\d+)/.exec(text);
        return m ? Number(m[1]) : 0;
      })(),
    };
  }

  /** What a landing read keeps for the run (#341): the page, its heading and the words read, and
   * the claim's bid. */
  const seenOf = (raw) => ({ path: raw.path, heading: raw.heading, form: raw.form, notes: raw.notes, errors: raw.errors, ...PR.landedBid(raw.bid_box, raw.bid_link) });

  /** On any page of the league: a claim this tab submitted and whose answer is not logged yet
   * (the worker keeps it) is read from this page and its live pass logged. An answer not
   * recognised, or the claim form's own path, is settled first on my team page (#341): the
   * record keeps this read and the tab goes there, where the Pending Transactions box says
   * whether the claim is in. The worker drops the record only once the API has the pass.
   * Answers the pass logged, or null. */
  async function landed() {
    const r = await send({ op: "moves_landed", league });
    if (!r || !r.ok || !r.data) return null;
    const record = r.data;
    const raw = landedControls(record.line);
    const action = (record.line.controls && record.line.controls.action) || null;
    const team = PR.teamPageOf(action);
    let answer;
    let seen;
    if (record.settle) {
      // The second read, on my team page or wherever the tab went: the box decides, else the
      // first landing's answer stands.
      answer = PR.settleLanded(record.settle.answer, raw, pendingLines());
      seen = { ...seenOf(raw), first: record.settle.seen };
    } else {
      answer = PR.readLanded({ ...raw, action });
      seen = seenOf(raw);
      if (PR.wantsSettle(answer) && team) {
        if (location.pathname.replace(/\/+$/, "") === team) answer = PR.settleLanded(answer, raw, pendingLines());
        else {
          const kept = await send({ op: "moves_settling", league, id: record.line.id, settle: { answer, seen } });
          if (kept && kept.ok) {
            movesStrip("live · Yahoo's answer not recognised here: reading my team page's pending transactions…");
            leaving = true;
            location.assign(`${location.origin}${team}`);
            return null;
          }
        }
      }
    }
    const run = PR.landedPass(record, answer, seen, extensionVersion());
    const logged = await send({ op: "moves_log", league, run });
    if (!logged || !logged.ok) {
      movesStrip(`claim submitted, not logged: ${(logged && logged.error) || "no answer from the extension"}`);
      return null;
    }
    movesStrip(PR.landedStripText(run));
    return run;
  }

  /** Claims submitted in the league whose answer never came (the tab closed, a page the reader
   * missed): each is logged before this pass, ``claimed`` with its answer not read, and never
   * submitted again. Answers the submits still on record: in flight, or refused by the log. */
  async function unread() {
    const submits = async () => {
      const r = await send({ op: "moves_submits", league });
      return (r && r.ok && r.data) || [];
    };
    const now = Date.now();
    const records = await submits();
    const stale = records.filter((x) => now - x.at >= PR.LANDING_MS);
    for (const record of stale) {
      // A landing read on record and never settled (#341) keeps its answer: the claim form's own
      // path stays failed; one not recognised is claimed, its answer not read.
      const first = record.settle || null;
      await send({ op: "moves_log", league, run: PR.landedPass(record, first ? first.answer : null, first ? first.seen : null, extensionVersion()) });
    }
    return stale.length ? submits() : records;
  }

  /** The moves executor on this add page, opened with ``trigger``'s fragment: the league's due
   * entries, the one whose add is this page's checked on the rendered form, and the pass logged;
   * in a live league whose guard holds, a claim that passes is submitted instead and its pass is
   * the landed page's. No entry for this player: nothing is logged. Answers the pass logged, or
   * null. */
  async function claim(trigger) {
    // A routine's pass happens once: a reload of the page is a plain visit.
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    const settings = await send({ op: "settings" });
    if (settings && settings.ok && settings.data.moves_executor === "off") {
      movesStrip(PR.movesStripText({ browserOff: true }));
      return null;
    }
    const records = await unread();
    const submitted = new Set(records.map((x) => x.line.id));
    // ``due`` is read fresh on each page and never kept; the claims in flight count as placed.
    const r = await send({ op: "moves_due", league: addPage.league });
    if (!r || !r.ok) {
      movesStrip(PR.movesStripText({ error: (r && r.error) || "no answer from the extension" }));
      return null;
    }
    const due = PR.withInflight(r.data, records);
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
      if (submitted.has(entry.id)) {
        movesStrip(`${PR.passMode(due).mode === "live" ? "live" : "dry run"} · a submit of this claim awaits Yahoo's answer: nothing done`);
        return null;
      }
      const readAt = new Date().toISOString();
      const seen = PR.readAddPage(addControls(), entry.from);
      const why = PR.entryProblem(entry, due);
      let check = why ? { outcome: "skipped", reason: why } : PR.pageCheck(entry, seen, due);
      // A full roster after this browser moved the held player on a later day's page (#214).
      if (entry.held_move) {
        const moved = await send({ op: "il_record", entry: entry.id });
        check = PR.claimWaits(check, moved && moved.ok ? moved.data : null, due.date);
      }
      if (check.outcome === "would_claim" && PR.passMode(due).mode === "live") {
        const held = PR.submitProblem(entry, seen);
        if (held) check = { outcome: "skipped", reason: held };
        else {
          const line = PR.moveCheck(entry, check, seen, due, readAt);
          // On record before the page is touched: no pass submits this entry again.
          const record = { day: due.date, trigger, line, cap: r.data.cap, done: r.data.done };
          const kept = await send({ op: "moves_submitting", league, record });
          const placed = kept && kept.ok ? await PR.fillClaim(document, entry) : { outcome: "skipped", reason: "the submit could not be put on record" };
          if (placed === null) {
            movesStrip(`live · claim submitted for $${line.bid}, ${PR.dropWords(line.drop)}: reading Yahoo's answer…`);
            return null;
          }
          check = placed;
        }
      }
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

  // ---------------------------------------------------------------- Start Active (#215)
  const saStrip = (line) => strip(line, "start active");
  /** How long the after-lineup reads wait for the page to settle (#289). */
  const AFTER_LINEUP_SETTLE_MS = 5 * 1000;

  /** Yahoo's Start Active control on my team page as a plain object for ``readStartActive``:
   * the buttons in its root (visible, disabled), any outside it, the dialog (there, open) and its
   * Rest of Week Starts. Nothing is read from the roster form. */
  function startActiveControls() {
    const visible = (el) => typeof el.getClientRects === "function" && el.getClientRects().length > 0;
    const inside = [...document.querySelectorAll(`${PR.SA_OVERLAY} ${PR.SA_BUTTON}`)];
    const dialog = document.querySelector(PR.SA_DIALOG);
    return {
      path: location.pathname + location.search,
      buttons: inside.map((b) => ({ visible: visible(b), disabled: Boolean(b.disabled) })),
      outside: document.querySelectorAll(PR.SA_BUTTON).length - inside.length,
      dialog: dialog ? { present: true, open: Boolean(dialog.open) } : null,
      intervals: dialog ? [...dialog.querySelectorAll(PR.SA_INTERVAL)].map((b) => ({ disabled: Boolean(b.disabled) })) : [],
    };
  }

  /** The press on record in this browser for the league, logging first one whose run never
   * reached the log (the tab closed mid-run, a log that failed): its run as read, else pressed
   * with its answer not read. It is never pressed again for it. */
  async function pressRecord(extension) {
    const read = async () => {
      const r = await send({ op: "start_active_record", league: page.league });
      return (r && r.ok && r.data) || null;
    };
    const record = await read();
    if (!record || record.logged || Date.now() - record.at < PR.SA_UNREAD_MS) return record;
    await send({ op: "start_active_log", league: page.league, run: record.run || PR.unreadRun(record, extension), pressed: true });
    return read();
  }

  /** Yahoo's Start Active Players on my team page, opened with ``trigger``'s fragment (#215): the
   * page posted, the API's due read fresh and my league's row taken. Under STOP the run says it
   * stopped; a league not due logs nothing; a dry run, or a live league whose guard refuses, logs
   * ``would_start`` and presses nothing; a live league presses once a day, the press put on
   * record before the page is touched (``pressStartActive``), unless the roster changed since.
   * Answers the run logged, or null. */
  async function startActive(trigger) {
    // A routine's run happens once: a reload of the page is a plain visit.
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    if (running) return null;
    running = true;
    try {
      const settings = await send({ op: "settings" });
      if (settings && settings.ok && settings.data.moves_executor === "off") {
        saStrip(PR.startActiveStripText({ browserOff: true }));
        return null;
      }
      const posted = await post();
      const extension = extensionVersion();
      const record = await pressRecord(extension);
      const r = await send({ op: "start_active_due" });
      if (!r || !r.ok) {
        saStrip(PR.startActiveStripText({ error: (r && r.error) || "no answer from the extension" }));
        return null;
      }
      const due = r.data;
      const row = (due.leagues || []).find((x) => String(x.league) === String(page.league));
      if (!row) {
        saStrip(PR.startActiveStripText({ none: "not armed here: the moves executor is off or the league is private" }));
        return null;
      }
      if (row.error) {
        saStrip(PR.startActiveStripText({ error: row.error }));
        return null;
      }
      if (settings && settings.ok && PR.startActiveBraked(settings.data, row)) {
        saStrip(PR.startActiveStripText({ browserOff: true }));
        return null;
      }
      // Opened from a later day's lineup set (#289): the set day's diff its page read.
      const handoff = trigger === "after_lineup" ? await send({ op: "after_lineup_take", league: page.league }) : null;
      const setDay = (handoff && handoff.ok && handoff.data) || null;
      const where = location.pathname + location.search;
      const base = { row, day: due.date, trigger, page: where, extension };
      const mode = PR.startActiveMode(row);
      let run;
      let pressed = false;
      let release = false;
      if (due.stop) run = PR.startActiveRun({ ...base, mode: row.mode === "live" ? "live" : "dry_run", outcome: "stopped", reason: due.reason });
      else if (!row.need) {
        saStrip(PR.startActiveStripText({ row }));
        return null;
      } else {
        const controls = PR.readStartActive(startActiveControls());
        const dialog = document.querySelector(PR.SA_DIALOG);
        const rows = PR.dialogRows(dialog ? dialog.textContent : "");
        // Live, the row's roster must be this page's (the same-day guard compares it): the post taken.
        const unposted = mode.mode === "live" && !posted.accepted ? "the page was not posted, so its roster is not known" : null;
        // The live lineup run on record lifts the same-day guard once it set a swap (#289).
        const ran = mode.mode === "live" && record && record.day === due.date ? await send({ op: "lineup_record", league: page.league }) : null;
        const lineupRan = (ran && ran.ok && ran.data) || null;
        const problem = PR.startActiveProblem(row, page, controls) || unposted || (mode.mode === "live" ? PR.sameDayProblem(record, row, due.date, lineupRan) : null);
        if (problem) run = PR.startActiveRun({ ...base, ...rows, mode: mode.mode, outcome: "skipped", reason: problem, controls });
        else if (mode.mode !== "live") run = PR.startActiveRun({ ...base, ...rows, mode: "dry_run", outcome: "would_start", reason: mode.reason, controls });
        else {
          // On record before the page is touched: no run presses this league again today.
          const put = await send({
            op: "start_active_pressing",
            league: page.league,
            record: { day: due.date, trigger, reasons: row.reasons || [], roster: row.roster || null, page: where },
          });
          if (!put || !put.ok) {
            const why = (put && put.error) || "no answer from the extension";
            run = PR.startActiveRun({ ...base, ...rows, mode: "live", outcome: "skipped", reason: `the press could not be put on record: ${why}`, controls });
          } else {
            const before = trigger === "after_lineup" ? PR.readLabels(document).lineup : null;
            const got = await PR.pressStartActive(document);
            pressed = got.outcome !== "skipped";
            release = !pressed;
            let diffs = null;
            let reason = got.reason;
            if (trigger === "after_lineup") {
              // Today's labels after Yahoo's answer, once its refresh shows (or 5 s): what the press changed today.
              const after = pressed ? (await PR.settledLabels(document, { cap: AFTER_LINEUP_SETTLE_MS, until: (l) => Object.keys(PR.pressChanged(before, l.lineup)).length > 0 })).lineup : before;
              diffs = { set_day: setDay ? { day: setDay.set_day, diff: setDay.diff } : null, today: { day: due.date, changed: PR.pressChanged(before, after) } };
              const range = got.today && got.today.range;
              if (pressed && range && PR.rangeIsDay(range, due.date) === false) reason = [reason, `Today Only read ${range}, not today (${due.date})`].filter(Boolean).join("; ");
            }
            run = PR.startActiveRun({ ...base, mode: "live", outcome: got.outcome, reason, message: got.message, today: got.today, rest_of_week: got.rest_of_week, diffs, controls });
          }
        }
      }
      const logged = await send({ op: "start_active_log", league: page.league, run, pressed, release });
      if (!logged || !logged.ok) {
        saStrip(`${pressed ? "pressed, " : ""}not logged: ${(logged && logged.error) || "no answer from the extension"}`);
        return null;
      }
      saStrip(PR.startActiveStripText({ run }));
      return run;
    } finally {
      running = false;
    }
  }

  // The side panel's "Start active players now": the same run, its trigger the panel's.
  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (!msg || msg.op !== "start_active_run" || !page || page.kind !== "team") return false;
    startActive("panel").then(
      (run) => reply({ ok: true, data: { run } }),
      (e) => reply({ ok: false, error: String((e && e.message) || e) }),
    );
    return true;
  });

  // ---------------------------------------------------------------- the IL move (#214)
  const ilStrip = (line) => strip(line, "IL move");

  /** Yahoo's swap controls on my team page as a plain object for ``readILPage``: whether the
   * manager is editable, and each roster row's player id, classes that matter (editable, empty),
   * status code (#342) and slot labels (slot, a button, visible). No field is read. */
  function ilControls() {
    const manager = document.querySelector(PR.IL_MANAGER);
    const visible = (el) => typeof el.getClientRects === "function" && el.getClientRects().length > 0;
    return {
      path: location.pathname + location.search,
      editable: manager ? manager.getAttribute("data-is-editable") === "true" : null,
      rows: [...document.querySelectorAll(PR.IL_ROWS)].map((tr) => {
        const id = tr.querySelector("[data-ys-playerid]");
        const flag = tr.querySelector(PR.IL_STATUS);
        const code = flag ? flag.querySelector("span[title]") || flag : null;
        return {
          player: id ? Number(id.getAttribute("data-ys-playerid")) : null,
          editable: tr.classList.contains("editable"),
          empty: tr.classList.contains("empty-bench"),
          status: code ? String(code.textContent || "").trim() || null : null,
          labels: [...tr.querySelectorAll(PR.IL_LABEL)].map((l) => ({ pos: l.getAttribute("data-pos"), button: l.getAttribute("role") === "button", visible: visible(l) })),
        };
      }),
    };
  }

  /** The move on record in this browser for ``entry``, logging first one whose run never reached
   * the log: its run as read, else clicked with its answer not read. It is never made again. */
  async function ilRecord(entry, extension) {
    const read = async () => {
      const r = await send({ op: "il_record", entry });
      return (r && r.ok && r.data) || null;
    };
    const record = await read();
    if (!record || record.logged || Date.now() - record.at < PR.IL_UNREAD_MS) return record;
    await send({ op: "il_log", league: page.league, run: record.run || PR.unreadIL(record, extension), clicked: true });
    return read();
  }

  /** The IL move on my team page opened with ``trigger``'s IL fragment (#214): the page posted,
   * the moves executor's due read fresh and the ``il_first`` item whose page this is taken. Under
   * STOP the run says it stopped; no item logs nothing; a dry run, or a live league whose guard
   * refuses, logs ``would_move`` and clicks nothing; a live league makes the move once, put on
   * record before the page is touched (``moveToIL``). After any logged run but a stop, the tab
   * goes to the entry's add page with the moves fragment, where the claim reads the page again.
   * Answers the run logged, or null. */
  async function ilMove(trigger) {
    // A routine's run happens once: a reload of the page is a plain visit.
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    if (running) return null;
    running = true;
    try {
      const settings = await send({ op: "settings" });
      if (settings && settings.ok && settings.data.moves_executor === "off") {
        ilStrip(PR.ilStripText({ browserOff: true }));
        return null;
      }
      await post();
      const extension = extensionVersion();
      const r = await send({ op: "moves_due", league: page.league });
      if (!r || !r.ok) {
        ilStrip(PR.ilStripText({ error: (r && r.error) || "no answer from the extension" }));
        return null;
      }
      const due = r.data;
      if (due.mode === "off") {
        ilStrip(PR.ilStripText({ none: "the moves executor is off in this league" }));
        return null;
      }
      const where = location.pathname + location.search;
      const mode = PR.passMode(due);
      let run;
      let item = null;
      let clicked = false;
      let release = false;
      if (due.stop) run = PR.ilRun({ day: due.date, trigger, mode: mode.mode, outcome: "stopped", reason: due.reason, page: where, extension });
      else {
        item = PR.ilItemFor(due, where);
        if (!item) {
          ilStrip(PR.ilStripText({ none: "no IL move due on this page" }));
          return null;
        }
        const record = await ilRecord(item.entry, extension);
        const controls = PR.readILPage(ilControls(), item);
        const base = { item, day: due.date, trigger, page: where, controls, extension };
        const done = mode.mode === "live" && record && record.day === due.date ? "this move was made from this browser today" : null;
        const problem = PR.ilProblem(item, controls) || done;
        if (problem) run = PR.ilRun({ ...base, mode: mode.mode, outcome: "skipped", reason: problem });
        else if (mode.mode !== "live") run = PR.ilRun({ ...base, mode: "dry_run", outcome: "would_move", reason: mode.refused });
        else {
          // On record before the page is touched: the move is never made twice.
          const put = await send({
            op: "il_moving",
            league: page.league,
            record: { day: due.date, entry: item.entry, player: item.player, slot: item.slot, dated: item.date, trigger, page: where },
          });
          if (!put || !put.ok) {
            const why = (put && put.error) || "no answer from the extension";
            run = PR.ilRun({ ...base, mode: "live", outcome: "skipped", reason: `the move could not be put on record: ${why}` });
          } else {
            const got = await PR.moveToIL(document, item);
            clicked = got.outcome !== "skipped";
            release = !clicked;
            run = PR.ilRun({ ...base, mode: "live", outcome: got.outcome, reason: got.reason, message: got.message });
          }
        }
      }
      const logged = await send({ op: "il_log", league: page.league, run, clicked, release });
      if (!logged || !logged.ok) {
        ilStrip(`${clicked ? "clicked, " : ""}not logged: ${(logged && logged.error) || "no answer from the extension"}`);
        return null;
      }
      const next = run.outcome === "stopped" ? null : PR.ilNext(due, item, trigger, location.origin);
      ilStrip(PR.ilStripText({ run, next }));
      if (next) location.assign(next);
      return run;
    } finally {
      running = false;
    }
  }

  // ---------------------------------------------------------------- the held drop (#221 part 3)
  const dropStrip = (line) => strip(line, "held drop");

  /** Yahoo's drop page as a plain object for ``readDropPage``: whether the form is there, its
   * stage, each row button's player (its attribute trimmed), whether it shows and whether the row
   * carries his name link, and how many drop boxes are ticked. No token is read. */
  function dropControls() {
    const form = document.querySelector(PR.DROP_FORM);
    const visible = (el) => typeof el.getClientRects === "function" && el.getClientRects().length > 0;
    const elements = form ? [...form.elements] : [];
    return {
      path: location.pathname,
      form: Boolean(form),
      stage: elements.filter((el) => el.name === "stage").map((el) => String(el.value)).join(", ") || null,
      rows: form
        ? [...form.querySelectorAll(PR.DROP_ROW_BUTTON)].map((b) => {
            const player = String(b.getAttribute(PR.DROP_VALUE_ATTR) ?? "").trim();
            const tr = b.closest("tr");
            const name = tr ? [...tr.querySelectorAll(PR.DROP_NAME)].some((a) => a.getAttribute("data-ys-playerid") === player && textOf(a)) : false;
            return { player, name, visible: visible(b) };
          })
        : [],
      ticked: elements.filter((el) => el.name === "dpid" && el.checked).length,
    };
  }

  /** The held drops on record in this browser for ``items``, by entry; a submitted one whose run
   * never reached the log is logged first, unconfirmed, and never submitted again. */
  async function dropRecords(items, extension) {
    const read = async (entry) => {
      const r = await send({ op: "drop_record", league: dropPage.league, entry });
      return (r && r.ok && r.data) || null;
    };
    const out = {};
    for (const x of items) {
      let record = await read(x.entry);
      if (record && !record.logged && Date.now() - record.at >= PR.DROP_LANDING_MS) {
        await send({ op: "drop_log", league: dropPage.league, run: PR.landedDrop(record, null, extension) });
        record = await read(x.entry);
      }
      out[x.entry] = record;
    }
    return out;
  }

  /** The held drop on the drop page opened with ``trigger``'s fragment: the moves executor's due
   * read fresh and the next ``drop_first`` item taken. Under STOP the run says it stopped; no item
   * logs nothing; a dry run, or a live league whose guard refuses, logs ``would_drop`` and clicks
   * nothing; a live league makes the drop once, put on record before the submit (``dropPlayer``),
   * and the page Yahoo lands on logs it. Answers the run logged, or null. */
  async function heldDrop(trigger) {
    // Opened by a comeback's chain, the item comes from today's steps and the page goes on to the
    // pass's lineup run whatever it finds here (#318), unless a submit is waiting for Yahoo's
    // answer or STOP holds.
    let onward = PR.comebackOnward(location.hash);
    const chained = Boolean(onward);
    // A routine's run happens once: a reload of the page is a plain visit.
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    if (running) return null;
    running = true;
    let back = null;
    try {
      const settings = await send({ op: "settings" });
      if (settings && settings.ok && settings.data.moves_executor === "off") {
        dropStrip(PR.dropStripText({ browserOff: true }));
        return null;
      }
      const extension = extensionVersion();
      const r = await send({ op: "moves_due", league: dropPage.league });
      if (!r || !r.ok) {
        dropStrip(PR.dropStripText({ error: (r && r.error) || "no answer from the extension" }));
        return null;
      }
      const due = r.data;
      if (due.mode === "off") {
        dropStrip(PR.dropStripText({ none: "the moves executor is off in this league" }));
        return null;
      }
      const where = location.pathname;
      const mode = PR.passMode(due);
      let run;
      if (due.stop) {
        onward = null;
        run = PR.dropRun({ day: due.date, trigger, mode: mode.mode, outcome: "stopped", reason: due.reason, page: where, extension });
      } else {
        // The chain's drop comes from today's steps, read fresh here: its gates are theirs.
        const s = chained ? await send({ op: "lineup_steps", league: dropPage.league }) : null;
        const items = chained ? (s && s.ok ? PR.comebackDrops(s.data) : []) : due.drop_first || [];
        const records = await dropRecords(items, extension);
        const item = PR.dropItemFor({ drop_first: items }, where, (x) => PR.ranToday(records[x.entry], due.date, mode.mode, trigger));
        if (!item) {
          dropStrip(PR.dropStripText({ none: "no held drop due on this page" }));
          return null;
        }
        back = chained ? item.back || null : null;
        const controls = PR.readDropPage(dropControls(), item);
        const base = { item, day: due.date, trigger, page: where, controls, extension };
        const problem = PR.dropProblem(controls);
        if (problem) run = PR.dropRun({ ...base, mode: mode.mode, outcome: "skipped", reason: problem });
        else if (mode.mode !== "live") run = PR.dropRun({ ...base, mode: "dry_run", outcome: "would_drop", reason: mode.refused });
        else {
          let refused = null;
          // On record before the submit: the drop is never submitted twice.
          const onConfirm = async (confirm) => {
            const put = await send({
              op: "drop_dropping",
              league: dropPage.league,
              record: { day: due.date, entry: item.entry, player: item.player, trigger, page: where, back, controls: { ...controls, confirm } },
            });
            refused = put && put.ok ? null : (put && put.error) || "no answer from the extension";
            return !refused;
          };
          const got = await PR.dropPlayer(document, item, { onConfirm });
          if (got === null) {
            onward = null;
            dropStrip(`live · drop of ${item.player} submitted: reading Yahoo's answer…`);
            return null;
          }
          const reason = refused ? `${got.reason}: ${refused}` : got.reason;
          run = PR.dropRun({ ...base, controls: { ...controls, confirm: got.confirm }, mode: "live", outcome: got.outcome, reason, message: got.message });
        }
      }
      const logged = await send({ op: "drop_log", league: dropPage.league, run });
      if (!logged || !logged.ok) {
        dropStrip(`not logged: ${(logged && logged.error) || "no answer from the extension"}`);
        return null;
      }
      dropStrip(PR.dropStripText({ run }));
      return run;
    } finally {
      running = false;
      const to = onward ? await lineupPage(dropPage.league, onward) : null;
      if (to) goOn(to);
    }
  }

  /** On any page of the league: a held drop this tab submitted and whose run is not logged yet
   * (the worker keeps it) is read from this page (Yahoo's alert codes in the URL, its notice) and
   * logged; once he is dropped, the tab goes on to the entry's IL move or add page from the due
   * read again. A comeback's chain goes back to today's dated page, whose fresh read confirms the
   * drop before his move; one not dropped or not logged runs the pass's lineup alone. Answers
   * whether the tab is going on. */
  async function dropLanded() {
    const r = await send({ op: "drop_landed", league });
    if (!r || !r.ok || !r.data) return false;
    const record = r.data;
    const notices = [...document.querySelectorAll(".Alert, [role=alert]")].map(textOf).filter((x) => x && x.length < 300);
    const raw = {
      path: location.pathname,
      alerts: new URLSearchParams(location.search).get("_global_alerts"),
      notices,
      shown: Boolean(document.querySelector(`[data-ys-playerid="${record.player}"]`)),
    };
    const run = PR.landedDrop(record, PR.readDropLanded(raw), extensionVersion());
    const logged = await send({ op: "drop_log", league, run });
    const ok = logged && logged.ok;
    if (!ok) dropStrip(`drop submitted, not logged: ${(logged && logged.error) || "no answer from the extension"}`);
    let next = null;
    if (record.back) {
      // A drop of the player himself leaves no move: on to the press, the roster changed.
      const himself = record.entry === `comeback:${record.player}`;
      if (ok && run.outcome === "dropped" && himself) next = PR.comebackPress(record.back, record.trigger);
      else {
        const on = !ok || run.outcome !== "dropped" ? PR.comebackChainOf(record.trigger) : PR.comebackMoveOf(record.trigger);
        next = on ? await lineupPage(league, on) : null;
      }
    } else if (ok && run.outcome === "dropped") {
      const due = await send({ op: "moves_due", league });
      next = due && due.ok ? PR.dropNext(due.data, record.entry, record.trigger, location.origin) : null;
    }
    if (ok) dropStrip(PR.dropStripText({ run, next }));
    if (next) goOn(next);
    return Boolean(next);
  }

  // ---------------------------------------------------------------- a claim page's read (#345 step 0)
  const claimStrip = (line) => strip(line, "claim read");
  const claimPage = PR.claimPageOf(location.href);

  /** Yahoo's page of a claim as a plain object for ``PR.claimPageRead``: its URL, heading (not
   * one of Yahoo's header or navigation), notices, its forms (names, method, action, each
   * field's kind and names, its buttons and links) and the buttons and claim links outside them.
   * No field's value is read: an input button's label is, as its words. Nothing is clicked. */
  function claimControls() {
    const chromeOf = (el) => typeof el.closest === "function" && Boolean(el.closest("header, nav, [role=navigation], #ybar"));
    const BUTTONS = new Set(["submit", "button", "reset", "image"]);
    const typeOf = (el) => String(el.getAttribute("type") || (el.tagName === "BUTTON" ? "submit" : "text")).toLowerCase();
    const control = (el) => {
      const tag = el.tagName.toLowerCase();
      const type = tag === "a" ? null : typeOf(el);
      return {
        tag,
        type,
        name: el.getAttribute("name"),
        id: el.getAttribute("id"),
        text: tag === "input" ? null : textOf(el),
        label: tag === "input" && BUTTONS.has(type) ? el.getAttribute("value") : null,
        href: tag === "a" ? el.getAttribute("href") : null,
      };
    };
    const isButton = (el) => el.tagName === "BUTTON" || (el.tagName === "INPUT" && BUTTONS.has(typeOf(el)));
    const CONTROLS = "button, input[type=submit], input[type=button], input[type=reset], input[type=image], a[href]";
    const forms = [...document.querySelectorAll("form")].filter((f) => !chromeOf(f));
    const texts = (sel) => [...document.querySelectorAll(sel)].filter((x) => !chromeOf(x)).map(textOf).filter((x) => x && x.length < 300);
    const claimish = /waiver|claim|cancel|edit|delete|remove|change|modify|back/i;
    const outside = [...document.querySelectorAll("button, a[href]")].filter(
      (el) => !el.closest("form") && !chromeOf(el) && (el.tagName === "BUTTON" || claimish.test(el.getAttribute("href") || "") || claimish.test(textOf(el)))
    );
    return {
      url: location.href,
      heading: [...document.querySelectorAll("h1, h2, h3")].filter((h) => !chromeOf(h)).map(spacedText).find((x) => x && !/^yahoo/i.test(x)) || null,
      notes: texts(".Alert, .alert, [role=alert], .F-positive, .success, .Success, .notice, .Notice, .error, .Error, .F-negative"),
      forms: forms.map((f) => ({
        id: f.getAttribute("id"),
        name: f.getAttribute("name"),
        method: f.getAttribute("method") || "get",
        action: f.getAttribute("action"),
        fields: [...f.querySelectorAll("input, select, textarea")]
          .filter((el) => !isButton(el))
          .map((el) => ({ tag: el.tagName.toLowerCase(), type: el.tagName === "INPUT" ? typeOf(el) : null, name: el.getAttribute("name"), id: el.getAttribute("id") })),
        controls: [...f.querySelectorAll(CONTROLS)].map(control),
      })),
      controls: outside.map(control),
    };
  }

  /** The read's due, fresh, for this league: null (the strip says why) when the browser's brake
   * is on, the due does not answer, or no read is due here. */
  async function claimReadDue() {
    const settings = await send({ op: "settings" });
    if (settings && settings.ok && settings.data.moves_executor === "off") {
      claimStrip(PR.claimReadStripText({ skipped: "the browser's brake is on" }));
      return null;
    }
    const due = await send({ op: "claim_page_due" });
    if (!due || !due.ok) {
      claimStrip(PR.claimReadStripText({ error: (due && due.error) || "no answer from the extension" }));
      return null;
    }
    if (!due.data.due || String(due.data.league) !== String(league)) {
      claimStrip(PR.claimReadStripText({ skipped: due.data.due ? `the read is due in league ${due.data.league}` : due.data.reason || "not due" }));
      return null;
    }
    return due.data;
  }

  /** On my team page opened with the read's fragment: the Pending Transactions box's View
   * Details link of the due claim (else its first), followed with the fragment. Nothing clicked. */
  async function claimReadFrom() {
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    const due = await claimReadDue();
    if (!due) return;
    const href = PR.claimLink(pendingLines(), due);
    if (!href) {
      claimStrip(PR.claimReadStripText({ skipped: "no View Details link in the Pending Transactions box" }));
      return;
    }
    claimStrip(PR.claimReadStripText());
    const to = new URL(href, location.href);
    to.hash = PR.CLAIM_READ_FRAGMENT;
    goOn(to.href);
  }

  /** On the claim's page opened with the read's fragment: the page read (names and words only)
   * and filed, once; nothing clicked. */
  async function claimRead(trigger) {
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    const due = await claimReadDue();
    if (!due) return;
    const read = PR.claimPageRead(claimControls(), { trigger, readAt: Date.now(), extension: extensionVersion() });
    const r = await send({ op: "claim_page_read", league, read });
    if (!r || !r.ok) claimStrip(PR.claimReadStripText({ error: (r && r.error) || "no answer from the extension" }));
    else claimStrip(PR.claimReadStripText({ logged: true, forms: read.forms.length, controls: read.controls.length + read.forms.reduce((n, f) => n + f.controls.length, 0) }));
  }

  // ---------------------------------------------------------------- a claim's cancel (#345 PR 2)
  const cancelStrip = (line) => strip(line, "cancel");
  const cancelPage = PR.cancelPageOf(location.href);

  /** The text of ``el`` with a space between its text nodes: Yahoo's heading runs a player's name
   * and "Player Note" together otherwise. */
  function spacedText(el) {
    if (!el) return "";
    const parts = [];
    const walk = (n) => {
      if (typeof n === "string") parts.push(n);
      else if (n.nodeType === 3) parts.push(n.nodeValue);
      else for (const c of n.childNodes || n.nodes || []) walk(c);
    };
    walk(el);
    return parts.map((x) => String(x).trim()).filter(Boolean).join(" ").replace(/\s+/g, " ");
  }

  const chromeOf = (el) => typeof el.closest === "function" && Boolean(el.closest("header, nav, [role=navigation], #ybar"));
  const headingOf = () => [...document.querySelectorAll("h1, h2, h3")].filter((h) => !chromeOf(h)).map(spacedText).find((x) => x && !/^yahoo/i.test(x)) || null;
  const noticesOf = (sel) => [...document.querySelectorAll(sel)].filter((x) => !chromeOf(x)).map(textOf).filter((x) => x && x.length < 300 && !/^\d+$/.test(x));

  /** The claim's page as a plain object for ``PR.readCancelPage``: the URL, and each claim form's
   * id, action, the player links' ids in it and its submits by name, type and label. Never a
   * field's value. */
  function cancelControls() {
    return {
      url: location.href,
      forms: [...document.querySelectorAll("form")].filter((f) => !chromeOf(f)).map((f) => ({
        id: f.getAttribute("id"),
        action: f.getAttribute("action"),
        players: [...f.querySelectorAll('a[id*="playernote-"]')].map((a) => a.getAttribute("id")).filter((id) => id.startsWith("playernote-")).map((id) => id.slice("playernote-".length)),
        buttons: [...f.querySelectorAll("input[type=submit], button")].map((b) => ({
          name: b.getAttribute("name"),
          type: b.tagName === "INPUT" ? String(b.getAttribute("type") || "").toLowerCase() : String(b.getAttribute("type") || "submit").toLowerCase(),
          label: b.tagName === "INPUT" ? b.getAttribute("value") : textOf(b),
        })),
      })),
    };
  }

  /** The page the tab is on after a press, for the run: its path, heading, notices and errors,
   * and whether a claim form is there. */
  function cancelLandedRead() {
    const errors = noticesOf(".error, .Error, .F-negative");
    return {
      path: location.pathname,
      form: Boolean(document.querySelector(PR.CANCEL_FORM)),
      heading: headingOf(),
      notes: noticesOf(".Alert, .alert, [role=alert], .F-positive, .success, .Success, .notice, .Notice").filter((x) => !errors.includes(x)),
      errors,
    };
  }

  /** The league's cancels due, fresh: null (the strip says why) under the browser's brake, with no
   * answer, or with the executor off here. */
  async function cancelDue() {
    const settings = await send({ op: "settings" });
    if (settings && settings.ok && settings.data.moves_executor === "off") {
      cancelStrip(PR.cancelStripText({ browserOff: true }));
      return null;
    }
    const r = await send({ op: "cancel_due", league });
    if (!r || !r.ok) {
      cancelStrip(PR.cancelStripText({ error: (r && r.error) || "no answer from the extension" }));
      return null;
    }
    if (r.data.mode === "off" || /private/i.test(String(r.data.reason || ""))) {
      cancelStrip(PR.cancelStripText({ none: r.data.reason || "the moves executor is off in this league" }));
      return null;
    }
    return r.data;
  }

  /** The cancels on record in this browser for ``items``, by entry; a press whose run never
   * reached the log is logged first, unconfirmed, and never pressed again. */
  async function cancelRecords(items, extension) {
    const read = async (entry) => {
      const r = await send({ op: "cancel_record", league, entry });
      return (r && r.ok && r.data) || null;
    };
    const out = {};
    for (const x of items) {
      let record = await read(x.entry);
      if (record && record.mode === "live" && !record.logged && Date.now() - record.at >= PR.CANCEL_LANDING_MS) {
        await send({ op: "cancel_log", league, run: PR.unreadCancel(record, extension) });
        record = await read(x.entry);
      }
      out[x.entry] = record;
    }
    return out;
  }

  async function cancelLog(run) {
    const logged = await send({ op: "cancel_log", league, run });
    if (!logged || !logged.ok) {
      cancelStrip(`not logged: ${(logged && logged.error) || "no answer from the extension"}`);
      return null;
    }
    cancelStrip(PR.cancelStripText({ run }));
    return run;
  }

  /** On my team page opened with the cancel's fragment: the league's next cancel due, and that
   * claim's own View Details link followed with the fragment; under STOP the run says it stopped,
   * and a claim not in the box is logged skipped. Nothing is clicked here. */
  async function cancelFrom(trigger) {
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    if (running) return null;
    running = true;
    try {
      const due = await cancelDue();
      if (!due) return null;
      const extension = extensionVersion();
      const mode = PR.passMode(due);
      if (due.stop) return cancelLog(PR.cancelRun({ day: due.date, mode: mode.mode, trigger, outcome: "stopped", reason: due.reason, page: location.pathname, extension }));
      const records = await cancelRecords(due.cancels || [], extension);
      const item = PR.cancelItemFor(due, (x) => PR.cancelRanToday(records[x.entry], due.date, mode.mode));
      if (!item) {
        cancelStrip(PR.cancelStripText({ none: due.reason || "every claim due ran today" }));
        return null;
      }
      const claim = PR.claimIdOf(due.team, item);
      const href = PR.cancelLink(pendingLines(), due.team, item);
      if (!href) {
        return cancelLog(PR.cancelRun({ day: due.date, mode: mode.mode, trigger, outcome: "skipped", reason: "the claim is not among Yahoo's pending transactions on my team page", item, claim, page: location.pathname, extension }));
      }
      cancelStrip(PR.cancelStripText());
      const to = new URL(href, location.href);
      to.hash = PR.CANCEL_FRAGMENT;
      goOn(to.href);
      return null;
    } finally {
      running = false;
    }
  }

  /** On the claim's page opened with the cancel's fragment: the due read fresh and this page's
   * claim taken from it; the page checked; a dry run (or a live league whose guard refuses) logs
   * ``would_cancel`` and clicks nothing; a live league puts the press on record and presses
   * "Cancel Waiver" once (``PR.pressCancel``), and the page Yahoo lands on goes on to my team
   * page, whose box the run is logged from. */
  async function cancelOnPage(trigger) {
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    if (running) return null;
    running = true;
    try {
      const due = await cancelDue();
      if (!due) return null;
      const extension = extensionVersion();
      const mode = PR.passMode(due);
      const where = location.pathname;
      if (due.stop) return cancelLog(PR.cancelRun({ day: due.date, mode: mode.mode, trigger, outcome: "stopped", reason: due.reason, page: where, extension }));
      const item = (due.cancels || []).find((c) => PR.claimIdOf(due.team, c) === cancelPage.claim) || null;
      if (!item) {
        cancelStrip(PR.cancelStripText({ none: `claim ${cancelPage.claim || "none"} is not due a cancel` }));
        return null;
      }
      const records = await cancelRecords([item], extension);
      if (PR.cancelRanToday(records[item.entry], due.date, mode.mode)) {
        cancelStrip(PR.cancelStripText({ none: "this claim's cancel ran today" }));
        return null;
      }
      const claim = PR.claimIdOf(due.team, item);
      const controls = PR.readCancelPage(cancelControls());
      const base = { day: due.date, trigger, item, claim, page: where, controls, extension };
      const problem = PR.cancelProblem(controls, { league, team: due.team, item });
      if (problem) return cancelLog(PR.cancelRun({ ...base, mode: mode.mode, outcome: "skipped", reason: problem }));
      if (mode.mode !== "live") return cancelLog(PR.cancelRun({ ...base, mode: "dry_run", outcome: "would_cancel", reason: mode.refused }));
      let refused = null;
      const team = `/nba/${league}/${due.team}`;
      const onPress = async () => {
        const put = await send({ op: "cancel_pressing", league, record: { day: due.date, item, claim, trigger, page: where, controls, team } });
        refused = put && put.ok ? null : (put && put.error) || "no answer from the extension";
        return !refused;
      };
      const got = await PR.pressCancel(document, item, { onPress });
      if (got.pressed) {
        cancelStrip(PR.cancelStripText({ pressing: claim }));
        // Yahoo's post leaves the page; one that stays goes to my team page to read the box.
        setTimeout(() => {
          if (!leaving) goOn(`${location.origin}${team}`);
        }, PR.CANCEL_STAY_MS);
        return null;
      }
      const reason = refused ? `${got.reason}: ${refused}` : got.reason;
      return cancelLog(PR.cancelRun({ ...base, controls: { ...controls, confirm: got.confirm }, mode: "live", outcome: got.outcome, reason }));
    } finally {
      running = false;
    }
  }

  /** On any page of the league: a cancel this tab pressed whose run is not logged yet (the worker
   * keeps it) is read here. Yahoo's claim form drawn again is ``not_cancelled`` (nothing more is
   * clicked); otherwise my team page's box decides, and from any other page the tab goes there
   * first. Answers whether the tab is leaving for my team page: once logged, the page goes on
   * with whatever it was opened for (the pass's next cancel may open on my team page). */
  async function cancelLanded() {
    const r = await send({ op: "cancel_landed", league });
    if (!r || !r.ok || !r.data) return false;
    const record = r.data;
    const raw = cancelLandedRead();
    const extension = extensionVersion();
    const onTeam = location.pathname.replace(/\/+$/, "") === record.team;
    let answer = record.settle ? null : PR.readCancelLanded(raw);
    let landed = record.settle ? { ...record.settle.seen, team: raw } : raw;
    if (!answer) {
      if (!onTeam) {
        const kept = await send({ op: "cancel_settling", league, entry: record.item.entry, settle: { seen: raw } });
        if (kept && kept.ok) {
          cancelStrip("live · pressed: reading my team page's pending transactions…");
          goOn(`${location.origin}${record.team}`);
          return true;
        }
        answer = { outcome: "unconfirmed", reason: "pressed; my team page could not be read for the box" };
      } else {
        const roster = Boolean(document.querySelector("[data-ys-playerid]"));
        answer = PR.settleCancel(pendingLines(), record.claim, roster) || { outcome: "unconfirmed", reason: "pressed; my team page showed neither the box nor my roster" };
        if (!record.settle) landed = { team: raw };
      }
    }
    const message = [raw.heading, ...(raw.errors || []), ...(raw.notes || [])].filter(Boolean).join(" · ").slice(0, 300) || null;
    await cancelLog(
      PR.cancelRun({
        day: record.day,
        mode: "live",
        trigger: record.trigger,
        outcome: answer.outcome,
        reason: answer.reason,
        item: record.item,
        claim: record.claim,
        page: record.page,
        controls: record.controls,
        landed,
        message: answer.message || message,
        extension,
      })
    );
    return false;
  }

  // A live pass submits only on a page opened with a moves fragment; any other page of the league
  // reads a claim this tab submitted, first.
  const trigger = addPage ? PR.movesTriggerOf(location.hash) : null;
  const lineupTrigger = page ? PR.triggerOf(location.hash) : null;
  const saTrigger = page && page.kind === "team" ? PR.startActiveTriggerOf(location.hash) : null;
  const ilTrigger = page && page.kind === "team" ? PR.ilTriggerOf(location.hash) : null;
  const dropTrigger = dropPage ? PR.dropTriggerOf(location.hash) : null;
  const claimFrom = page && page.kind === "team" ? PR.claimReadTriggerOf(location.hash) : null;
  const claimTrigger = claimPage ? PR.claimReadTriggerOf(location.hash) : null;
  const cancelFromTrigger = page && page.kind === "team" ? PR.cancelTriggerOf(location.hash) : null;
  const cancelTrigger = cancelPage ? PR.cancelTriggerOf(location.hash) : null;
  setTimeout(async () => {
    await landed();
    // A landing settled on my team page (#341): the tab is on its way there.
    if (leaving) return;
    if (await dropLanded()) return;
    if (await cancelLanded()) return;
    if (cancelTrigger) await cancelOnPage(cancelTrigger);
    else if (cancelFromTrigger) await cancelFrom(cancelFromTrigger);
    else if (claimTrigger) await claimRead(claimTrigger);
    else if (claimFrom) await claimReadFrom();
    else if (dropTrigger) await heldDrop(dropTrigger);
    else if (trigger) await claim(trigger);
    else if (saTrigger) {
      const lineupAfter = PR.comebackLineupFragment(location.hash);
      await startActive(saTrigger);
      // The chain's last step (#318): the pass's lineup run on this page, read again.
      const to = lineupAfter ? await lineupPage(page.league, lineupAfter) : null;
      if (to) goOn(to);
    }
    else if (ilTrigger) await ilMove(ilTrigger);
    else if (page) await visit(lineupTrigger);
  }, SETTLE_MS);
})();
