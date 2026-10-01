// One armed turn: take pickandroll's pick in Yahoo's draft client. A port of the hook used in the
// September mock drafts (v16), with the deadlines of the #9 review:
//   1. hold GET /plan?wait&board for the solve of this turn's board (picks 1..k-1), but stop
//      waiting by 12 s left on the clock; a plan for an older board is asked for again;
//   2. click the first available candidate's Draft button; Yahoo drops a click that lands during
//      a re-render and confirms a registered one within ~400 ms, so re-click the same row at
//      1.8 s and again at 2.5 s; scroll, then search, when the row is not in view;
//   3. fall through to the next candidate;
//   4. by 6 s left, put the best remaining candidate alone in Yahoo's queue with Autodraft on,
//      for this pick only; after the turn Autodraft goes off and the queue is emptied.
// A trusted click by the user on any Draft control during the turn makes the pick theirs: the
// drafter stops at once and touches nothing more.
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

  /** Seconds to hold /plan for a fresh solve with ``left`` seconds on the clock. */
  function planWait(left) {
    if (left === null || left === undefined || Number.isNaN(left)) return PLAN_WAIT_MAX_S;
    return Math.max(0, Math.min(PLAN_WAIT_MAX_S, Math.floor(left - START_BY_S)));
  }

  class Drafter {
    /**
     * @param {object} o
     * @param {object} o.tracker RoomTracker of this room
     * @param {object} o.dom     the draft client: draftable(), find(c), scrollTo(c), search(c),
     *                           async click(row, c) -> "clicked" | "mismatch" | "none", nudge(),
     *                           queueOnly(c) -> {ok, msg}, setAutodraft(on), autodraftOn(),
     *                           clearQueue(), reset()
     * @param {function} o.plan  async (wait_s, board) -> GET /rooms/{d}/plan, held until the
     *                           solve of ``board`` (the number of picks it was built on)
     * @param {function} o.emit  client event sink
     * @param {function} o.sleep async (ms)
     * @param {function} o.now   epoch ms
     */
    constructor({ tracker, dom, plan, emit, sleep, now, log }) {
      Object.assign(this, { tracker, dom, plan, emit, sleep, now });
      this.log = log || (() => {});
      this.busy = false;
      this.tried = new Set(); // overalls a turn was started for
      this.last = null; // the last turn's summary
    }

    left() {
      return this.tracker.clockLeft(this.now());
    }

    /** The pick landed, or the user took it over. */
    done(k) {
      return this.tracker.picks.has(k) || this.tracker.isManual(k);
    }

    async waitDone(k, ms) {
      const end = this.now() + ms;
      while (this.now() < end) {
        if (this.done(k)) return true;
        await this.sleep(Math.min(200, Math.max(1, end - this.now())));
      }
      return this.done(k);
    }

    attempt(k, c, method, n) {
      this.attempts++;
      this.emit({
        type: "draft_attempt",
        t: this.now(),
        overall: k,
        yid: String(c.yahoo_player_id),
        name: c.name,
        method,
        attempt: n,
        board: this.board, // the board of the plan acted on
      });
    }

    /** Take pick ``k``. Resolves to a summary; never throws. */
    async turn(k) {
      if (this.busy || this.tried.has(k) || this.done(k)) return null;
      this.busy = true;
      this.tried.add(k);
      this.attempts = 0;
      const t0 = this.now();
      const out = {
        overall: k,
        result: "none",
        how: null,
        yid: null,
        fresh: null,
        board: null,
        waited_ms: null,
      };
      let autodraft = false;
      this.board = null;
      try {
        // A plan is this turn's only when it was solved on picks 1..k-1. The API's own
        // ``fresh`` is not enough: while the sync of pick k-1 is still in flight, the previous
        // board's plan is fresh to the API (pick 144 of the 2026-10-01 harness run).
        const board = k - 1;
        const current = (p) => Boolean(p && p.fresh && p.board === board);
        const first = planWait(this.left());
        const until = this.now() + first * 1000;
        const waitLeft = () =>
          Math.max(0, Math.min(planWait(this.left()), Math.floor((until - this.now()) / 1000)));
        let plan = await this.plan(first, board);
        while (!current(plan) && !this.done(k)) {
          const wait = waitLeft();
          if (wait <= 0) {
            // The solve can land just after the wait gives up: one last look before clicking.
            const again = await this.plan(0, board);
            if (current(again)) plan = again;
            break;
          }
          // An answer for an older board came back before the wait was up (the API predates
          // the board contract): ask again.
          await this.sleep(ASK_AGAIN_MS);
          const again = await this.plan(waitLeft(), board);
          if (again) plan = again;
        }
        out.fresh = current(plan);
        out.board = plan && Number.isInteger(plan.board) ? plan.board : null;
        out.waited_ms = plan ? plan.waited_ms : null;
        this.board = out.board;
        if (this.done(k)) return this.finish(out, k);
        const cands = Y.candidatesFor(plan, this.tracker.taken()).slice(0, MAX_CANDIDATES);
        if (!cands.length) {
          this.emit({ type: "note", what: "no candidates", overall: k });
          return this.finish(out, k);
        }
        // The previous pick's row leaves the table about a second after its frame.
        const lastAt = Math.max(0, ...[...this.tracker.picks.values()].map((p) => p.t));
        while (this.now() - lastAt < 900 && !this.done(k)) await this.sleep(150);

        for (const c of cands) {
          if (this.done(k) || this.left() <= BACKSTOP_BY_S) break;
          if (this.tracker.taken().has(String(c.yahoo_player_id))) continue;
          const r = await this.rowDraft(k, c);
          this.log(`#${k} ${c.name}: ${r}`);
          if (r === "landed" || r === "manual") break;
        }
        if (!this.done(k)) {
          const c = cands.find((x) => !this.tracker.taken().has(String(x.yahoo_player_id)));
          if (c) {
            const q = await this.dom.queueOnly(c);
            if (q.ok && !this.done(k)) {
              autodraft = true;
              this.tracker.noteAttempt(k, "queue"); // Yahoo can pick the instant the switch is on
              await this.dom.setAutodraft(true);
              this.attempt(k, c, "queue", 1);
              const left = this.left();
              await this.waitDone(k, ((left === null ? 10 : Math.max(0, left)) + 3) * 1000);
            } else if (!q.ok) {
              this.emit({ type: "note", what: "queue backstop failed", overall: k, msg: q.msg });
            }
          }
        }
        return this.finish(out, k);
      } catch (e) {
        this.emit({ type: "note", what: "turn error", overall: k, msg: String((e && e.message) || e) });
        return this.finish(out, k);
      } finally {
        try {
          // After a hand pick the page is the user's: only undo what the drafter switched on.
          const manual = this.tracker.isManual(k);
          if (autodraft || (!manual && this.dom.autodraftOn() === true)) await this.dom.setAutodraft(false);
          if (autodraft || !manual) await this.dom.clearQueue();
          if (!manual) await this.dom.reset();
        } catch (_) {
          // the guard loop retries between turns
        }
        out.ms = this.now() - t0;
        this.last = out;
        this.busy = false;
      }
    }

    finish(out, k) {
      const p = this.tracker.picks.get(k);
      if (this.tracker.isManual(k)) out.result = "manual";
      else if (p) out.result = "landed";
      out.yid = p ? p.yid : null;
      out.how = p ? this.tracker.how(k, { autodraft: this.dom.autodraftOn() === true }) : null;
      out.attempts = this.attempts;
      return out;
    }

    /** Click candidate ``c``'s row; "landed", "manual", "noRow", "mismatch", "noButton" or
     * "notLanded". */
    async rowDraft(k, c) {
      for (let i = 0; i < 8 && !this.dom.draftable(); i++) {
        await this.sleep(250);
        if (this.done(k)) return this.tracker.isManual(k) ? "manual" : "landed";
      }
      let via = "row";
      let row = this.dom.find(c);
      if (!row) {
        via = "scroll";
        row = await this.dom.scrollTo(c);
      }
      if (!row && this.left() > BACKSTOP_BY_S + 2) {
        via = "search";
        row = await this.dom.search(c);
      }
      if (this.done(k)) return this.tracker.isManual(k) ? "manual" : "landed";
      if (!row) return "noRow";
      // Noted before the click: the pick can land while the click is still settling.
      this.tracker.noteAttempt(k, "row");
      let r = await this.dom.click(row, c);
      if (r === "mismatch") {
        await this.dom.nudge();
        row = this.dom.find(c);
        r = row ? await this.dom.click(row, c) : "none";
      }
      if (r === "mismatch") return "mismatch";
      if (r !== "clicked") return "noButton";
      this.attempt(k, c, via, 1);
      let n = 1;
      for (const gap of RECLICK_MS) {
        const budget = Math.min(gap, ((this.left() ?? 30) - BACKSTOP_BY_S) * 1000);
        if (budget <= 0) break;
        if (await this.waitDone(k, budget)) break;
        const again = this.dom.find(c);
        if (!again || (await this.dom.click(again, c)) !== "clicked") break;
        n++;
        this.attempt(k, c, via, n);
      }
      if (this.tracker.isManual(k)) return "manual";
      if (this.tracker.picks.has(k)) return "landed";
      const rest = ((this.left() ?? 30) - BACKSTOP_BY_S) * 1000;
      if (rest > 0 && (await this.waitDone(k, Math.min(4000, rest)))) {
        return this.tracker.isManual(k) ? "manual" : "landed";
      }
      return "notLanded";
    }
  }

  return { Drafter, planWait, START_BY_S, BACKSTOP_BY_S };
});
