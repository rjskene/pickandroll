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
//   3. fall through to the next candidate;
//   4. by 6 s left, put the best remaining candidate alone in Yahoo's queue with Autodraft on,
//      for this pick only; after the turn Autodraft goes off and the queue is emptied. One
//      exception (user, 2026-10-02): when my next pick follows this one (slots 1 and 12), the
//      plan's player for it goes in behind, so Yahoo's instant autopick at that turn's start
//      takes ours rather than its own ranking's.
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
// it lands nothing, a note "request failed" drops it and the turn goes on, backstop included.
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
      stopped: null, // "superseded" by a newer turn, or "manual" (the user took the pick)
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
     * @param {object} o.dom     the draft client: draftable(), find(c), scrollTo(c), search(c),
     *                           async click(row, c) -> "clicked" | "mismatch" | "none", nudge(),
     *                           queueOnly(c) -> {ok, msg}, queueAlso(c2, c) -> {ok, msg, single}
     *                           (c2 behind c; on failure ``single`` is queueOnly(c) redone),
     *                           probeQueue(c) -> {outcome, panel, control},
     *                           setAutodraft(on), autodraftOn(), clearQueue(), reset()
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
      this.requesting = null; // the user's pending request: {k, ctx, settled}
      this.requests = new Set(); // requests served, by overall and player
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
      const key = `${k}:${c.yahoo_player_id}`;
      if (this.requests.has(key) || this.requesting) return null;
      this.requests.add(key);
      const ctx = turnContext(k);
      ctx.board = Number.isInteger(q.board) ? q.board : null;
      let settle;
      const settled = new Promise((resolve) => {
        settle = resolve;
      });
      this.requesting = { k, ctx, settled };
      const out = { overall: k, yid: c.yahoo_player_id, result: "failed", attempts: 0 };
      try {
        for (let n = 1; n <= REQUEST_TRIES && this.live(ctx) && this.tracker.myTurnNow() === k; n++) {
          let row = this.dom.find(c) || (await this.page(() => this.dom.scrollTo(c)));
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
              this.attempt(ctx, c, "request", n);
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
          this.emit({ type: "note", what: "request failed", overall: k, yid: c.yahoo_player_id, attempts: out.attempts });
        }
        return out;
      } catch (e) {
        this.emit({ type: "note", what: "request failed", overall: k, yid: c.yahoo_player_id, msg: String((e && e.message) || e) });
        return out;
      } finally {
        this.requesting = null;
        ctx.settled = true;
        settle();
      }
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
     * pick the page is the user's: only what the drafter switched on is undone. */
    async tidy(manual) {
      if (this.touched.autodraft || (!manual && this.dom.autodraftOn() === true)) {
        const on = await this.page(() => this.dom.setAutodraft(false));
        if (on === true) return; // still on: leave the queue alone
        this.touched.autodraft = false;
      }
      if (this.touched.queue || !manual) {
        await this.page(() => this.dom.clearQueue());
        this.touched.queue = false;
      }
      if (!manual) await this.page(() => this.dom.reset());
    }

    /** Take pick ``k``. Resolves to a summary; never throws. Starting it stops an older turn
     * that is still running, without waiting for it. */
    async turn(k) {
      const prev = this.current;
      if (this.tried.has(k) || (prev && prev.k >= k)) return null;
      if (this.done(k)) {
        // Taken before its turn began: only undo what an older turn left switched on.
        if (this.touched.autodraft || this.touched.queue) await this.tidy(this.tracker.isManual(k));
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
        if (this.probeDue(k) && this.live(ctx) && this.leftOrPlenty() > BACKSTOP_BY_S + 8) {
          await this.probe(ctx, cands.find((x) => !this.tracker.taken().has(String(x.yahoo_player_id))));
        }

        for (let i = 0; i < cands.length; i++) {
          await this.yieldTo(ctx);
          if (!this.live(ctx) || this.leftOrPlenty() <= BACKSTOP_BY_S) break;
          const c = cands[i];
          if (this.tracker.taken().has(String(c.yahoo_player_id))) continue;
          const r = await this.rowDraft(ctx, c);
          this.log(`#${k} ${c.name}: ${r}`);
          if (r === "landed" || r === "manual" || r === "stopped") break;
          if (r === "yielded") i--; // the user's request took the page: this row again after it
        }
        await this.yieldTo(ctx);
        if (this.live(ctx)) {
          const c = cands.find((x) => !this.tracker.taken().has(String(x.yahoo_player_id)));
          if (c) {
            this.touched.queue = true;
            let q = await this.page(() => this.dom.queueOnly(c));
            let next = null; // my next pick's player, queued behind (the back-to-back exception)
            if (q.ok && this.live(ctx) && this.tracker.mine.includes(k + 1)) {
              next = this.nextFor(plan, k, c);
              const q2 = next ? await this.page(() => this.dom.queueAlso(next, c)) : null;
              if (q2 && !q2.ok) {
                this.emit({ type: "note", what: "queue backstop: second entry failed", overall: k + 1, msg: q2.msg });
                next = null;
                q = q2.single; // the adapter put this pick's player back alone, or could not
              }
            }
            if (q.ok && this.live(ctx)) {
              this.touched.autodraft = true;
              this.tracker.noteAttempt(k, "queue"); // Yahoo can pick the instant the switch is on
              if (next) this.tracker.noteAttempt(k + 1, "queue");
              await this.page(() => this.dom.setAutodraft(true));
              this.attempt(ctx, c, "queue", 1);
              // Logged on this turn's board, k-1: the scorecard labels pick k+1 stale.
              if (next) this.attempt(ctx, next, "queue", 1, k + 1);
              const left = this.left();
              await this.waitDone(ctx, ((left === null ? 10 : Math.max(0, left)) + 3) * 1000);
            } else if (!q.ok) {
              this.emit({ type: "note", what: "queue backstop failed", overall: k, msg: q.msg });
            }
          }
        }
        return this.finish(out, ctx);
      } catch (e) {
        this.emit({ type: "note", what: "turn error", overall: k, msg: String((e && e.message) || e) });
        return this.finish(out, ctx);
      } finally {
        // A superseded turn leaves the page to the newer one, which tidies it before acting.
        if (ctx.stopped !== "superseded") {
          try {
            await this.tidy(this.tracker.isManual(k));
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
        r = await this.page(() => this.dom.probeQueue(c));
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
     * "noButton", "notLanded" or "yielded" (the user's request took the page). Page actions are not cut short (a click settles in ~400 ms);
     * the waits between them are. */
    async rowDraft(ctx, c) {
      const k = ctx.k;
      for (let i = 0; i < 8 && !this.dom.draftable(); i++) {
        if (!(await this.pause(ctx, 250)) || !this.live(ctx)) return this.outcome(ctx);
      }
      let via = "row";
      let row = this.dom.find(c);
      if (!row) {
        via = "scroll";
        row = await this.page(() => this.dom.scrollTo(c));
      }
      if (!row && this.searchFallback && this.live(ctx) && this.leftOrPlenty() > BACKSTOP_BY_S + 2) {
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
      this.attempt(ctx, c, via, 1);
      let n = 1;
      for (const gap of RECLICK_MS) {
        const budget = Math.min(gap, ((this.left() ?? 30) - BACKSTOP_BY_S) * 1000);
        if (budget <= 0) break;
        if ((await this.waitDone(ctx, budget)) || !this.live(ctx)) break;
        if (this.yields(k)) return "yielded";
        const again = this.dom.find(c);
        if (!again || (await this.clickFor(ctx, again, c, "row")) !== "clicked") break;
        n++;
        this.attempt(ctx, c, via, n);
      }
      if (!this.live(ctx)) return this.outcome(ctx);
      const rest = ((this.left() ?? 30) - BACKSTOP_BY_S) * 1000;
      if (rest > 0 && (await this.waitDone(ctx, Math.min(4000, rest)))) return this.outcome(ctx);
      return this.live(ctx) ? "notLanded" : this.outcome(ctx);
    }
  }

  return { Drafter, planWait, START_BY_S, BACKSTOP_BY_S };
});
