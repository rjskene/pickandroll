// The room as the extension sees it: every pick from the socket with its arrival time, the pick
// on the clock, how far the API has synced, and the fidelity events (docs/YAHOO_SYNC.md §4) to
// post. Pure: times are passed in, nothing here touches the DOM, the network or chrome.*.
(function (root, factory) {
  const node = typeof module === "object" && module.exports;
  const api = factory(node ? require("./protocol.js") : root.PickAndRoll);
  if (node) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function (P) {
  "use strict";

  class RoomTracker {
    constructor({ draftId, slot, numTeams = 12, rounds = 13 }) {
      this.draftId = draftId;
      this.slot = slot;
      this.numTeams = numTeams;
      this.rounds = rounds;
      this.picks = new Map(); // overall -> {overall, yid, slot, t, src}
      this.sent = 0; // the API has applied every pick through this overall
      this.gap = null; // the API is waiting for this overall
      this.onDeck = null; // {overall, slot, clock, at}
      this.clock = null; // {value, at}: seconds left on the current pick
      this.turnAt = new Map(); // overall -> when it went on the clock
      this.manual = null; // {overall, at, label}: a trusted click on a Draft control on my turn
      this.attempts = new Map(); // overall -> how the extension drafted it ("row" | "queue")
      this.yahooMade = new Set(); // my overalls Yahoo announced it would pick itself (5|slot)
      this.landed = new Set();
      this.outbox = [];
      this.frames = 0;
    }

    configure({ slot, numTeams, rounds } = {}) {
      if (slot) this.slot = slot;
      if (numTeams) this.numTeams = numTeams;
      if (rounds) this.rounds = rounds;
    }

    get mine() {
      return P.snakePicks(this.numTeams, this.slot, this.rounds);
    }

    isMine(overall) {
      return P.pickOwner(this.numTeams, overall).slot === this.slot;
    }

    /** Highest overall seen. */
    last() {
      let m = 0;
      for (const k of this.picks.keys()) if (k > m) m = k;
      return m;
    }

    /** Highest k such that picks 1..k are all known. */
    contiguous() {
      let k = 0;
      while (this.picks.has(k + 1)) k++;
      return k;
    }

    taken() {
      return new Set([...this.picks.values()].map((p) => p.yid));
    }

    /** My first pick not made yet, or null when my roster is full. */
    nextMine() {
      return this.mine.find((k) => !this.picks.has(k)) ?? null;
    }

    /** The overall on the clock when it is mine and not made yet, else null. */
    myTurnNow() {
      const d = this.onDeck;
      return d && d.slot === this.slot && !this.picks.has(d.overall) ? d.overall : null;
    }

    clockLeft(t) {
      if (!this.clock) return null;
      return this.clock.value - (t - this.clock.at) / 1000;
    }

    /** Feed one socket frame received at ``t`` (epoch ms). */
    ingest(text, t) {
      this.frames++;
      const m = P.parseMessage(text);
      const out = { kind: m ? m.kind : null, picks: 0, turn: null, landed: null };
      if (!m) return out;
      if (m.kind === "pick") {
        if (this.add(m.overall, m.yid, m.slot, t, "socket")) {
          out.picks = 1;
          out.landed = this.landedRecord(m.overall, t);
        }
      } else if (m.kind === "history") {
        for (const p of m.picks) if (this.add(p.overall, p.yid, p.slot, t, "history")) out.picks++;
      } else if (m.kind === "on_deck") {
        this.onDeck = { overall: m.overall, slot: m.slot, clock: m.clock, at: t };
        if (m.clock !== null) this.clock = { value: m.clock, at: t };
        if (!this.turnAt.has(m.overall) && !this.picks.has(m.overall)) {
          this.turnAt.set(m.overall, t);
          this.outbox.push({
            type: "turn_start",
            t,
            overall: m.overall,
            slot: m.slot,
            clock_s: m.clock,
          });
        }
        if (m.slot === this.slot && !this.picks.has(m.overall)) out.turn = m.overall;
      } else if (m.kind === "clock") {
        this.clock = { value: m.clock, at: t };
      } else if (m.kind === "auto" && m.slot === this.slot) {
        const d = this.onDeck;
        const k = d && d.slot === this.slot && !this.picks.has(d.overall) ? d.overall : this.nextMine();
        if (k !== null) this.yahooMade.add(k);
      }
      return out;
    }

    add(overall, yid, slot, t, src) {
      if (this.picks.has(overall)) return false;
      this.picks.set(overall, { overall, yid: String(yid), slot, t, src });
      return true;
    }

    /** A trusted click on a Draft control: if it is my turn, the pick is the user's. */
    noteManual(t, label) {
      const k = this.myTurnNow();
      if (k === null) return null;
      if (!this.manual || this.manual.overall !== k) this.manual = { overall: k, at: t, label };
      return k;
    }

    isManual(overall) {
      return Boolean(this.manual && this.manual.overall === overall);
    }

    noteAttempt(overall, how) {
      this.attempts.set(overall, how);
    }

    /** How a pick of mine landed, as far as the room shows it: the user's trusted click, then
     * Yahoo's own pick (announced by 5|slot; ``autodraft`` is Yahoo's Autodraft switch at
     * landing time), then the extension's attempt. Null when nothing says. */
    how(overall, { autodraft = false } = {}) {
      if (this.isManual(overall)) return "manual";
      if (this.yahooMade.has(overall)) return autodraft ? "autopick" : "expiry";
      if (this.attempts.has(overall)) return this.attempts.get(overall);
      return null;
    }

    /** For a pick of mine that just arrived: what the caller needs to post pick_landed. */
    landedRecord(overall, t) {
      if (!this.isMine(overall) || this.landed.has(overall)) return null;
      this.landed.add(overall);
      const turn = this.turnAt.get(overall);
      return {
        overall,
        yid: this.picks.get(overall).yid,
        t,
        ms_from_turn: turn === undefined ? null : t - turn,
      };
    }

    /** The pick_landed event, or null when nothing says how the pick was made. */
    landedEvent(rec, context) {
      const how = this.how(rec.overall, context);
      if (!how) return null;
      return { type: "pick_landed", ...rec, how };
    }

    /** Picks the API has not applied yet, as POST /rooms/{d}/picks items. */
    unsent() {
      return [...this.picks.values()]
        .filter((p) => p.overall > this.sent)
        .sort((a, b) => a.overall - b.overall)
        .map((p) => ({
          overall: p.overall,
          yahoo_player_id: p.yid,
          slot: p.slot,
          t_room: p.t,
          src: p.src,
        }));
    }

    /** Record an API answer (POST /picks or GET /rooms/{d}). */
    synced(resp) {
      if (!resp) return;
      if (typeof resp.synced_through === "number") this.sent = resp.synced_through;
      this.gap = resp.waiting_for ?? null;
    }

    /** Picks the room has that the session does not. */
    behind() {
      return Math.max(0, this.last() - this.sent);
    }

    takeEvents() {
      return this.outbox.splice(0);
    }

    snapshot() {
      return {
        draft_id: this.draftId,
        slot: this.slot,
        num_teams: this.numTeams,
        rounds: this.rounds,
        room_picks: this.picks.size,
        last: this.last(),
        contiguous: this.contiguous(),
        sent: this.sent,
        gap: this.gap,
        behind: this.behind(),
        on_deck: this.onDeck,
        my_turn: this.myTurnNow(),
        next_mine: this.nextMine(),
        frames: this.frames,
      };
    }
  }

  return { RoomTracker };
});
