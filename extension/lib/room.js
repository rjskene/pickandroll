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

  // How far each source of a team's draft position is trusted. A round-1 frame is the room
  // putting that team on overall k; the title and the R| frame say so before the draft. A
  // source replaces a different answer only from a weaker one; an equal one keeps the first.
  const SEAT_TRUST = { title: 1, order: 1, frame: 2, given: 2 };

  class RoomTracker {
    /** ``teamId``: my Yahoo team id (the draft path's last number), which the room's frames
     * use. ``slot``: my draft position when it is already known (tests); otherwise it comes
     * from the title, the R| frame or round 1 (seat sources below). */
    constructor({ draftId, teamId = null, slot = null, numTeams = 12, rounds = 13 }) {
      this.draftId = draftId;
      this.teamId = teamId ?? slot;
      this.numTeams = numTeams;
      this.rounds = rounds;
      // Yahoo team id -> {pos, src}: the draft position the room gives each team, and pos ->
      // team id. Everything below the frames is positional; a team not placed yet has slot null.
      this.seats = new Map();
      this.byPos = new Map();
      this.firstSeen = new Map(); // team id -> the lowest overall a frame put it on
      this.titleSeen = new Set(); // "You pick Nth" values noted once the draft is on
      this.picks = new Map(); // overall -> {overall, yid, team, slot, t, src}
      this.owners = new Map(); // overall -> the slot the room put on it (picks and turns)
      this.orderLen = null; // entries in the room's R| frame (draft order), when one came
      this.order = null; // what the R| frame gave: {entries, teams} or {entries, error}
      this.sent = 0; // the API has applied every pick through this overall
      this.gap = null; // the API is waiting for this overall
      this.onDeck = null; // {overall, slot, clock, at}
      this.clock = null; // {value, at}: seconds left on the current pick
      this.turnAt = new Map(); // overall -> when it went on the clock
      this.manual = null; // {overall, at, label}: a trusted click on a Draft control on my turn
      this.attempts = new Map(); // overall -> how the extension drafted it ("row" | "queue")
      this.requested = new Map(); // overall -> the player of a failed request the backstop queued
      this.yahooMade = new Set(); // my overalls Yahoo announced it would pick itself (5|slot)
      this.landed = new Set();
      // Keeper slots, from the API's room (docs/KEEPERS.md): never a turn of mine, and filled
      // whether or not the room sends their picks.
      this.keepers = new Set();
      this.outbox = [];
      this.frames = 0;
      if (slot) this.learn(this.teamId, slot, "given", null);
    }

    /** My draft position, or null while no source has placed my team. */
    get slot() {
      const s = this.seats.get(this.teamId);
      return s ? s.pos : null;
    }

    /** Where my position came from: "title" | "order" | "frame" | "given", or null. */
    get seatSource() {
      const s = this.seats.get(this.teamId);
      return s ? s.src : null;
    }

    /** The draft position of Yahoo team ``team``, or null while it is not known. */
    seatOf(team) {
      const s = this.seats.get(team);
      return s ? s.pos : null;
    }

    /** Place ``team`` at draft position ``pos`` on the word of ``src``. A different answer
     * already held (for the team or for the position) is a "seat conflict" note; the new one
     * replaces it only when ``src`` is trusted more. Returns true when the map changed. */
    learn(team, pos, src, t) {
      if (!Number.isInteger(team) || team < 1 || !Number.isInteger(pos) || pos < 1 || pos > 20) return false;
      const had = this.seats.get(team);
      if (had && had.pos === pos) return false;
      const holder = this.byPos.get(pos);
      const rivals = [];
      if (had) rivals.push({ team, position: had.pos, src: had.src });
      if (holder !== undefined && holder !== team)
        rivals.push({ team: holder, position: pos, src: this.seats.get(holder).src });
      if (rivals.length) {
        const wins = rivals.every((r) => SEAT_TRUST[src] > SEAT_TRUST[r.src]);
        this.outbox.push({ type: "note", t, what: "seat conflict", team, position: pos, src, had: rivals, kept: wins ? "new" : "old" });
        if (!wins) return false;
        for (const r of rivals) {
          this.seats.delete(r.team);
          this.byPos.delete(r.position);
        }
      }
      const mine = this.slot;
      this.seats.set(team, { pos, src });
      this.byPos.set(pos, team);
      for (const r of rivals) if (r.team !== team) this.place(r.team);
      this.place(team);
      if (this.slot !== mine && src !== "given")
        this.outbox.push({ type: "note", t, what: "seat", team: this.teamId, slot: this.slot, src });
      return true;
    }

    /** Put ``team``'s current position on its picks, the pick on the clock and the owners. */
    place(team) {
      const pos = this.seatOf(team);
      for (const p of this.picks.values()) {
        if (p.team !== team) continue;
        p.slot = pos;
        if (pos === null) this.owners.delete(p.overall);
        else this.own(p.overall, pos);
      }
      const d = this.onDeck;
      if (d && d.team === team) {
        d.slot = pos;
        if (pos === null) this.owners.delete(d.overall);
        else this.own(d.overall, pos);
      }
    }

    /** A frame put ``team`` on ``overall``. In round 1 (k <= teams, the team on no earlier
     * overall) that is the team's draft position: in time for my first turn when nothing
     * earlier said it. */
    seen(overall, team, t) {
      if (!Number.isInteger(overall) || !Number.isInteger(team)) return;
      const first = this.firstSeen.get(team);
      if (overall <= this.numTeams && overall >= 1 && (first === undefined || first >= overall))
        this.learn(team, overall, "frame", t);
      if (first === undefined || overall < first) this.firstSeen.set(team, overall);
    }

    /** The tab title's "You pick Nth" (protocol.titlePosition). Before the first pick it can
     * only mean my seat; once a pick is in, Yahoo may mean the next overall or the picks to
     * go, so it is noted once per value and not used. Returns true when my seat changed. */
    fromTitle(n, t) {
      if (!Number.isInteger(n)) return false;
      const mine = this.slot;
      if (!this.picks.size) this.learn(this.teamId, n, "title", t);
      else if (n !== this.slot && !this.titleSeen.has(n) && this.titleSeen.size < 30) {
        this.titleSeen.add(n);
        this.outbox.push({ type: "note", t, what: "title seat", position: n, slot: this.slot, last: this.last() });
      }
      return this.slot !== mine;
    }

    configure({ numTeams, rounds, keepers } = {}) {
      if (numTeams) this.numTeams = numTeams;
      if (rounds) this.rounds = rounds;
      if (Array.isArray(keepers)) this.keepers = new Set(keepers.map((k) => Number(k.overall)));
    }

    /** My draftable picks: my snake picks without my keeper slots; none while my seat is not
     * known. */
    get mine() {
      const slot = this.slot;
      if (slot === null || slot > this.numTeams) return [];
      return P.snakePicks(this.numTeams, slot, this.rounds).filter((k) => !this.keepers.has(k));
    }

    isKeeper(overall) {
      return this.keepers.has(overall);
    }

    /** An overall of this draft: 1 .. teams x rounds (a fake room can run past the end). */
    inDraft(overall) {
      return Number.isInteger(overall) && overall >= 1 && overall <= this.numTeams * this.rounds;
    }

    /** A turn of mine: my slot's pick, not a keeper slot. */
    isMine(overall) {
      const slot = this.slot;
      return slot !== null && this.inDraft(overall) && P.pickOwner(this.numTeams, overall).slot === slot && !this.isKeeper(overall);
    }

    /** Highest overall seen. */
    last() {
      let m = 0;
      for (const k of this.picks.keys()) if (k > m) m = k;
      return m;
    }

    /** Highest k such that picks 1..k are all known; a keeper slot counts as known (the room
     * may never send its pick), and so does a pick the API has synced through without one (a
     * gap: a keeper the table does not know about, filled with a stand-in). */
    contiguous() {
      let k = this.sent;
      while (this.picks.has(k + 1) || this.isKeeper(k + 1)) k++;
      return k;
    }

    taken() {
      return new Set([...this.picks.values()].map((p) => p.yid));
    }

    /** My first pick not made yet, or null when my roster is full. */
    nextMine() {
      return this.mine.find((k) => !this.picks.has(k)) ?? null;
    }

    /** The overall on the clock when it is mine and not made yet, else null. A keeper slot of
     * mine on the clock is never my turn: its pick is the keeper. */
    myTurnNow() {
      const d = this.onDeck;
      return d && d.slot !== null && d.slot === this.slot && this.isMine(d.overall) && !this.picks.has(d.overall)
        ? d.overall
        : null;
    }

    clockLeft(t) {
      if (!this.clock) return null;
      return this.clock.value - (t - this.clock.at) / 1000;
    }

    /** Remember who the room says owns ``overall``: the evidence for teamsSeen. */
    own(overall, slot) {
      if (Number.isInteger(overall) && overall >= 1 && Number.isInteger(slot) && slot >= 1)
        this.owners.set(overall, slot);
    }

    /** The room's team count from the room itself (#17): the one T in 2..20 whose snake order
     * puts every pick and turn seen on the slot the room put it on. Null while more than one T
     * fits (until the snake first turns, pick T+1 back on slot T) or when none does. The attach
     * says the count; this is how the room's own count reaches the API (mock 2: a 10-team room
     * attached as 12). */
    teamsSeen() {
      let found = null;
      for (let T = 2; T <= 20; T++) {
        let fits = true;
        for (const [k, s] of this.owners) {
          if (P.pickOwner(T, k).slot !== s) {
            fits = false;
            break;
          }
        }
        if (!fits) continue;
        if (found !== null) return null;
        found = T;
      }
      return found;
    }

    /** Feed one socket frame received at ``t`` (epoch ms). */
    ingest(text, t) {
      this.frames++;
      const m = P.parseMessage(text);
      // landed: a pick of mine from a pick frame; history: mine from Yahoo's history frame (#26).
      const out = { kind: m ? m.kind : null, picks: 0, turn: null, landed: null, history: [] };
      if (!m) return out;
      // Frames name teams by Yahoo team id; each is placed (seatOf) before anything below reads
      // it, so owners, turns, my picks and the API's picks are all by draft position.
      const mine = this.slot;
      if (m.kind === "pick") {
        this.seen(m.overall, m.team, t);
        if (this.add(m.overall, m.yid, m.team, t, "socket")) {
          out.picks = 1;
          out.landed = this.landedRecord(m.overall, t);
        }
      } else if (m.kind === "history") {
        const picks = [...m.picks].sort((a, b) => a.overall - b.overall);
        for (const p of picks) this.seen(p.overall, p.team, t);
        for (const p of picks) {
          if (!this.add(p.overall, p.yid, p.team, t, "history")) continue;
          out.picks++;
          // Its t is when the frame came, not when the pick was made: no time from the turn.
          const rec = this.landedRecord(p.overall, t);
          if (rec) out.history.push({ ...rec, ms_from_turn: null });
        }
      } else if (m.kind === "order") {
        this.orderLen = m.order.length;
        this.fromOrder(m.order, t);
      } else if (m.kind === "on_deck") {
        this.seen(m.overall, m.team, t);
        const slot = this.seatOf(m.team);
        this.own(m.overall, slot);
        this.onDeck = { overall: m.overall, slot, team: m.team, clock: m.clock, at: t };
        if (m.clock !== null) this.clock = { value: m.clock, at: t };
        if (this.inDraft(m.overall) && !this.turnAt.has(m.overall) && !this.picks.has(m.overall)) {
          this.turnAt.set(m.overall, t);
          const start = {
            type: "turn_start",
            t,
            overall: m.overall,
            slot,
            clock_s: m.clock,
            teams: this.teamsSeen(), // null until the room shows it
          };
          if (m.team !== slot) start.team = m.team; // a league room: Yahoo's team id
          // Whether the room puts keeper slots on the clock is to be seen on the night.
          if (this.isKeeper(m.overall)) start.keeper = true;
          this.outbox.push(start);
        }
        if (slot !== null && slot === this.slot && this.isMine(m.overall) && !this.picks.has(m.overall)) out.turn = m.overall;
      } else if (m.kind === "clock") {
        this.clock = { value: m.clock, at: t };
      } else if (m.kind === "auto" && this.slot !== null && this.seatOf(m.team) === this.slot) {
        const d = this.onDeck;
        const k = d && d.slot === this.slot && !this.picks.has(d.overall) ? d.overall : this.nextMine();
        if (k !== null) this.yahooMade.add(k);
      }
      if (this.slot !== mine) out.seat = this.slot;
      return out;
    }

    /** The R| frame: every team's position when its entries check out (protocol.orderSeats). */
    fromOrder(order, t) {
      const r = P.orderSeats(order, this.rounds);
      this.order = r.error ? { entries: order.length, error: r.error } : { entries: order.length, teams: r.teams };
      if (!r.error) for (const [team, pos] of r.seats) this.learn(team, pos, "order", t);
    }

    add(overall, yid, team, t, src) {
      const slot = this.seatOf(team);
      this.own(overall, slot);
      if (!this.inDraft(overall) || this.picks.has(overall)) return false; // never sent past the end
      this.picks.set(overall, { overall, yid: String(yid), team, slot, t, src });
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

    /** The backstop queued ``yid``, the player of the user's request that failed, first for
     * ``overall``: if Yahoo takes that player there, the pick is the user's (#26). */
    noteRequested(overall, yid) {
      this.requested.set(overall, String(yid));
    }

    /** How a pick of mine landed, as far as the room shows it: the user's trusted click, then
     * Yahoo's history frame (the tab was not in the room when it was made), then the player of
     * the user's failed request taken from the backstop's queue (the user's pick), then
     * Yahoo's own pick (announced by 5|slot; ``autodraft`` is Yahoo's Autodraft switch at
     * landing time), then the extension's attempt, then the switch alone (with Autodraft on,
     * Yahoo picks the moment the turn starts and sends no 5|slot), else "unknown". */
    how(overall, { autodraft = false } = {}) {
      if (this.isManual(overall)) return "manual";
      const p = this.picks.get(overall);
      if (p && p.src === "history") return "history";
      if (p && this.requested.get(overall) === p.yid) return "manual";
      if (this.yahooMade.has(overall)) return autodraft ? "autopick" : "expiry";
      if (this.attempts.has(overall)) return this.attempts.get(overall);
      return autodraft ? "autopick" : "unknown";
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

    /** The pick_landed event: every pick of mine gets one, so D2 and the labels see it; one
     * from the history frame says how "history", and D2 leaves it out. */
    landedEvent(rec, context) {
      return { type: "pick_landed", ...rec, how: this.how(rec.overall, context) };
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
        team_id: this.teamId,
        seat_src: this.seatSource,
        num_teams: this.numTeams,
        room_teams: this.teamsSeen(),
        order_len: this.orderLen,
        order: this.order,
        rounds: this.rounds,
        keepers: [...this.keepers].sort((a, b) => a - b),
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
