// Yahoo draft-room protocol and snake-draft arithmetic. Pure functions, no DOM and no chrome.*:
// loaded as a classic script by the content script and the service worker (as
// globalThis.PickAndRoll) and by node's test runner (as a CommonJS module).
//
// Room socket messages (text frames, "|"-separated):
//   0|overall|yahooId|slot|pos|0      a pick
//   P|1=yahooId,slot,0|2=...|         every pick so far, sent once on connect
//   D|overall|slot|clock              a pick goes on the clock (slot = its owner)
//   C|clock                           the clock, seconds left
//   X|n, then 5|slot                  Yahoo is about to make the pick for that slot itself
//                                     (expiry, or the seat is on Autodraft)
//   R|...                             the draft order
// Outgoing, the client's hello is 8|<league>|<slot>|<user agent>|...; only the slot is kept.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DRAFT_PATH = /\/draftclient\/(?:[a-z]+\/)?([A-Za-z0-9_.-]{1,64})\/(\d{1,2})\/?$/;

  /** {draft_id, slot} from a draft-client path such as /draftclient/nba/2515267/1. */
  function roomFromPath(pathname) {
    const m = DRAFT_PATH.exec(pathname || "");
    if (!m) return null;
    const slot = Number(m[2]);
    return slot >= 1 ? { draft_id: m[1], slot } : null;
  }

  const int = (s) => (/^\d+$/.test(s) ? Number(s) : null);

  /** One socket frame as a record, or null for frames the extension does not use. */
  function parseMessage(text) {
    if (typeof text !== "string" || text.length < 2 || text[1] !== "|") return null;
    const f = text.split("|");
    switch (f[0]) {
      case "0": {
        const overall = int(f[1]);
        const yid = int(f[2]);
        const slot = int(f[3]);
        if (!overall || !yid || !slot) return null;
        return { kind: "pick", overall, yid: String(yid), slot, pos: f[4] || "" };
      }
      case "P": {
        const picks = [];
        for (const seg of f.slice(1)) {
          const m = /^(\d+)=(\d+),(\d+)/.exec(seg);
          if (m) picks.push({ overall: Number(m[1]), yid: m[2], slot: Number(m[3]) });
        }
        return { kind: "history", picks };
      }
      case "D": {
        const overall = int(f[1]);
        const slot = int(f[2]);
        if (!overall || !slot) return null;
        return { kind: "on_deck", overall, slot, clock: int(f[3]) };
      }
      case "C": {
        const clock = int(f[1]);
        return clock === null ? null : { kind: "clock", clock };
      }
      case "X":
        return { kind: "auto_warn", value: int(f[1] || "") };
      case "5": {
        const slot = int(f[1] || "");
        return slot ? { kind: "auto", slot } : null;
      }
      case "R":
        return { kind: "order", order: f.slice(1).filter(Boolean) };
      default:
        return null;
    }
  }

  /** The slot from the client's hello frame (8|league|slot|...), else null. */
  function parseHello(text) {
    if (typeof text !== "string" || !text.startsWith("8|")) return null;
    const slot = int(text.split("|")[2] || "");
    return slot && slot <= 20 ? slot : null;
  }

  /** Overall picks owned by draft position ``slot`` (1-based) in a snake draft. */
  function snakePicks(numTeams, slot, rounds) {
    if (!(slot >= 1 && slot <= numTeams)) throw new RangeError("slot must be in 1..numTeams");
    const out = [];
    for (let r = 1; r <= rounds; r++) {
      out.push((r - 1) * numTeams + (r % 2 === 1 ? slot : numTeams - slot + 1));
    }
    return out;
  }

  /** {round, slot} that owns an overall pick in a snake draft. */
  function pickOwner(numTeams, overall) {
    if (!(overall >= 1)) throw new RangeError("overall must be positive");
    const round = Math.floor((overall - 1) / numTeams);
    const idx = (overall - 1) % numTeams;
    return { round: round + 1, slot: round % 2 === 0 ? idx + 1 : numTeams - idx };
  }

  return { roomFromPath, parseMessage, parseHello, snakePicks, pickOwner };
});
