// Yahoo draft-room protocol and snake-draft arithmetic. Pure functions, no DOM and no chrome.*:
// loaded as a classic script by the content script and the service worker (as
// globalThis.PickAndRoll) and by node's test runner (as a CommonJS module).
//
// Room socket messages (text frames, "|"-separated). ``team`` is the Yahoo team id, which is
// the draft position only in mock rooms (the mock lobby numbers its teams by seat); in a league
// room team 10 can pick 1st (league 222017, 2026-10-11). The draft path ends in it too.
//   0|overall|yahooId|team|pos|0      a pick
//   P|1=yahooId,team,0|2=...|         every pick so far, sent once on connect
//   D|overall|team|clock              a pick goes on the clock (team = its owner)
//   C|clock                           the clock, seconds left
//   X|n, then 5|team                  Yahoo is about to make the pick for that team itself
//                                     (expiry, or the seat is on Autodraft)
//   R|team|team|...|                  the draft order: the team id on each overall pick, in snake
//                                     order with the league's traded picks moved (league 31822,
//                                     2026-10-14: ten of them), ~100 ms after entry (league
//                                     222017: 130 entries); checked before use (orderSeats)
// Seen in a league room and not used: A| (autopick flags per team id) and w|7200|30 at entry,
// H|S|60|0|0|<state> (0 before, 1 during, 2 after the draft), J| and L| (presence),
// O|draft-labels|<overall>|<json> on my own turns, and C| counting down to the draft every 6 s.
// Outgoing, the client's hello is 8|<league>|<team>|<user agent>|...; only the team is kept.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.PickAndRoll = Object.assign(root.PickAndRoll || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DRAFT_PATH = /\/draftclient\/(?:[a-z]+\/)?([A-Za-z0-9_.-]{1,64})\/(\d{1,2})\/?$/;

  /** {draft_id, team} from a draft-client path such as /draftclient/nba/2515267/1: the last
   * number is my Yahoo team id, not my draft position (equal only in mock rooms). */
  function roomFromPath(pathname) {
    const m = DRAFT_PATH.exec(pathname || "");
    if (!m) return null;
    const team = Number(m[2]);
    return team >= 1 ? { draft_id: m[1], team } : null;
  }

  /** My draft position from the tab title "You pick 1st | Live NBA Draft", else null. Before
   * pick 1 it reads the same whether Yahoo means my seat, my next overall or the picks to go;
   * the tracker takes it only then. Any other title ("YOUR TURN, DRAFT NOW") is null. */
  function titlePosition(title) {
    const m = /\byou pick (\d{1,2})(?:st|nd|rd|th)\b/i.exec(title || "");
    const n = m ? Number(m[1]) : 0;
    return n >= 1 && n <= 20 ? n : null;
  }

  /** The draft order behind the R| frame's entries, read as the team id on each overall pick:
   * {teams, seats: [[team, position], ...], owners: [team, ...], traded} when the frame
   * checks out, else {error}. It checks out when every entry is an integer, there are
   * teams x ``rounds`` of them with teams in 2..20 (as many distinct teams), and every team
   * has a settled draft position: the snake slot most of its picks fall on (a traded pick is
   * the odd one out), the positions a permutation of 1..teams. A round may repeat a team
   * (traded picks); ``traded`` counts the entries on another position's snake slot, and
   * ``owners`` is the frame itself as numbers. */
  function orderSeats(order, rounds) {
    const n = Array.isArray(order) ? order.length : 0;
    if (!n || !(rounds >= 1) || n % rounds) return { error: `${n} entries for ${rounds} rounds` };
    const teams = n / rounds;
    if (teams < 2 || teams > 20) return { error: `${teams} teams` };
    if (!order.every((e) => /^\d{1,6}$/.test(String(e)))) return { error: "not all integers" };
    const ids = order.map(Number);
    const distinct = new Set(ids).size;
    if (distinct !== teams) return { error: `${distinct} teams in ${teams} x ${rounds} entries` };
    const tally = new Map(); // team -> Map(snake slot -> picks on it)
    ids.forEach((team, i) => {
      const slot = pickOwner(teams, i + 1).slot;
      if (!tally.has(team)) tally.set(team, new Map());
      tally.get(team).set(slot, (tally.get(team).get(slot) || 0) + 1);
    });
    const seats = [];
    const byPos = new Map();
    for (const [team, slots] of tally) {
      const most = Math.max(...slots.values());
      const top = [...slots].filter(([, c]) => c === most).map(([slot]) => slot);
      if (top.length !== 1) return { error: `team ${team} has no settled position` };
      if (byPos.has(top[0])) return { error: `position ${top[0]} is held by two teams` };
      byPos.set(top[0], team);
      seats.push([team, top[0]]);
    }
    seats.sort((a, b) => a[1] - b[1]);
    const posOf = new Map(seats);
    const traded = ids.filter((team, i) => posOf.get(team) !== pickOwner(teams, i + 1).slot).length;
    return { teams, seats, owners: ids, traded };
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
        const team = int(f[3]);
        if (!overall || !yid || !team) return null;
        return { kind: "pick", overall, yid: String(yid), team, pos: f[4] || "" };
      }
      case "P": {
        const picks = [];
        for (const seg of f.slice(1)) {
          const m = /^(\d+)=(\d+),(\d+)/.exec(seg);
          if (m) picks.push({ overall: Number(m[1]), yid: m[2], team: Number(m[3]) });
        }
        return { kind: "history", picks };
      }
      case "D": {
        const overall = int(f[1]);
        const team = int(f[2]);
        if (!overall || !team) return null;
        return { kind: "on_deck", overall, team, clock: int(f[3]) };
      }
      case "C": {
        const clock = int(f[1]);
        return clock === null ? null : { kind: "clock", clock };
      }
      case "X":
        return { kind: "auto_warn", value: int(f[1] || "") };
      case "5": {
        const team = int(f[1] || "");
        return team ? { kind: "auto", team } : null;
      }
      case "R":
        return { kind: "order", order: f.slice(1).filter(Boolean) };
      default:
        return null;
    }
  }

  /** The team id from the client's hello frame (8|league|team|...), else null. */
  function parseHello(text) {
    if (typeof text !== "string" || !text.startsWith("8|")) return null;
    const team = int(text.split("|")[2] || "");
    return team && team <= 20 ? team : null;
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

  return { roomFromPath, titlePosition, orderSeats, parseMessage, parseHello, snakePicks, pickOwner };
});
