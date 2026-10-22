// pickandroll, league page reader (#98, isolated world). On a Yahoo league's own pages (the
// league page, a team page or a team's page for a day, the players page, a matchup, the
// transactions, the draft results, the settings page) it posts the page as
// the user's Chrome rendered it to the season's snapshot route, through the service worker; the
// API parses it (sources/yahoo/pages.py). This is how the private league, whose pages answer only
// when signed in, reaches the season view; a public league's pages post the same way.
//
// It never clicks anything and never runs on the draft client. It navigates only to follow the
// players page's Next 25 link during a multi-page read the user armed from the side panel.
(() => {
  "use strict";
  const PR = globalThis.PickAndRoll;
  const KEY = "__pickandrollLeague";
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

  /** The page without its scripts, styles, frames and form fields: all the parsers read, and none
   * of the page's own code or tokens (Yahoo's forms carry a hidden crumb). */
  function pageHtml() {
    const root = document.documentElement.cloneNode(true);
    const drop = "script, style, noscript, iframe, svg, link, template, input, textarea";
    for (const el of root.querySelectorAll(drop)) el.remove();
    return "<!doctype html>" + root.outerHTML;
  }

  /** The players page's Next 25 link, if it has one. */
  function nextLink() {
    const a = [...document.querySelectorAll("a[href]")].find((x) => /^next\s+25$/i.test(x.textContent.trim()));
    return a ? a.href : null;
  }

  async function post() {
    let r;
    try {
      r = await chrome.runtime.sendMessage({
        op: "season_page",
        url: location.href,
        html: pageHtml(),
        fetched_at: Date.now(),
        next: page.kind === "players" ? nextLink() : null,
      });
    } catch (_) {
      return; // the extension was reloaded: the next page load posts again
    }
    if (r && r.ok && r.data && r.data.follow) location.assign(r.data.follow);
  }

  setTimeout(post, SETTLE_MS);
})();
