// One armed turn: take pickandroll's pick in Yahoo's draft client. A port of the hook used in the
// September mock drafts (v16), with the deadlines of the #9 review:
//   1. hold GET /plan?wait&board for the solve of this turn's board (picks 1..k-1), but stop
//      waiting by 12 s left on the clock; a plan for an older board is asked for again, and so
//      is a failed ask (the API restarting, a 5xx); when the wait is up the turn acts on the
//      newest plan it holds, the one the page fetched ahead included (fresh only on board k-1);
//   2. click the first available candidate's Draft button; Yahoo drops a click that lands during
//      a re-render and confirms a registered one within ~400 ms, so re-click the same row at
//      1.8 s and again at 2.5 s; scroll when the row is not in view (Yahoo's search box only
//      with the option on: in September the filtered table's Draft button drafted the wrong
//      player, §0);
//   3. fall through to the next candidate; after the top four, look for rows without scrolling
//      over all of the plan's candidates in priced order, pass after pass, to the backstop line
//      (mock 7, pick 68: the top four had no row while Yahoo's table was not its Players list);
//      the turn starts from the top of that list (the search box cleared, the list at its top),
//      and while the table shows no Draft button or no candidate's row, Yahoo's Players tab is
//      selected again and the view reset, every 2 s; each candidate that misses is noted with
//      what the page showed;
//   4. by 6 s left, put the best remaining candidate alone in Yahoo's queue with Autodraft on,
//      for this pick only (the first candidate with a row, and while none has one the turn
//      keeps looking until 2 s before the clock runs out); after the turn Autodraft goes off,
//      the queue is emptied and the view reset (after a hand pick, once it is in). One
//      exception (user, 2026-10-02): when my next pick follows this one (slots 1 and 12), the
//      plan's player for it goes in behind, so Yahoo's instant autopick at that turn's start
//      takes ours rather than its own ranking's. After the user's request for this pick failed
//      (its clicks were lost), the requested player goes first and the best candidate second
//      (#26): Yahoo takes the head for this pick, and back to back the next one for mine.
// Turns are independent. Each starts from its own turn frame, and starting turn k stops
// whatever turn k-1 still has pending (a re-click wait, a /plan hold, a sleep) without waiting
// for it: the newer turn owns the page and first undoes what the older one left switched on
// (Autodraft off, then the queue). Page actions run one at a time, so a stopped turn's click
// that is still settling never interleaves with the next turn's.
// A trusted click by the user on any Draft control during the turn makes the pick theirs: the
// drafter stops at once and touches nothing more.
// "Draft in Yahoo" from the web app (#10, in mirror and autopilot): ``request`` clicks the user's
// player for the pick on the clock, with the row click's label guard, in two tries; the pick is
// the user's (how "manual"). While it is pending an armed turn for that pick stands aside; when
// it lands, that turn ends, as after a hand pick; when it lands nothing, a note "request failed"
// drops it and the turn goes on, backstop included (a second try that would cut into the
// backstop's time is skipped).
// ``actAt`` (the room's act_at_s, #10; null: at once): an armed turn holds its click until the
// clock is down to that many seconds, so the user may pick first (by hand or by a request,
// either of which ends the turn). Its plan wait stops there instead of at 12 s, and it takes its
// last look at the plan at act time, not at the turn's start.
// The queue probe (once per draft, ``probeRound``): on my first turn from that round on whose
// next pick is not also mine, star the top candidate before drafting it, and log what Yahoo
// did with it (queued, or drafted: the pick wanted either way). Nothing landing is "dropped"
// on a Draft-labelled control (a lost click) and "failed" on any other (the star path).
//
// The page is reached only through ``dom`` (see content.js for Yahoo's), so node's tests run
// the whole turn against a scripted page and a virtual clock.
(function (root, factory) {
  const node = typeof module === "object" && module.exports;
  const api = factory(node ? require("./yahoo.js") : root.PickAndRoll);
  if (node) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function (Y) {
  "use strict";

  const PLAN_WAIT_MAX_S = 20;
  const START_BY_S = 12; // stop waiting for a fresh plan with this much clock left
  const BACKSTOP_BY_S = 6; // the queue backstop is set with this much clock left
  const RECLICK_MS = [1800, 2500, 2500];
  const MAX_CANDIDATES = 4;
  const ASK_AGAIN_MS = 250; // between asks when the API answered for an older board
  const RETRY_MS = 500; // between asks when /plan failed (the API restarting, a 5xx)
  const REQUEST_TRIES = 2; // clicks for a "Draft in Yahoo" request before it is dropped
  const REQUEST_WAIT_MS = 2500; // after each, for the pick to land (Yahoo confirms in ~400 ms)
  const LAST_LOOK_S = 2; // the backstop looks for a row until this much clock is left
  const RECOVER_MS = 2000; // between view resets while the table shows no row to take
  const SETTLE_MS = 1000; // Draft buttons missing for this long at act time: reset the view
  const PASS_MS = 250; // between find-only passes
  const ENDS = new Set(["landed", "manual", "stopped"]);
  const NO_ROW = new Set(["no row", "row vanished"]); // queueOnly found no row to star
  const MISSES = new Set(["noRow", "noButton", "mismatch", "notLanded"]);

  /** Seconds to hold /plan for a fresh solve with ``left`` seconds on the clock, stopping
   * with ``by`` seconds left. */
  function planWait(left, by = START_BY_S) {
    if (left === null || left === undefined || Number.isNaN(left)) return PLAN_WAIT_MAX_S;
    return Math.max(0, Math.min(PLAN_WAIT_MAX_S, Math.floor(left - by)));
  }

  const STOP = Symbol("stop");

  /** One turn: what it has done, and a switch that ends its next wait at once and cancels its
   * /plan hold in the service worker. */
  function turnContext(k) {
    let fire;
    const halted = new Promise((resolve) => {
      fire = resolve;
    });
    const ctl = typeof AbortController === "function" ? new AbortController() : null;
    return {
      k,
      stopped: null, // "superseded" by a newer turn, "manual" (the user took the pick) or "request"
      halted,
      signal: ctl ? ctl.signal : null,
      settled: false,
      attempts: 0,
      planErrors: 0, // failed /plan asks
      planError: null, // the last one's status and message
      board: null, // the board of the plan this turn acts on
      stop(why) {
        if (this.stopped) return;
        this.stopped = why;
        if (ctl) ctl.abort();
        fire(STOP);
      },
    };
  }

  class Drafter {
    /**
     * @param {object} o
     * @param {object} o.tracker RoomTracker of this room
     * @param {object} o.dom     the draft client: draftable(), find(c), scrollTo(c, until),
     *                           search(c), async click(row, c) -> "clicked" | "mismatch" |
     *                           "none", nudge(), queueOnly(c, until) -> {ok, msg},
     *                           queueAlso(c2, c, until) -> {ok, msg, single} (c2 behind c; on
     *                           failure ``single`` is queueOnly(c) redone), probeQueue(c) ->
     *                           {outcome, panel, control}, setAutodraft(on), autodraftOn(),
     *                           clearQueue(), reset() (the search box cleared, the list at its
     *                           top), showPlayers() -> "selected" | "clicked" | "none" (Yahoo's
     *                           Players tab), summary() -> what the page shows (read only);
     *                           ``until``: epoch ms a scroll for a row gives up at
     * @param {function} o.plan  async (wait_s, board, signal) -> GET /rooms/{d}/plan, held
     *                           until the solve of ``board`` (the number of picks it was built
     *                           on); ``signal`` aborts when the turn is stopped
     * @param {function} o.held  (k) -> the newest plan the page holds for my pick k (fetched
     *                           ahead of the turn), or null
     * @param {function} o.emit  client event sink
     * @param {function} o.sleep async (ms)
     * @param {function} o.now   epoch ms
     */
    constructor({ tracker, dom, plan, held, emit, sleep, now, log }) {
      Object.assign(this, { tracker, dom, plan, emit, sleep, now });
      this.held = held || (() => null);
      this.log = log || (() => {});
      this.current = null; // the newest turn
      this.tried = new Set(); // overalls a turn was started for
      this.last = null; // the last settled turn's summary
      // What the drafter switched on in the page and has not undone, whichever turn did it.
      this.touched = { autodraft: false, queue: false };
      this.pageTail = Promise.resolve();
      this.probeRound = null; // the queue probe's round (the options page), null: off
      this.probed = null; // the pick the probe ran on
      this.searchFallback = false; // Yahoo's search box for an off-screen row (the options page)
      this.requesting = null; // the user's pending request: {k, yid, ctx, settled}
      this.failed = null; // the user's last request that landed nothing: {k, c, id}, for the backstop
      this.requests = new Set(); // requests served, each by the API's id for it
      this.offered = null; // the room's pending request as the tab last read it
      this.onRequest = () => {}; // ({start: q}) when a request is served, ({out}) when it ends
      this.actAt = null; // the room's act_at_s: seconds left when an armed turn acts, null: at once
    }

    /** A turn has not settled yet. */
    get busy() {
      return Boolean(this.current && !this.current.settled);
    }

    left() {
      return this.tracker.clockLeft(this.now());
    }

    /** Seconds left, or Infinity before the room's first clock frame: the row loop then runs as
     * if time were plenty, as planWait and the re-click budgets already do. */
    leftOrPlenty() {
      const left = this.left();
      return left === null || left === undefined || Number.isNaN(left) ? Infinity : left;
    }

    /** The turn is short of the line ``s`` seconds before its clock runs out. With no clock from
     * the room, it is for at most 30 - ``s`` seconds from the turn's first look at the table
     * (Yahoo's 30 s clock), so that a look that finds nothing ends. */
    before(ctx, s) {
      const left = this.left();
      if (left !== null && left !== undefined && !Number.isNaN(left)) return left > s;
      if (ctx.blind === undefined) ctx.blind = this.now();
      return this.now() - ctx.blind < (30 - s) * 1000;
    }

    /** Epoch ms at which the clock shows ``s`` seconds left; Infinity before the room's first
     * clock frame. */
    clockAt(s) {
      const left = this.left();
      if (left === null || left === undefined || Number.isNaN(left)) return Infinity;
      return this.now() + (left - s) * 1000;
    }

    /** What the page shows, for a note: read only, and never throws. */
    summary() {
      try {
        return this.dom.summary ? this.dom.summary() : null;
      } catch (e) {
        return { error: String((e && e.message) || e) };
      }
    }

    /** The pick landed, or the user took it over. */
    done(k) {
      return this.tracker.picks.has(k) || this.tracker.isManual(k);
    }

    /** The turn may still act on the page. */
    live(ctx) {
      return !ctx.stopped && !this.done(ctx.k);
    }

    /** ``p``, or STOP the moment the turn is stopped: a stopped turn waits for nothing. */
    wait(ctx, p) {
      const q = Promise.resolve(p);
      q.catch(() => {}); // a result nobody waits for any more must not throw unhandled
      return Promise.race([q, ctx.halted]);
    }

    /** Sleep ``ms``; false when the turn was stopped meanwhile. */
    async pause(ctx, ms) {
      return (await this.wait(ctx, this.sleep(ms))) !== STOP;
    }

    /** One page action at a time across turns: a stopped turn's click may still be settling. */
    page(fn) {
      const run = this.pageTail.then(() => fn());
      this.pageTail = run.catch(() => {});
      return run;
    }

    async waitDone(ctx, ms) {
      const end = this.now() + ms;
      while (this.now() < end && !this.done(ctx.k)) {
        if (!(await this.pause(ctx, Math.min(200, Math.max(1, end - this.now()))))) break;
      }
      return this.done(ctx.k);
    }

    /** GET /plan for this turn: the plan, STOP, or null when the ask failed (the API
     * restarting, a 5xx, the worker gone): the turn asks again rather than ending. */
    async ask(ctx, wait, board) {
      try {
        return await this.wait(ctx, this.plan(wait, board, ctx.signal));
      } catch (e) {
        ctx.planErrors++;
        ctx.planError = [e && e.status, String((e && e.message) || e)].filter(Boolean).join(" ");
        return null;
      }
    }

    /** The user took pick ``k`` by hand: its turn touches the page no more (G4). */
    handPick(k) {
      const ctx = this.current;
      if (ctx && ctx.k === k) ctx.stop("manual");
      if (this.requesting && this.requesting.k === k) this.requesting.ctx.stop("manual");
    }

    /** A request of the user's is pending for pick ``k``: an armed turn stands aside. */
    yields(k) {
      return Boolean(this.requesting && this.requesting.k === k);
    }

    /** Wait while the user's request for this turn's pick is pending. */
    async yieldTo(ctx) {
      const q = this.requesting;
      if (q && q.k === ctx.k) await this.wait(ctx, q.settled);
    }

    /** act_at_s: hold the turn until the clock is down to ``actAt`` seconds, standing aside for
     * a request meanwhile. True when it held at all. Without a clock frame there is nothing to
     * count down: the turn acts at once. */
    async holdTill(ctx) {
      let held = false;
      for (;;) {
        await this.yieldTo(ctx);
        const left = this.left();
        const at = this.actAt;
        if (!this.live(ctx) || at === null || left === null || left === undefined || Number.isNaN(left) || left <= at) break;
        held = true;
        if (!(await this.pause(ctx, Math.min(250, Math.max(1, Math.ceil((left - at) * 1000)))))) break;
      }
      return held;
    }

    /** Click ``row`` for ``c`` once the page is free, if the turn is live and its pick still mine
     * on the clock then. Page actions queue and a click settles in ~400 ms: a click queued behind
     * one that drafted must not land on the next pick's frame (back to back, slots 1 and 12). The
     * attempt is noted right before the click, since the pick can land while it settles, and
     * taken back when nothing was clicked. */
    clickFor(ctx, row, c, how) {
      const k = ctx.k;
      return this.page(async () => {
        if (!this.live(ctx) || this.tracker.myTurnNow() !== k) return "none";
        const before = this.tracker.attempts.get(k);
        this.tracker.noteAttempt(k, how);
        ctx.clickAt = this.now(); // the click's own time: it settles ~400 ms later (#26)
        const r = await this.dom.click(row, c);
        if (r !== "clicked") {
          if (before === undefined) this.tracker.attempts.delete(k);
          else this.tracker.noteAttempt(k, before);
        }
        return r;
      });
    }

    /** The user's "Draft in Yahoo" from the web app (#10): click ``q``'s player for pick
     * ``q.overall``, only while that pick is mine on the clock, with the row click's label
     * guard. Resolves to a summary ("landed", "failed", "manual", "other", "stopped"), or null
     * when the request is not this turn's or was served already; never throws. */
    async request(q) {
      const k = q ? Number(q.overall) : null;
      if (!q || !Number.isInteger(k) || this.done(k) || this.tracker.myTurnNow() !== k) return null;
      const c = { ...q, yahoo_player_id: String(q.yahoo_player_id) };
      // Every request the user sends is its own, by the API's id for it (its time from an API
      // before #22): a re-request of a player whose first one failed, or B again after C, is
      // served; the same one is not.
      const key = `${k}:${c.yahoo_player_id}:${q.id ?? q.t ?? ""}`;
      if (this.requests.has(key) || this.requesting) return null;
      this.requests.add(key);
      const ctx = turnContext(k);
      ctx.board = Number.isInteger(q.board) ? q.board : null;
      let settle;
      const settled = new Promise((resolve) => {
        settle = resolve;
      });
      this.requesting = { k, yid: c.yahoo_player_id, ctx, settled };
      const out = { overall: k, yid: c.yahoo_player_id, result: "failed", attempts: 0 };
      // The notes name the request by the API's id: its failure drops this request only, not a
      // newer one for the same player (#22).
      const note = (what, extra) =>
        this.emit({ type: "note", what, overall: k, yid: c.yahoo_player_id, request_id: q.id ?? null, ...extra });
      try {
        for (let n = 1; n <= REQUEST_TRIES && this.live(ctx) && this.tracker.myTurnNow() === k; n++) {
          // An armed turn stands aside for this request: a second try past its backstop line
          // would take the backstop's time (#24).
          const turn = this.current;
          if (n > 1 && turn && turn.k === k && !turn.settled && this.leftOrPlenty() <= BACKSTOP_BY_S) break;
          // At the turn's frame the table may not show its Draft buttons yet, as for a row draft,
          // but the wait leaves an armed turn its backstop line (#22) and ends when the pick is in.
          for (let i = 0; i < 8 && this.live(ctx) && !this.dom.draftable(); i++) {
            const room = (this.leftOrPlenty() - BACKSTOP_BY_S) * 1000;
            if (room <= 0 || !(await this.pause(ctx, Math.min(250, room)))) break;
          }
          if (!this.live(ctx)) break;
          let row = this.dom.find(c) || (await this.page(() => this.dom.scrollTo(c, this.clockAt(BACKSTOP_BY_S + 1))));
          if (!this.live(ctx)) break;
          if (row) {
            // The user's pick, made through the tab (how "manual").
            let r = await this.clickFor(ctx, row, c, "manual");
            if (r === "mismatch" && this.live(ctx)) {
              await this.page(() => this.dom.nudge());
              row = this.dom.find(c);
              r = row && this.live(ctx) ? await this.clickFor(ctx, row, c, "manual") : "none";
            }
            if (r === "clicked") {
              out.attempts++;
              this.attempt(ctx, c, "request", n, k, ctx.clickAt);
            }
          }
          // Room for the armed turn's backstop after a failure, never less than a confirmation.
          const budget = Math.max(800, Math.min(REQUEST_WAIT_MS, (this.leftOrPlenty() - BACKSTOP_BY_S) * 1000));
          if (await this.waitDone(ctx, budget)) break;
        }
        const p = this.tracker.picks.get(k);
        if (this.tracker.isManual(k)) out.result = "manual";
        else if (p) out.result = p.yid === c.yahoo_player_id ? "landed" : "other";
        else if (ctx.stopped) out.result = "stopped";
        if (out.result === "failed") {
          this.failed = { k, c, id: q.id ?? null };
          note("request failed", { attempts: out.attempts });
        }
        note("request", { result: out.result, attempts: out.attempts });
        // The pick is in: the armed turn that stood aside waits for nothing more (its /plan hold
        // included), as after a hand pick (#22).
        const turn = this.current;
        if (p && turn && turn.k === k) turn.stop("request");
        return out;
      } catch (e) {
        // A page action threw: dropped, and noted as every served request is (§4, #24).
        this.failed = { k, c, id: q.id ?? null };
        note("request failed", { msg: String((e && e.message) || e) });
        note("request", { result: out.result, attempts: out.attempts });
        return out;
      } finally {
        this.requesting = null;
        ctx.settled = true;
        settle();
      }
    }

    /** The room's pending request as the tab last read it from the room summary (null: none;
     * #10, #22). A request for another player of the pick being served stops that one before
     * its next try; a request not served yet is served now, and when one ends the newest offered
     * is served next. ``onRequest`` hears each start and end. */
    offer(q) {
      this.offered = q || null;
      const cur = this.requesting;
      if (cur && q && Number(q.overall) === cur.k && String(q.yahoo_player_id) !== cur.yid) cur.ctx.stop("replaced");
      this.serveOffered();
    }

    serveOffered() {
      const q = this.offered;
      if (!q || this.requesting || this.tracker.myTurnNow() !== Number(q.overall)) return;
      const asked = this.request(q);
      if (!this.requesting) return; // not this turn's, or served already
      this.onRequest({ start: q });
      asked.then((out) => {
        this.onRequest({ out });
        this.serveOffered(); // a request that replaced this one, at once
      });
    }

    /** A draft attempt for ``overall`` (this turn's pick, or my next one when it is queued
     * behind it), on the board of the plan acted on. */
    attempt(ctx, c, method, n, overall = ctx.k, t = this.now()) {
      if (overall === ctx.k) ctx.attempts++;
      this.emit({
        type: "draft_attempt",
        t,
        overall,
        yid: String(c.yahoo_player_id),
        name: c.name,
        method,
        attempt: n,
        board: ctx.board, // the board of the plan acted on
      });
    }

    /** Undo what the drafter switched on: Autodraft off first (with it on, Yahoo picks from the
     * queue) and only then the queue, never the queue while Autodraft is still on. After a hand
     * pick the page is the user's: only what the drafter switched on is undone, and once the
     * pick is in (``landed``), the view is put back to the top of the Players list as after any
     * turn (a search left in the box is the filtered table of §0). */
    async tidy(manual, landed = false) {
      if (this.touched.autodraft || (!manual && this.dom.autodraftOn() === true)) {
        const on = await this.page(() => this.dom.setAutodraft(false));
        if (on === true) return; // still on: leave the queue alone
        this.touched.autodraft = false;
      }
      if (this.touched.queue || !manual) {
        await this.page(() => this.dom.clearQueue());
        this.touched.queue = false;
      }
      // After a hand pick, only once it is in: a reset while the user's click settles would
      // re-render the table under it.
      if (!manual || landed) await this.page(() => this.dom.reset());
    }

    /** Act time: the view at the top of Yahoo's Players list, and while the table shows no Draft
     * button (past Yahoo's usual re-render), the Players tab and the reset every 2 s, up to the
     * backstop line. */
    async view(ctx) {
      await this.page(() => this.dom.reset());
      const from = this.now();
      while (this.live(ctx) && !this.dom.draftable() && this.before(ctx, BACKSTOP_BY_S)) {
        if (this.now() - from >= SETTLE_MS) await this.recover(ctx, "no Draft button");
        if (!(await this.pause(ctx, PASS_MS))) break;
      }
    }

    /** At most every 2 s a turn: Yahoo's Players tab when another view is selected, then the
     * reset; noted with what the page showed before. */
    async recover(ctx, why) {
      if (ctx.recoveredAt !== undefined && this.now() - ctx.recoveredAt < RECOVER_MS) return;
      ctx.recoveredAt = this.now();
      const dom = this.summary();
      const tab = await this.page(() => (this.dom.showPlayers ? this.dom.showPlayers() : "none"));
      await this.page(() => this.dom.reset());
      ctx.recovered = (ctx.recovered || 0) + 1;
      this.emit({ type: "note", what: "view reset", overall: ctx.k, why, tab, dom });
    }

    /** One candidate's row draft, noted when it misses: the outcome and what the page showed.
     * A row that was clicked, or refused by the label guard, is not tried again this turn. */
    async tryRow(ctx, c, scroll, skip) {
      const r = await this.rowDraft(ctx, c, scroll);
      this.log(`#${ctx.k} ${c.name}: ${r}`);
      if (MISSES.has(r)) {
        if (r !== "noRow" && !(r === "noButton" && !this.dom.draftable())) skip.add(String(c.yahoo_player_id));
        this.emit({
          type: "note",
          what: "row miss",
          overall: ctx.k,
          yid: String(c.yahoo_player_id),
          name: c.name,
          result: r,
          via: scroll ? "scroll" : "find",
          dom: this.summary(),
        });
      }
      return r;
    }

    /** From act time to the backstop line: the top four candidates, scrolled for; then passes
     * over all of the plan's candidates in priced order, each row only where the table already
     * shows it (no scrolling: the time is the backstop's), until one lands or the line comes. A
     * pass that finds no candidate's row resets the view (the Players tab included). */
    async rows(ctx, plan, cands) {
      const skip = new Set();
      const time = () => this.live(ctx) && this.before(ctx, BACKSTOP_BY_S);
      for (let i = 0; i < cands.length; i++) {
        await this.yieldTo(ctx);
        if (!time()) return;
        const c = cands[i];
        if (this.tracker.taken().has(String(c.yahoo_player_id))) continue;
        const r = await this.tryRow(ctx, c, true, skip);
        if (ENDS.has(r)) return;
        if (r === "yielded") i--; // the user's request took the page: this row again after it
      }
      let passes = 0;
      let tried = 0;
      for (;;) {
        await this.yieldTo(ctx);
        if (!time()) break;
        passes++;
        let found = false;
        for (const c of Y.candidatesFor(plan, this.tracker.taken())) {
          if (!time()) break;
          if (skip.has(c.yahoo_player_id) || !this.dom.find(c)) continue;
          found = true;
          tried++;
          const r = await this.tryRow(ctx, c, false, skip);
          if (ENDS.has(r)) return;
          if (r === "yielded") break; // the next pass starts again from the top
        }
        if (!found && time()) await this.recover(ctx, "no candidate's row");
        if (!(await this.pause(ctx, PASS_MS))) break;
      }
      if (passes && this.live(ctx)) {
        this.emit({ type: "note", what: "row passes", overall: ctx.k, passes, tried, resets: ctx.recovered || 0 });
      }
    }

    /** The first of the plan's candidates, in priced order, whose row the table shows now. */
    firstWithRow(plan) {
      return Y.candidatesFor(plan, this.tracker.taken()).find((x) => this.dom.find(x)) || null;
    }

    /** Take pick ``k``. Resolves to a summary; never throws. Starting it stops an older turn
     * that is still running, without waiting for it. */
    async turn(k) {
      const prev = this.current;
      if (this.tried.has(k) || (prev && prev.k >= k)) return null;
      if (this.done(k)) {
        // Taken before its turn began: only undo what an older turn left switched on.
        if (this.touched.autodraft || this.touched.queue) await this.tidy(this.tracker.isManual(k), true);
        return null;
      }
      this.tried.add(k);
      const ctx = turnContext(k);
      this.current = ctx;
      if (prev && !prev.settled) prev.stop("superseded");
      const t0 = this.now();
      const out = {
        overall: k,
        result: "none",
        how: null,
        yid: null,
        fresh: null,
        board: null,
        waited_ms: null,
        act_at_s: this.actAt,
        held_ms: null,
      };
      try {
        // The older turn left the page as it was when it stopped: this turn owns it now.
        if (this.touched.autodraft || this.touched.queue) await this.tidy(false);
        // With Autodraft on at this turn's frame, Yahoo has already taken the pick.
        if (!this.live(ctx)) return this.finish(out, ctx);
        // A plan is this turn's only when it was solved on picks 1..k-1. The API's own
        // ``fresh`` is not enough: while the sync of pick k-1 is still in flight, the previous
        // board's plan is fresh to the API (pick 144 of the 2026-10-01 harness run).
        const board = k - 1;
        const current = (p) => Boolean(p && p !== STOP && p.fresh && p.board === board);
        const by = this.actAt === null ? START_BY_S : Math.max(START_BY_S, this.actAt);
        const first = planWait(this.left(), by);
        const until = this.now() + first * 1000;
        const waitLeft = () =>
          Math.max(0, Math.min(planWait(this.left(), by), Math.floor((until - this.now()) / 1000)));
        let plan = await this.ask(ctx, first, board);
        while (plan !== STOP && !current(plan) && this.live(ctx)) {
          const wait = waitLeft();
          if (wait <= 0) {
            // The solve can land just after the wait gives up: one last look before clicking.
            const again = await this.ask(ctx, 0, board);
            if (current(again)) plan = again;
            break;
          }
          // An answer for an older board came back before the wait was up (the API predates
          // the board contract), or none did (the ask failed): ask again.
          if (!(await this.pause(ctx, plan ? ASK_AGAIN_MS : RETRY_MS))) break;
          const again = await this.ask(ctx, waitLeft(), board);
          if (again === STOP) break;
          if (again) plan = again;
        }
        if (plan === STOP) plan = null;
        // act_at_s: the click waits for its time unless the user picks first, then the plan is
        // looked at once more (a pin or a re-solve on this board since).
        if (this.actAt !== null && this.live(ctx)) {
          const from = this.now();
          const held = await this.holdTill(ctx);
          out.held_ms = this.now() - from;
          if (held && this.live(ctx)) {
            const again = await this.ask(ctx, 0, board);
            if (current(again)) plan = again;
          }
        }
        // The plan the page fetched ahead for this pick, when it is on this turn's board or the
        // asks brought nothing at all (an older board's plan is acted on as stale).
        const held = this.live(ctx) && !current(plan) ? this.held(k) : null;
        if (held && (current(held) || !plan)) plan = held;
        if (ctx.planErrors) {
          this.emit({
            type: "note",
            what: "plan errors",
            overall: k,
            errors: ctx.planErrors,
            msg: ctx.planError,
            board: plan && Number.isInteger(plan.board) ? plan.board : null,
          });
        }
        out.fresh = current(plan);
        out.board = plan && Number.isInteger(plan.board) ? plan.board : null;
        out.waited_ms = plan ? plan.waited_ms : null;
        ctx.board = out.board;
        if (!this.live(ctx)) return this.finish(out, ctx);
        const cands = Y.candidatesFor(plan, this.tracker.taken()).slice(0, MAX_CANDIDATES);
        if (!cands.length) {
          this.emit({ type: "note", what: "no candidates", overall: k });
          return this.finish(out, ctx);
        }
        // The previous pick's row leaves the table about a second after its frame.
        const lastAt = Math.max(0, ...[...this.tracker.picks.values()].map((p) => p.t));
        while (this.now() - lastAt < 900 && this.live(ctx)) {
          if (!(await this.pause(ctx, 150))) break;
        }

        await this.yieldTo(ctx);
        if (this.live(ctx)) await this.view(ctx);
        await this.yieldTo(ctx);
        if (this.probeDue(k) && this.live(ctx) && this.leftOrPlenty() > BACKSTOP_BY_S + 8) {
          await this.probe(ctx, cands.find((x) => !this.tracker.taken().has(String(x.yahoo_player_id))));
        }
        await this.rows(ctx, plan, cands);
        await this.yieldTo(ctx);
        if (this.live(ctx)) await this.backstop(ctx, plan, cands);
        return this.finish(out, ctx);
      } catch (e) {
        this.emit({ type: "note", what: "turn error", overall: k, msg: String((e && e.message) || e) });
        return this.finish(out, ctx);
      } finally {
        // A superseded turn leaves the page to the newer one, which tidies it before acting.
        if (ctx.stopped !== "superseded") {
          try {
            await this.tidy(this.tracker.isManual(k), this.tracker.picks.has(k));
          } catch (_) {
            // the guard loop retries between turns
          }
        }
        ctx.settled = true;
        out.stopped = ctx.stopped;
        out.ms = this.now() - t0;
        this.last = out;
      }
    }

    /** By 6 s left: the best remaining candidate alone in Yahoo's queue with Autodraft on, for
     * this pick only; when my next pick follows (slots 1 and 12), the plan's player for it
     * behind. When the user's request for this pick landed nothing, the requested player goes
     * first and the best candidate second, for this pick and, back to back, for the next
     * (#26); if the requested player cannot be queued, the backstop is the usual one. The
     * attempts are stamped as the switch is thrown: Yahoo can pick before the switch returns.
     * On my turn a row's star can draft its player (as the queue probe found): then the pick
     * is in and the backstop ends there. */
    async backstop(ctx, plan, cands) {
      const k = ctx.k;
      const taken = this.tracker.taken();
      const top = cands.find((x) => !taken.has(String(x.yahoo_player_id))) || Y.candidatesFor(plan, taken)[0] || null;
      const f = this.failed;
      const asked = f && f.k === k && !taken.has(f.c.yahoo_player_id) ? f.c : null;
      if (!top && !asked) return;
      const backToBack = this.tracker.mine.includes(k + 1);
      this.touched.queue = true;
      this.tracker.noteAttempt(k, "queue"); // the star may draft
      // Before the requested player's star too: if Yahoo takes that player for this pick, by
      // the queue or the star, the pick is the user's.
      if (asked) this.tracker.noteRequested(k, asked.yahoo_player_id);
      let head = null;
      let q = { ok: false, msg: "nothing queued" };
      let t = this.now();
      const until = this.clockAt(LAST_LOOK_S);
      if (asked) {
        q = await this.page(() => this.dom.queueOnly(asked, until));
        if (q.ok) head = asked;
        else {
          this.emit({
            type: "note",
            what: "queue backstop: requested player failed",
            overall: k,
            yid: asked.yahoo_player_id,
            msg: q.msg,
          });
        }
      }
      if (!head && top && this.live(ctx)) {
        // The first candidate whose row the reset view shows, in priced order (mock 7, pick 68:
        // the top had none); with none, the top, which the queue scrolls for. While no candidate
        // has a row, the turn keeps looking until 2 s before the clock runs out: an expiry is
        // the same outcome as giving up.
        await this.page(() => this.dom.reset());
        let c = this.firstWithRow(plan) || top;
        for (;;) {
          t = this.now();
          q = await this.page(() => this.dom.queueOnly(c, until));
          if (q.ok) {
            head = c;
            break;
          }
          if (!NO_ROW.has(q.msg)) break;
          let next = null;
          while (!next && this.live(ctx) && this.before(ctx, LAST_LOOK_S)) {
            await this.recover(ctx, "backstop: no candidate's row");
            if (!(await this.pause(ctx, PASS_MS))) break;
            next = this.firstWithRow(plan);
          }
          if (!next || !this.live(ctx)) break;
          c = next;
        }
      }
      const drafted = () => {
        const p = this.tracker.picks.get(k);
        if (!p || !head || p.yid !== String(head.yahoo_player_id)) return false;
        this.attempt(ctx, head, "queue", 1, k, t);
        return true;
      };
      const landedRequest = () => {
        const p = this.tracker.picks.get(k);
        if (head === asked && p && p.yid === asked.yahoo_player_id) {
          this.emit({ type: "note", what: "backstop landed the request", overall: k, yid: p.yid, request_id: f.id });
        }
      };
      if (drafted()) return landedRequest(); // the star drafted the head
      // Behind the head: the best candidate after a failed request, for this pick too;
      // otherwise, back to back, the plan's player for my next pick.
      const also = head && head === asked && top && String(top.yahoo_player_id) !== asked.yahoo_player_id ? top : null;
      let behind = null;
      if (head && q.ok && this.live(ctx)) {
        const want = also || (backToBack ? this.nextFor(plan, k, head) : null);
        const q2 = want ? await this.page(() => this.dom.queueAlso(want, head, until)) : null;
        if (q2 && q2.ok) behind = want;
        else if (q2) {
          if (drafted()) return landedRequest();
          this.emit({ type: "note", what: "queue backstop: second entry failed", overall: also ? k : k + 1, msg: q2.msg });
          q = q2.single; // the adapter put the head back alone, or could not
        }
      }
      if (drafted()) return landedRequest();
      if (!head || !q.ok) {
        this.emit({ type: "note", what: "queue backstop failed", overall: k, msg: q.msg });
        return;
      }
      if (!this.live(ctx)) return;
      const next = backToBack ? behind : null; // Yahoo's pick for my next turn: the queue's next
      this.touched.autodraft = true;
      if (next) this.tracker.noteAttempt(k + 1, "queue");
      t = this.now();
      await this.page(() => this.dom.setAutodraft(true));
      this.attempt(ctx, head, "queue", 1, k, t);
      if (behind && behind === also) this.attempt(ctx, behind, "queue", 2, k, t);
      // Logged on this turn's board, k-1: the scorecard labels pick k+1 stale.
      if (next) this.attempt(ctx, next, "queue", 1, k + 1, t);
      const left = this.left();
      await this.waitDone(ctx, ((left === null ? 10 : Math.max(0, left)) + 3) * 1000);
      landedRequest();
    }

    /** The probe runs once per draft: on my first turn from ``probeRound`` on whose next pick
     * is not also mine (that turn's backstop may queue two). */
    probeDue(k) {
      if (!this.probeRound || this.probed !== null) return false;
      return Math.ceil(k / this.tracker.numTeams) >= this.probeRound && !this.tracker.mine.includes(k + 1);
    }

    /** Star ``c`` and log what Yahoo did: a note ``queue_probe`` (a type every API version
     * accepts). A star that drafted ``c`` is this turn's row pick. */
    async probe(ctx, c) {
      if (!c) return;
      const k = ctx.k;
      this.probed = k;
      this.touched.queue = true; // a queued star is cleared after the turn, as usual
      this.tracker.noteAttempt(k, "row"); // the star may draft
      const t = this.now();
      let r;
      try {
        r = await this.page(() => this.dom.probeQueue(c, this.clockAt(BACKSTOP_BY_S + 2)));
      } catch (e) {
        r = { outcome: "failed", panel: null, control: null, msg: String((e && e.message) || e) };
      }
      const yid = String(c.yahoo_player_id);
      if (r.outcome === "drafted") this.attempt(ctx, c, "row", 1, k, t);
      this.emit({ type: "note", what: "queue_probe", t, overall: k, yid, name: c.name, board: ctx.board, ...r });
    }

    /** The plan's player for my pick k+1 when it follows k: ``plan.second`` (built on this
     * turn's board for pick k+1, the plan's own player first), else the next candidate. */
    nextFor(plan, k, c) {
      const taken = this.tracker.taken();
      const first = String(c.yahoo_player_id);
      const second = plan && plan.second_pick === k + 1 ? plan.second || [] : [];
      const pool = [...second, ...((plan && plan.candidates) || [])];
      const pick = pool.find((x) => {
        const yid = String(x.yahoo_player_id);
        return yid !== first && !taken.has(yid);
      });
      return pick ? { ...pick, yahoo_player_id: String(pick.yahoo_player_id) } : null;
    }

    finish(out, ctx) {
      const k = ctx.k;
      const p = this.tracker.picks.get(k);
      if (this.tracker.isManual(k)) out.result = "manual";
      else if (p) out.result = "landed";
      else if (ctx.stopped === "superseded") out.result = "superseded";
      out.yid = p ? p.yid : null;
      out.how = p ? this.tracker.how(k, { autodraft: this.dom.autodraftOn() === true }) : null;
      out.attempts = ctx.attempts;
      return out;
    }

    /** Why a turn's row draft ended early: "manual", "landed" or "stopped". */
    outcome(ctx) {
      if (this.tracker.isManual(ctx.k)) return "manual";
      if (this.tracker.picks.has(ctx.k)) return "landed";
      return "stopped";
    }

    /** Click candidate ``c``'s row; "landed", "manual", "stopped", "noRow", "mismatch",
     * "noButton", "notLanded" or "yielded" (the user's request took the page). ``scroll``: look
     * for a row the table does not show by scrolling Yahoo's list (to a second before the
     * backstop line). Page actions are not cut short (a click settles in ~400 ms); the waits
     * between them are. */
    async rowDraft(ctx, c, scroll = true) {
      const k = ctx.k;
      for (let i = 0; i < 8 && !this.dom.draftable(); i++) {
        if (!(await this.pause(ctx, 250)) || !this.live(ctx)) return this.outcome(ctx);
      }
      let via = "row";
      let row = this.dom.find(c);
      if (!row && scroll) {
        via = "scroll";
        row = await this.page(() => this.dom.scrollTo(c, this.clockAt(BACKSTOP_BY_S + 1)));
      }
      if (!row && scroll && this.searchFallback && this.live(ctx) && this.leftOrPlenty() > BACKSTOP_BY_S + 2) {
        via = "search";
        row = await this.page(() => this.dom.search(c));
      }
      if (!this.live(ctx)) return this.outcome(ctx);
      if (!row) return "noRow";
      if (this.yields(k)) return "yielded";
      let r = await this.clickFor(ctx, row, c, "row");
      if (r === "mismatch" && this.live(ctx)) {
        await this.page(() => this.dom.nudge());
        row = this.dom.find(c);
        r = row && this.live(ctx) ? await this.clickFor(ctx, row, c, "row") : "none";
      }
      if (r === "mismatch") return "mismatch";
      if (r !== "clicked") return this.live(ctx) ? "noButton" : this.outcome(ctx);
      // Stamped at the click, not when it settled: a reco that lands while it settles came
      // after the choice (the scorecard judges the pick by the reco before its first attempt).
      this.attempt(ctx, c, via, 1, k, ctx.clickAt);
      let n = 1;
      for (const gap of RECLICK_MS) {
        const budget = Math.min(gap, ((this.left() ?? 30) - BACKSTOP_BY_S) * 1000);
        if (budget <= 0) break;
        if ((await this.waitDone(ctx, budget)) || !this.live(ctx)) break;
        if (this.yields(k)) return "yielded";
        const again = this.dom.find(c);
        if (!again || (await this.clickFor(ctx, again, c, "row")) !== "clicked") break;
        n++;
        this.attempt(ctx, c, via, n, k, ctx.clickAt);
      }
      if (!this.live(ctx)) return this.outcome(ctx);
      const rest = ((this.left() ?? 30) - BACKSTOP_BY_S) * 1000;
      if (rest > 0 && (await this.waitDone(ctx, Math.min(4000, rest)))) return this.outcome(ctx);
      return this.live(ctx) ? "notLanded" : this.outcome(ctx);
    }
  }

  return { Drafter, planWait, START_BY_S, BACKSTOP_BY_S };
});
