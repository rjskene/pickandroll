// Reading a Yahoo league's own pages for the season view (#98): which pages the reader posts,
// the snapshot body the API's /seasons/{league}/snapshot takes, and the multi-page read of the
// players page the user arms from the side panel. Pure, so node's tests cover it; the content
// script (league.js) and the service worker share it. The API parses the pages
// (sources/yahoo/pages.py): nothing here reads a row.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const HOST = "basketball.fantasysports.yahoo.com";
  /** Rows on one players page; Yahoo's Next 25 link moves ``count`` by this. */
  const PAGE_ROWS = 25;
  /** A multi-page read stops after this many pages (300 players, as the API's own refresh). */
  const READ_PAGES = 12;

  /** The league page ``url`` is, as the API's ``pages.page_kind`` reads it: ``{league, kind}``
   * with ``team`` for a team page and ``offset`` for the players page; null for any other page
   * (the draft client, a player's page, another sport) and for a team page on another date
   * (``?date=``), whose lineup is not today's roster. */
  function leaguePage(url) {
    let u;
    try {
      u = new URL(url);
    } catch (_) {
      return null;
    }
    if (u.protocol !== "https:" || u.hostname !== HOST) return null;
    const parts = u.pathname.split("/").filter(Boolean);
    if (parts[0] !== "nba" || !/^\d+$/.test(parts[1] || "")) return null;
    const league = parts[1];
    const rest = parts.slice(2);
    if (!rest.length) return { league, kind: "league" };
    if (rest.length === 1 && /^\d+$/.test(rest[0])) {
      return u.searchParams.has("date") ? null : { league, kind: "team", team: Number(rest[0]) };
    }
    if (rest.length === 1 && rest[0] === "players") {
      return { league, kind: "players", offset: Number(u.searchParams.get("count")) || 0 };
    }
    if (rest.length === 1 && rest[0] === "matchup") return { league, kind: "matchup" };
    if (rest.length === 1 && rest[0] === "transactions") return { league, kind: "transactions" };
    return null;
  }

  /** Where the page's posts are kept in the panel: one line per team, matchup and players
   * page, so a page read again replaces its own line. */
  function postKey(page) {
    if (page.kind === "team") return `team ${page.team}`;
    if (page.kind === "players") return `players ${page.offset + 1}-${page.offset + PAGE_ROWS}`;
    return page.kind;
  }

  /** The body of POST /seasons/{league}/snapshot for one page. */
  function snapshotBody(url, html, fetchedAt) {
    return { pages: [{ url, html, fetched_at: new Date(fetchedAt).toISOString() }] };
  }

  /** A multi-page read of the players page, armed from the side panel: at most ``pages`` more
   * pages of ``league``. */
  function startRead(league, pages = READ_PAGES, now = Date.now()) {
    return { league: String(league), pages_left: pages, started_at: now };
  }

  /** What the reader does after posting ``page``: ``{follow, read}``. It follows Yahoo's Next 25
   * link (``next``, read from the page) only on a players page of the armed league whose post
   * the API accepted, while pages are left; ``read`` is the read that remains, null once it is
   * done. Without an armed read it never navigates. */
  function afterPost(read, page, posted, next) {
    if (!read) return { follow: null, read: null };
    if (!page || page.league !== read.league || page.kind !== "players") return { follow: null, read };
    if (!posted || !next || read.pages_left <= 1 || leaguePage(next)?.kind !== "players") {
      return { follow: null, read: null };
    }
    return { follow: next, read: { ...read, pages_left: read.pages_left - 1 } };
  }

  /** "2 min ago" for a post's age. */
  function ago(at, now = Date.now()) {
    const s = Math.max(0, Math.round((now - at) / 1000));
    if (s < 60) return `${s} s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} min ago`;
    const h = Math.floor(m / 60);
    return h < 48 ? `${h} h ago` : `${Math.floor(h / 24)} days ago`;
  }

  /** One post as the panel lists it. */
  function postLine(post, now = Date.now()) {
    const when = ago(post.at, now);
    if (post.error) return `${post.key}: ${post.error} (${when})`;
    const skipped = (post.skipped || []).map((s) => s.reason).filter(Boolean);
    if (skipped.length) return `${post.key}: not read: ${skipped.join("; ")} (${when})`;
    return `${post.key}: posted ${when}${post.accepted && post.accepted.length ? ` as ${post.accepted.join(", ")}` : ""}`;
  }

  return { LEAGUE_HOST: HOST, LEAGUE_PAGE_ROWS: PAGE_ROWS, READ_PAGES, leaguePage, postKey, snapshotBody, startRead, afterPost, ago, postLine };
});
