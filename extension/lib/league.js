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
  /** A multi-page read stops after this many pages of a view (300 players, as the API's own refresh). */
  const READ_PAGES = 12;
  /** The players page's Next 7 Days (proj) view: Yahoo's own weekly projections (#93). */
  const PROJECTION_VIEW = "S_PS7";

  /** The league page ``url`` is, as the API's ``pages.page_kind`` reads it: ``{league, kind}``
   * with ``team`` for a team page (and ``date``, YYYY-MM-DD, for the team page shown for a day,
   * ``?date=``: that day's lineup, #107), ``offset`` (and ``view``, its ``stat1``, when the URL
   * names one) for the players page; the league page, a matchup, the transactions, the draft
   * results and the settings page by kind alone; null for any other page (the draft client, a
   * player's page, another sport) and for a team page whose date is not a day. */
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
      const team = { league, kind: "team", team: Number(rest[0]) };
      if (!u.searchParams.has("date")) return team;
      const date = u.searchParams.get("date");
      return isDay(date) ? { ...team, date } : null;
    }
    if (rest.length === 1 && rest[0] === "players") {
      const view = u.searchParams.get("stat1");
      return { league, kind: "players", offset: Number(u.searchParams.get("count")) || 0, ...(view ? { view } : {}) };
    }
    if (rest.length === 1 && rest[0] === "matchup") return { league, kind: "matchup" };
    if (rest.length === 1 && rest[0] === "transactions") return { league, kind: "transactions" };
    // The draft's picks, for the weekly recorder (#97): read once per league.
    if (rest.length === 1 && rest[0] === "draftresults") return { league, kind: "draftresults" };
    // The held slots and the lineup rule (#107, #124): read once per league.
    if (rest.length === 1 && rest[0] === "settings") return { league, kind: "settings" };
    return null;
  }

  /** ``s`` is a calendar day written YYYY-MM-DD. */
  function isDay(s) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
    const d = new Date(`${s}T00:00:00Z`);
    return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
  }

  /** Where the page's posts are kept in the panel: one line per team, matchup and players
   * page, so a page read again replaces its own line. A team's page for a day keeps a line per
   * day, and the projection view's pages keep lines of their own: they feed Yahoo's projections
   * as well as the available players. */
  function postKey(page) {
    if (page.kind === "team") return page.date ? `team ${page.team} on ${page.date}` : `team ${page.team}`;
    if (page.kind === "players") {
      const rows = `players ${page.offset + 1}-${page.offset + PAGE_ROWS}`;
      return page.view === PROJECTION_VIEW ? `${rows} (next 7 days)` : rows;
    }
    return page.kind;
  }

  /** The body of POST /seasons/{league}/snapshot for one page. */
  function snapshotBody(url, html, fetchedAt) {
    return { pages: [{ url, html, fetched_at: new Date(fetchedAt).toISOString() }] };
  }

  /** A multi-page read of the players page, armed from the side panel: at most ``pages`` more
   * pages of ``league`` in the view it starts in (``view``, the page's ``stat1``), then as many
   * in the projection view (``then``) unless it starts there. */
  function startRead(league, pages = READ_PAGES, now = Date.now(), view = null) {
    const then = view === PROJECTION_VIEW ? [] : [PROJECTION_VIEW];
    return { league: String(league), pages, pages_left: pages, started_at: now, then };
  }

  /** ``url``, a players page, in another stat view, from its first page; filters and sort kept. */
  function viewUrl(url, view) {
    const u = new URL(url);
    u.searchParams.set("stat1", view);
    u.searchParams.delete("count");
    return u.href;
  }

  /** What the reader does after posting ``page`` (at ``url``): ``{follow, read}``. It follows
   * Yahoo's Next 25 link (``next``, read from the page) only on a players page of the armed
   * league whose post the API accepted, while pages are left; when the view runs out, it opens
   * the first page of the next view the read has ``then``. ``read`` is the read that remains,
   * null once it is done. Without an armed read it never navigates. */
  function afterPost(read, page, posted, next, url = null) {
    if (!read) return { follow: null, read: null };
    if (!page || page.league !== read.league || page.kind !== "players") return { follow: null, read };
    if (!posted) return { follow: null, read: null };
    if (next && read.pages_left > 1 && leaguePage(next)?.kind === "players") {
      return { follow: next, read: { ...read, pages_left: read.pages_left - 1 } };
    }
    const [view, ...then] = (read.then || []).filter((v) => v !== page.view);
    if (!view || !url) return { follow: null, read: null };
    return { follow: viewUrl(url, view), read: { ...read, pages_left: read.pages, then } };
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

  return {
    LEAGUE_HOST: HOST,
    LEAGUE_PAGE_ROWS: PAGE_ROWS,
    READ_PAGES,
    PROJECTION_VIEW,
    leaguePage,
    postKey,
    snapshotBody,
    startRead,
    viewUrl,
    afterPost,
    ago,
    postLine,
  };
});
