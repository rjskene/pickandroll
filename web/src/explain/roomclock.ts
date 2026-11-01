// One armed turn on the 30 s pick clock (#284): the plan solve, the pricing, the drafter's
// wait, the act-at hold, the click, the queue backstop and Yahoo's autopick at zero, as lanes
// on one axis of seconds into the turn. The 30 s clock is the design point. The plan budget
// (the clock less 13 s of margin and 12 s of pricing, 5 s at least) is the API's
// (docs/YAHOO_SYNC.md); the wait's 12 s line, the re-click at 1.8 s and 2.5 s, the 6 s
// backstop and the last look at 2 s are the extension's (extension/lib/drafter.js); the
// landing times are the mocks' typical ones. No React, so the test runs under Node.
import type { Lane, Seg } from "./lane.ts";
import type { Tick } from "./Lanes";

/** Whether this board's branch was solved ahead (a hit) or is solved cold at the turn. */
export type Board = "hit" | "cold";
/** Seconds left at which an armed turn acts; 0 is "not set", act at once. */
export type Act = 0 | 15;
/** Whether the candidate's row is on the page, the top four are missing, or no row at all. */
export type Row = "found" | "top4" | "none";

export const RC_END = 30;
/** Seconds into the turn at which a hit's plan arrives (the wait's round trip). */
export const RC_HIT_S = 0.5;
/** The cold board's plan budget, then its pricing, on a 30 s clock. */
export const RC_PLAN_S = 5;
export const RC_PRICE_S = 12;
/** The wait stops with this much clock left (the extension's START_BY_S). */
export const RC_START_BY_S = 12;
/** The queue backstop fires with this much clock left; the last look is at 2 s left. */
export const RC_BACKSTOP_BY_S = 6;
export const RC_LAST_LOOK_S = 2;
/** A clean click lands in about this long (turn-to-land, the mocks' typical). */
export const RC_LAND_S = 1.5;

/** The clock's reading: seconds left. */
export function rcLeft(t: number): string {
  return `${(RC_END - t).toFixed(1).replace(/\.0$/, "")} s left`;
}

export function rcTicks(phone: boolean): Tick[] {
  const out: Tick[] = [];
  for (let s = 0; s <= RC_END; s += phone ? 10 : 5) out.push({ v: s, l: `${RC_END - s} s` });
  return out;
}

