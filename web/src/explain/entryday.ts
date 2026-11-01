// One queued entry's day (#286): queued at the morning build, the veto window, due at the
// execute time, the page check and the claim at the morning pass, cleared at Yahoo's run and
// read by the next daily; the user's strike (the bid alone, or the whole entry) changes what the
// gates say. The times are an example weekday's; the rules are season/autopilot.py's
// (executes_at, due, effective_bid). No React, so the test runs under Node.
import { M } from "./lane.ts";

/** 0 kept, 1 the bid struck at 07:30, 2 the entry struck at 07:30. */
export type Strike = 0 | 1 | 2;

export const STRIKES: { id: Strike; label: string }[] = [
  { id: 0, label: "bid kept" },
  { id: 1, label: "bid struck at 07:30" },
  { id: 2, label: "entry struck at 07:30" },
];

/** From 05:00 to 06:00 the next day, played in 40 s. */
export const ENTRY_MIN = M(5);
export const ENTRY_MAX = M(30);
export const ENTRY_SECONDS = 40;

/** The example day's instants, minutes from midnight (past 1440 is the next day). */
export const T = {
  queued: M(5, 40),
  hour: M(6, 40),
  strike: M(7, 30),
  exec: M(9),
  pass: M(9, 15),
  late: M(15),
  build: M(21),
  evening: M(22, 40),
  stop: M(22, 58),
  run: M(28),
  read: M(29),
};

export const ENTRY_EVENTS: number[] = [...new Set(Object.values(T))].sort((a, b) => a - b);

/** One node of the chain: the state's name, the example time it is reached, a note under it. */
export interface EntryNode {
  name: string;
  at: string;
  note?: string;
}

/** The chain's nodes, in order. */
export const ENTRY_NODES: EntryNode[] = [
  { name: "queued", at: "05:40" },
  { name: "veto window", at: "to 09:00" },
  { name: "due", at: "09:00" },
  { name: "page check", at: "09:15" },
  { name: "claimed", at: "09:15" },
  { name: "cleared", at: "04:00", note: "+1 day" },
  { name: "read", at: "05:00", note: "+1 day" },
];

/** The clock's reading; past midnight it says so. */
export function entryHhmm(t: number): string {
  const h = String(Math.floor(t / 60) % 24).padStart(2, "0");
  const m = String(Math.round(t) % 60).padStart(2, "0");
  return `${t >= 1440 ? "next day " : ""}${h}:${m}`;
}

export interface EntryState {
  /** The chain's current node (−1 before the entry exists). */
  cur: number;
  /** The entry was struck: it stays in the veto window and never claims. */
  dead: boolean;
}

export function entryState(t: number, strike: Strike): EntryState {
  if (t < T.queued) return { cur: -1, dead: false };
  if (strike === 2 && t >= T.strike) return { cur: 1, dead: true };
  if (t < T.exec) return { cur: 1, dead: false };
  if (t < T.pass) return { cur: 2, dead: false };
  if (t < T.run) return { cur: 4, dead: false };
  if (t < T.read) return { cur: 5, dead: false };
  return { cur: 6, dead: false };
}

/** A gate's state at the marker: passed, blocking, or not yet asked. */
export type GateKind = "ok" | "no" | "off";

export interface Gate {
  k: GateKind;
  text: string;
}

/** The seven gates at `t`, each with its words. */
export function entryGates(t: number, strike: Strike): Gate[] {
  const dead = strike === 2 && t >= T.strike;
  const g = (k: GateKind, text: string): Gate => ({ k, text });
  const bid = strike === 1 ? 0 : 3;
  const struck =
    strike === 0
      ? g(t < T.queued ? "off" : "ok", "not struck by the user")
      : t < T.strike
        ? g(t < T.queued ? "off" : "ok", "not struck by the user (yet)")
        : strike === 1
          ? g("ok", "the bid struck at 07:30: the entry stands as a $0 claim")
          : g("no", "the entry struck at 07:30: no claim; the rebuild keeps it struck by id");
  return [
    g(t < T.queued ? "off" : "ok", "queued by the daily build at 05:40"),
    t < T.queued ? g("off", "an hour after queueing (06:40)") : t < T.hour ? g("no", "not before an hour after queueing (06:40): the veto window") : g("ok", "an hour after queueing: 06:40 passed"),
    t < T.queued ? g("off", "the day's execute time (09:00)") : t < T.exec ? g("no", "not before the day's execute time (09:00; 07:00 by default)") : g("ok", "the day's execute time 09:00 passed"),
    struck,
    dead
      ? g("off", "a pass opens the add page: not for a struck entry")
      : t < T.pass
        ? g(t < T.exec ? "off" : "no", "a pass opens the add page: the next is 09:15")
        : g("ok", "the 09:15 pass opened the page: available · drop on the roster · under the cap · not struck · one live run a league"),
    dead
      ? g("off", "claimed")
      : t < T.pass
        ? g("off", `claimed at $${bid}, to land at Yahoo's early-morning run on the clear date`)
        : t < T.build
          ? g("ok", `claimed at $${bid}; lands at Yahoo's early-morning run on the clear date`)
          : g("ok", `claimed at $${bid}; the 21:00 rebuild keeps an executed entry by id`),
    dead
      ? g("off", "Yahoo's run and the daily's read")
      : t < T.run
        ? g("off", "Yahoo's run at 04:00 decides it; the 05:00 daily reads won or lost from the transactions")
        : t < T.read
          ? g("ok", "Yahoo's run at 04:00: the claim cleared; the paired drop takes effect now")
          : g("ok", "the 05:00 daily read the transaction: won; the adds left this week count it"),
  ];
}

/** Words wrapped into lines of at most `max` characters (a longer word stands alone). */
export function wrap(text: string, max: number): string[] {
  const out: string[] = [];
  let line = "";
  for (const w of text.split(" ")) {
    const next = (line + " " + w).trim();
    if (next.length > max && line) {
      out.push(line);
      line = w;
    } else line = next;
  }
  if (line) out.push(line);
  return out;
}