/** The turn's lanes for one board, one act-at setting and one state of the row. */
export function rcLanes(board: Board, act: Act, row: Row): Lane[] {
  const reco = board === "hit" ? RC_HIT_S : RC_PLAN_S + RC_PRICE_S;
  const cap = act ? RC_END - act : RC_END - RC_START_BY_S;
  const waitEnd = Math.min(reco, cap);
  const fresh = reco <= cap;
  const click = act ? Math.max(waitEnd, RC_END - act) : waitEnd;
  const land = click + RC_LAND_S;
  const backstop = RC_END - RC_BACKSTOP_BY_S;
  const last = RC_END - RC_LAST_LOOK_S;
  const found = row === "found";
  const none = row === "none";

  const plan: Seg[] =
    board === "hit"
      ? [{ a: 0, b: RC_END, k: "after", l: "a hit: the branch for this board converged before the turn, solved ahead while the picks before mine landed" }]
      : [
          { a: 0, b: RC_PLAN_S, k: "run", l: "solving the board cold: 3 candidates, no scenarios; the budget is the clock less the drafter's 13 s margin and 12 s of pricing, 5 s at least" },
          { a: RC_PLAN_S, b: RC_END, k: "after", l: `budget spent at ${RC_END - RC_PLAN_S} s left: a converged plan, or its time-limited incumbent` },
        ];
  const pricing: Seg[] =
    board === "hit"
      ? [{ a: 0, b: RC_END, k: "after", l: "priced before the turn, with the plan" }]
      : [
          { a: 0, b: RC_PLAN_S, k: "idle", l: "waits for the plan" },
          { a: RC_PLAN_S, b: reco, k: "run", l: "each candidate forced to be the pick and the objective lost measured: the price" },
          { a: reco, b: RC_END, k: "after", l: `priced: the recommendation is fresh with ${RC_END - reco} s left` },
        ];
  const wait: Seg[] = [
    { a: 0, b: waitEnd, k: "open", l: "holding GET /plan?wait for this board's solve" + (act ? " until act time" : `; stops by ${RC_START_BY_S} s left`) },
    {
      a: waitEnd,
      b: RC_END,
      k: "after",
      l: fresh ? `a fresh plan arrived with ${rcLeft(reco)}` : "the wait ran out: the turn acts on the newest plan it holds, the one fetched ahead, fresh only for the board before this pick",
    },
  ];
  const hold: Seg[] = act
    ? reco < RC_END - act
      ? [
          { a: 0, b: reco, k: "idle", l: "waits for the plan" },
          { a: reco, b: click, k: "block", l: `held until ${act} s left so the user may pick first, by hand or by "Draft in Yahoo"; either ends the turn` },
          { a: click, b: RC_END, k: "after", l: `released at ${act} s left` },
        ]
      : [
          { a: 0, b: click, k: "idle", l: "no hold needed: the plan wait itself ran to act time" },
          { a: click, b: RC_END, k: "after", l: `act time, ${act} s left` },
        ]
    : [{ a: 0, b: RC_END, k: "idle", l: "act-at not set: the turn clicks as soon as it has a plan" }];
  const clickSegs: Seg[] = ([{ a: 0, b: click, k: "idle", l: "waits" }] as Seg[]).concat(
    found
      ? [
          { a: click, b: land, k: "run", l: "Draft clicked on the first candidate's row; Yahoo drops a click that lands during a re-render, so the same row again at 1.8 s and 2.5 s" },
          { a: land, b: RC_END, k: "done", l: "the pick is in: Yahoo confirms a registered click in about 400 ms; turn-to-land 1.3 to 1.6 s clean" },
        ]
      : none
        ? [
            { a: click, b: last, k: "run", l: `no candidate has a row: Yahoo's Players tab selected again and the view reset every 2 s, looking until ${RC_LAST_LOOK_S} s left` },
            { a: last, b: RC_END, k: "block", l: "nothing to click or queue" },
          ]
        : [
            { a: click, b: backstop, k: "run", l: "no row for the top four: find-only passes over the plan's candidates in priced order, the view reset every 2 s" },
            { a: backstop, b: RC_END, k: "after", l: `the backstop took over at ${RC_BACKSTOP_BY_S} s left` },
          ],
  );
  const queue: Seg[] = found
    ? [{ a: 0, b: RC_END, k: "idle", l: `not needed: the pick landed before ${RC_BACKSTOP_BY_S} s left` }]
    : none
      ? [
          { a: 0, b: backstop, k: "idle", l: `waits for ${RC_BACKSTOP_BY_S} s left` },
          { a: backstop, b: last, k: "open", l: `looking for any candidate's row to queue, until ${RC_LAST_LOOK_S} s left` },
          { a: last, b: RC_END, k: "block", l: "no row to queue" },
        ]
      : [
          { a: 0, b: backstop, k: "idle", l: `waits for ${RC_BACKSTOP_BY_S} s left` },
          { a: backstop, b: backstop + 0.6, k: "run", l: "the best remaining candidate alone in Yahoo's queue, Autodraft on" },
          { a: backstop + 0.6, b: RC_END, k: "done", l: "Yahoo takes the queue's head; after the turn Autodraft goes off and the queue is emptied" },
        ];
  const autopick: Seg[] = none
    ? [
        { a: 0, b: last, k: "idle", l: "Yahoo picks only when the clock runs out" },
        { a: last, b: RC_END, k: "block", w: "at zero", l: "no pick by zero: Yahoo picks for the seat from its own ranking, and a second missed turn flips the seat into autopick mode, turned off only by hand" },
      ]
    : [{ a: 0, b: RC_END, k: "idle", l: "moot: the pick is in before the clock runs out" }];

  return [
    { name: "plan solve", sub: `budget ${RC_PLAN_S} s on a ${RC_END} s clock`, segs: plan },
    { name: "pricing", sub: `${RC_PRICE_S} s: each candidate forced first`, segs: pricing },
    { name: "the drafter's wait", sub: act ? "holds the plan route until act time" : `holds the plan route, to ${RC_START_BY_S} s left at the latest`, marks: [{ at: cap, k: "tick" }], segs: wait },
    { name: "act-at hold", sub: act ? `acts at ${act} s left` : "not set: acts at once", segs: hold },
    { name: "the click", sub: "the candidate's Draft button", segs: clickSegs },
    { name: "queue backstop", sub: `by ${RC_BACKSTOP_BY_S} s left, for this pick only`, marks: [{ at: backstop, k: "stop" }], segs: queue },
    { name: "Yahoo's autopick", sub: "at zero", marks: [{ at: RC_END, k: "stop" }], segs: autopick },
  ];
}
