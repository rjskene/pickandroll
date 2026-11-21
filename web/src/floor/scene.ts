// The floor at a moment (FLOOR PR 4, #461): where every agent, entry, lamp and gate stands, and
// what each label says, from the PR 3 timeline and a clock. Pure, so the floor's SVG only draws
// what this returns and the test runs under Node. The geometry is the approved mock-up's
// (`floor-final.html`, a 1280 by 612 stage): the week strip on top, the moves engine and the
// Solver's rail on the left, the belt through the queue's seven rules to the execute-time gate,
// the lanes out to a dock a league, the rack, the Sources room and the ledger along the bottom.

import type { QueueRules } from "../api.ts";
import { AGENTS, BELT, SIGNS, centralDate, entryState, floorAt } from "./model.ts";
import type { Agent, EntryState, FloorEntry, FloorRun, FloorStep, FloorUnit, Timeline } from "./model.ts";

// ---------------------------------------------------------------- the geometry
export const W = 1280;
export const H = 612;
export const HUB = { x: 262, y: 250 };
/** The execute-time gate, where the belt ends and the lanes fan out. */
export const GATE = { x: 850, y: 250 };
export const BELT_Y = 250;
export const DOCK_X = 1046;
export const RACK_X = 888;
export const RAIL_Y = 374;
export const ROOM = { rest: 36, y: 526, line: 556, up: 540, over: 424, gx: 868, ledger: 552 };
/** The x of the belt's rule ``k``. */
export const gateX = (k: number) => 344 + k * 66;
/** The stations of the Sources room: a pellet a report, a league or a read. */
export const SITES = [
  { key: "bbm", name: "Basketball Monster", sub: "projections: five exports a day", x0: 56, px: (i: number) => 76 + i * 26 },
  { key: "espn", name: "ESPN", sub: "schedule, injuries, box scores", x0: 232, px: (i: number) => 252 + i * 36 },
  { key: "yahoo", name: "Yahoo Fantasy", sub: "league pages, team pages, claims", x0: 374, px: (i: number) => 384 + i * 15 },
] as const;
export type SiteKey = (typeof SITES)[number]["key"];

/** The flow from the reads to the leagues: a caption a stage and where its number sits on the floor. */
export const FLOW: { title: string; lines: [string, string, string]; at: [number, number] }[] = [
  { title: "Reads", lines: ["Scout saves the exports and", "reads each league's pages. A", "read league's lamp is outlined."], at: [94, 445] },
  { title: "Solve", lines: ["Each league is solved. The", "Solver carries the keep rule", "and season guard into each."], at: [192, RAIL_Y] },
  { title: "Queue build", lines: ["The orchestrator reads the", "logged sets, never solves,", "and sizes each claim's bid."], at: [HUB.x - 31, HUB.y - 29] },
  { title: "Rules", lines: ["Each entry meets the queue's", "rules in order. The first to", "fail holds it in the bay below."], at: [gateX(0) - 27, BELT_Y + 22] },
  { title: "Veto window", lines: ["What passes is queued and", "waits. You can strike it or", "its bid until execute time."], at: [GATE.x - 42, BELT_Y - 19] },
  { title: "Execute time", lines: ["A gate, not a trigger: the", "next pass after it (09:15,", "15:00, 22:40) takes it."], at: [GATE.x + 30, BELT_Y - 50] },
  { title: "Out and back", lines: ["The Mover opens the add", "page, re-checks it, places", "the claim. Results fly back."], at: [GATE.x + 52, BELT_Y + 18] },
];

/** The Explain step each stage's number opens (the hash Explain reads). */
export const FLOW_EXPLAIN: { track: "moves" | "daily"; step: string }[] = [
  { track: "daily", step: "daily" },
  { track: "moves", step: "weekly-odds" },
  { track: "daily", step: "build" },
  { track: "moves", step: "keep-rule" },
  { track: "daily", step: "execute" },
  { track: "daily", step: "execute" },
  { track: "daily", step: "morning" },
];

/** The glossary term each stage's title opens (Explain, #462). */
export const FLOW_TERMS = ["reads", "solve", "queue-build", "rules", "veto-window", "execute-time", "out-and-back"] as const;

/** The rack's agents, top down: the Scout lives in the Sources room, the Solver on its rail. */
export const RACK: Agent[] = ["setter", "starter", "mover"];
export const rackY = (i: number) => 326 + i * 33;

const clamp = (v: number, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
const ease = (p: number) => {
  const q = clamp(p);
  return q * q * (3 - 2 * q);
};
const bez = (a: number, b: number, c: number, d: number, t: number) => {
  const u = 1 - t;
  return u * u * u * a + 3 * u * u * t * b + 3 * u * t * t * c + t * t * t * d;
};
/** The jaw of an agent at work: it chews. */
export const chomp = (now: number) => 0.5 + 0.5 * Math.sin(now * 17);
const last = (name: string) => {
  const p = name.split(" ");
  return p.length > 1 && /^(Jr\.|Sr\.|III|II|IV)$/.test(p[p.length - 1]) ? p.slice(-2).join(" ") : p[p.length - 1];
};

/** A lane out of the gate to a dock: a bezier from the gate to ``(x1, y)``. */
export function lanePath(y: number, x1: number): string {
  return `M${GATE.x},${GATE.y} C${GATE.x + 112},${GATE.y} ${x1 - 112},${y} ${x1},${y}`;
}
const lanePoint = (y: number, x1: number, t: number) => ({ x: bez(GATE.x, GATE.x + 112, x1 - 112, x1, t), y: bez(GATE.y, GATE.y, y, y, t) });

// ---------------------------------------------------------------- the inputs
export interface LeagueRow {
  league: string;
  /** The private league: suggestions only, nothing clicks there. */
  mine: boolean;
  adds: { used: number; limit: number | null } | null;
  budget: number | null;
}

export interface SceneInput {
  tl: Timeline;
  /** The moment, epoch milliseconds. */
  t: number;
  /** Seconds of play since an instant (the Demo's bent clock), or real seconds when live. */
  age: (at: number) => number;
  /** Frame time in seconds, for the chewing and the belt's dashes; constant under reduced motion. */
  now: number;
  leagues: LeagueRow[];
  /** One league's floor, or all of them. */
  one: string | null;
  /** The execute time in force on the moment's day, ``HH:MM``. */
  executeTime: string;
  /** One league's roster, a slot each: as read (live), or as the week began, the claims landing
   * on it as they land (the Demo, with ``claims``). */
  roster?: { slot: string; name: string | null }[] | null;
  claims?: boolean;
}

export interface Tile {
  slot: string;
  name: string | null;
  state: "" | "new" | "target";
}

/** One league's roster at ``t``: each claim that landed puts its add in its drop's slot (or the
 * first open one), lit for a moment; a claim under way marks the slot it targets. */
export function rosterAt(
  base: { slot: string; name: string | null }[],
  entries: FloorEntry[],
  t: number,
  age: SceneInput["age"],
  pass: ReturnType<typeof floorAt>["pass"],
  unit: ReturnType<typeof floorAt>["unit"] = null,
): Tile[] {
  const tiles: Tile[] = base.map((b) => ({ slot: b.slot, name: b.name, state: "" }));
  const mine = entries.filter((e) => e.queued && (e.outcome === "claimed" || e.outcome === "added") && e.outcomeAt !== null).sort((a, b) => (a.outcomeAt ?? 0) - (b.outcomeAt ?? 0));
  for (const e of mine) {
    const k = tiles.findIndex((x) => (e.dropName ? x.name === e.dropName : x.name === null) && !/^IL/.test(x.slot));
    if (k < 0) continue;
    const s = entryState(e, t, pass, unit);
    if (s === "claimed" || s === "added") {
      tiles[k].name = e.addName;
      tiles[k].state = age(e.outcomeAt ?? t) < 1.6 ? "new" : "";
    } else if (s === "doing") tiles[k].state = "target";
  }
  return tiles;
}

// ---------------------------------------------------------------- the scene
export type LampState = "" | "read" | "solved" | "solving";
export type PelletState = "todo" | "doing" | "done" | "skipped";

export interface TokenView {
  id: string;
  x: number;
  y: number;
  k: number;
  state: EntryState;
  /** The share of a claim done, while it is under way. */
  p: number;
  title: string;
  label: { x: number; y: number; anchor: "start" | "middle"; text: string; sub: string; hot: boolean } | null;
}

export interface Scene {
  days: { date: string; label: string; on: boolean; tally: { claimed: number; held: number; failed: number; skipped: number }; pips: { title: string; state: PelletState }[] }[];
  lamps: { league: string; x: number; y: number; state: LampState; off: boolean }[];
  rail: PelletState[];
  solver: { x: number; open: number; alpha: number; signs: ("" | "on" | "hot")[]; key: boolean[]; text: string };
  hub: { spin: number; building: boolean; n: number; text: string };
  gates: { key: string; tag: string; knob: string; title: string; x: number; up: number; open: number; hot: boolean }[];
  stage: number;
  gate: { open: number; face: string; veto: string };
  lanes: { key: string; y: number; x1: number; hot: number; color: Agent | null }[];
  docks: { league: string; y: number; mine: boolean; pips: boolean[]; budget: string; res: string; cls: string }[];
  /** One league: its card and the other leagues' line. */
  court: { league: string; mine: boolean; sub: string; res: string; cls: string; tiles: Tile[]; other: { res: string; cls: string } } | null;
  tokens: TokenView[];
  chips: { x: number; y: number; outcome: string }[];
  agents: { role: Agent; x: number; y: number; open: number; alpha: number; rackY: number }[];
  scout: { x: number; open: number; alpha: number; flip: boolean; label: string; on: SiteKey | null; pellets: Record<SiteKey, PelletState[]>; pulses: [number, number][] };
  steps3: { x: number; y: number; done: boolean }[];
  sub: { x: number; y: number; text: string } | null;
  ledger: { at: string; cls: string; text: string }[];
  now: NowPanel;
}

export interface NowPanel {
  /** The run under way, or the next timer at rest. */
  title: string;
  agent: Agent | null;
  when: string;
  line: string;
  steps: { name: string; agent: Agent; state: PelletState | "running"; detail: string }[];
  unit: { big: string; sub: string; p: number } | null;
}

const OUT_KEYS: Record<string, string> = { claimed: "claimed", failed: "failed", skipped: "skipped", gone: "failed", added: "claimed", would_claim: "skipped" };
const MARK: Record<string, string> = { claimed: "✓", added: "✓", failed: "✕", gone: "✕", skipped: "»", would_claim: "»" };
const SUBS = ["opening the add page", "checking the claim form", "placing the claim"];
const READS: Record<string, string> = { exports: "saving the exports", browser: "checking the sign-in", claim_page: "reading the claims back", fresh_reads: "fresh read of" };
const UNIT_TEXT: Record<string, string> = {
  refresh: "pages read",
  private_pages: "pages read",
  lineup_pages: "pages read",
  fresh_reads: "team page read",
  solve: "solved",
  resolve: "solved again",
  resolve_comebacks: "solved again",
  lineup: "lineup set",
  start_active: "Start Active pressed",
  placed_il: "IL move made",
  comebacks: "comeback moved",
};

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** ``YYYY-MM-DD`` moved ``n`` days. */
const addDays = (date: string, n: number) => new Date(Date.parse(`${date}T12:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
const weekday = (date: string) => new Date(Date.parse(`${date}T12:00:00Z`)).getUTCDay();
export const dayLabel = (date: string) => `${DAY_NAMES[weekday(date)]} ${MONTHS[Number(date.slice(5, 7)) - 1]} ${Number(date.slice(8, 10))}`;

const HM = new Intl.DateTimeFormat("en-US", { timeZone: "America/Chicago", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
/** ``HH:MM`` on the Central clock. */
export const hhmm = (t: number) => HM.format(new Date(t));
/** The clock's line: the Central day and time. */
export const clockText = (t: number) => `${dayLabel(centralDate(t))} · ${hhmm(t)}`;

/** The Monday of the Central week holding ``t``. */
export function weekOf(t: number): string[] {
  const d = centralDate(t);
  const monday = addDays(d, -((weekday(d) + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => addDays(monday, i));
}

const entryLine = (e: FloorEntry) => `${e.addName}${e.dropName ? ` for ${e.dropName}` : " to an open spot"}`;
const holdTag = (e: FloorEntry): string => {
  const h = e.hold;
  if (!h) return "";
  if (h.at === "belt") return BELT.find((r) => r.key === h.rule)?.tag ?? h.reason;
  if (h.at === "sign") return SIGNS.find((r) => r.key === h.sign)?.tag ?? h.reason;
  return h.reason;
};
const outcomeCls = (o: string | null) => (o ? (OUT_KEYS[o] ?? "skipped") : "held");
const entryTitle = (e: FloorEntry) =>
  `${e.league} · ${entryLine(e)}${e.bid !== null ? ` · bid $${e.bid}` : ""}${e.gain !== null ? ` · gain +${e.gain.toFixed(2)}` : ""}` +
  (e.queued ? (e.outcome ? ` · ${e.outcome}${e.outcomeReason ? `: ${e.outcomeReason}` : ""}` : " · queued") : ` · held: ${e.hold?.reason ?? ""}`);

/** The belt's knob under each rule, from the gates' values (#458): one league's, or the value all
 * the leagues share, else "by league". */
export function knobs(rules: Record<string, QueueRules>, one: string | null, adds: LeagueRow["adds"]): Record<string, string> {
  const rows = one ? (rules[one] ? [rules[one]] : []) : Object.values(rules);
  const same = <T>(f: (r: QueueRules) => T): T | null => {
    if (!rows.length) return null;
    const v = f(rows[0]);
    return rows.every((r) => JSON.stringify(f(r)) === JSON.stringify(v)) ? v : null;
  };
  const floor = same((r) => r.noise_floor?.plan ?? null);
  const cap = same((r) => r.daily_cap.value);
  const reserve = same((r) => [r.reserve_adds, r.reserve_release] as const);
  const recut = same((r) => r.recut_days);
  const by = rows.length ? "by league" : "";
  const day = (s: string) => s.slice(0, 1).toUpperCase() + s.slice(1, 3);
  return {
    waiver_days: "dropped lately",
    noise_floor: floor !== null ? `gain under ${floor.toFixed(2)}` : by,
    reserve: reserve ? (reserve[0] ? `${reserve[0]} add until ${day(reserve[1])}` : "none held") : by,
    recut: recut !== null ? `added in ${recut} days` : by,
    week_plan: "a later day",
    no_adds: one && adds?.limit ? `${adds.used} of ${adds.limit} used` : "the week's limit",
    day_cap: cap !== null ? `${cap} a day` : by,
  };
}

const RULE_TITLE: Record<string, string> = {
  waiver_days: "the add is a player this queue drops today or dropped within the waiver days",
  noise_floor: "a gain under the noise floor is shown, never executed",
  reserve: "the week's last add is held until its release day unless a move beats the price",
  recut: "a player added within the re-cut days is not dropped cheaply",
  week_plan: "a later step of the week plan waits for its day's build",
  no_adds: "the league's weekly add limit is used up",
  day_cap: "at most the day's cap of executed moves a league",
};

/** The floor at ``t``. */
export function sceneAt(i: SceneInput): Scene {
  const { tl, t, age, now, one } = i;
  const f = floorAt(tl, t);
  const today = centralDate(t);
  const week = weekOf(t);
  const order = i.leagues.map((l) => l.league);
  const shownEntry = (e: FloorEntry) => !one || e.league === one;
  const pass = f.pass;
  const st: FloorStep | null = f.run ? f.step : null;
  const role = st ? st.cast.agent : null;
  const working = st && st.status !== "skipped" ? st : null;

  // The week strip: a day's tally of what landed or was held by t, its runs' pips.
  const days = week.map((date) => {
    const tally = { claimed: 0, held: 0, failed: 0, skipped: 0 };
    for (const e of tl.entries) {
      if (e.date !== date || !shownEntry(e)) continue;
      const s = entryState(e, t, pass, f.unit);
      if (s === "held") tally.held++;
      else if (s === "claimed" || s === "added") tally.claimed++;
      else if (s === "failed" || s === "gone") tally.failed++;
      else if (s === "skipped") tally.skipped++;
    }
    const pips = tl.runs
      .filter((r) => r.date === date)
      .map((r) => ({ title: `${hhmm(r.start)} ${r.label}`, state: (t < r.start ? "todo" : r.end === null || t < r.end ? "doing" : "done") as PelletState }));
    return { date, label: dayLabel(date), on: date === today, tally, pips };
  });

  // The engine's lamps: outlined once read today, tinted once solved, filled while solving.
  const units = (r: FloorRun) => r.steps.flatMap((s) => s.units.map((u) => ({ s, u })));
  const todays = tl.runs.filter((r) => r.date === today);
  const n = order.length;
  const lamps = order.map((league, k) => {
    let state: LampState = "";
    for (const r of todays)
      for (const { s, u } of units(r)) {
        if (u.league !== league || u.end > t) continue;
        if (s.cast.agent === "solver") state = "solved";
        else if (s.cast.agent === "scout" && s.cast.to === "engine") state = state === "solved" ? state : "read";
      }
    if (f.unit && f.unit.league === league && role === "solver" && working) state = "solving";
    const rows = Math.ceil(n / 2) || 1;
    const dy = Math.min(26, 128 / rows);
    return { league, x: 30 + (k % 2) * 78, y: 189 + Math.floor(k / 2) * dy, state, off: !!one && league !== one };
  });

  // The Solver on its rail, its two signs and their key.
  const solving = working && role === "solver" && working.units.length ? working : null;
  const rail = (solving?.units ?? []).map((u) => pelletOf(u, t));
  let sx = 34;
  if (solving) sx = lerp(36, 44 + (solving.units.length - 1) * 15, clamp((t - solving.start) / ((solving.end ?? t) - solving.start || 1)));
  const signHot = [false, false];

  // Entries: the belt, the bays, the waiting line, the Mover's load, the chips flying home.
  const bays = new Map<string, number>();
  const gates = BELT.map((r, k) => ({
    key: r.key as string,
    tag: r.tag as string,
    knob: "",
    title: RULE_TITLE[r.key],
    x: gateX(k),
    up: k % 2 ? 60 : 34,
    open: 0,
    hot: false,
  }));
  const shownLeague = i.leagues.find((l) => l.league === one) ?? null;
  const knob = knobs(tl.rules, one, shownLeague?.adds ?? null);
  for (const g of gates) g.knob = knob[g.key] ?? "";
  const yOfLeague = (league: string) => (one ? (league === one ? BELT_Y : 578) : dockY(order.indexOf(league), n));
  const laneX1 = one ? 994 : DOCK_X - 8;
  const tokens: TokenView[] = [];
  const chips: Scene["chips"] = [];
  let waiting = 0;
  let heldNow = 0;
  let travelling = false;
  let flying = false;
  let firstQueued: FloorEntry | null = null;
  const openAt: number[] = [];
  const dayEnd = (date: string) => Date.parse(`${addDays(date, 1)}T06:00:00Z`);
  const queuedAhead = new Map<string, number>();
  const visible = tl.entries.filter((e) => shownEntry(e) && t >= e.builtAt && t < Math.max(dayEnd(e.date), e.builtAt + 3_600_000));
  visible
    .filter((e) => e.queued && entryState(e, t, pass, f.unit) === "queued")
    .sort((a, b) => (a.executesAt ?? 0) - (b.executesAt ?? 0) || order.indexOf(a.league) - order.indexOf(b.league))
    .forEach((e, k) => queuedAhead.set(e.id, k));
  const mover = { x: RACK_X, y: rackY(RACK.indexOf("mover")) };
  for (const e of visible) {
    const s = entryState(e, t, pass, f.unit);
    const a = age(e.builtAt);
    let x = HUB.x + 30;
    let y = BELT_Y;
    let k = 1;
    let show = true;
    let label: TokenView["label"] = null;
    let p = 0;
    const h = e.hold;
    if (h && (h.at === "sign" || h.at === "desk" || h.at === "league")) {
      // Held in the solve (a sign) or at the desk: it never rides the belt; it sits in the tray
      // under the Solver's rail, or beside the hub.
      const key = `${e.date}|${h.at}`;
      const j = (bays.get(key) ?? 0) + 1;
      bays.set(key, j);
      if (h.at === "sign") {
        signHot[h.sign === "keep" ? 0 : 1] = true;
        x = 34;
        y = RAIL_Y + 42 + (j - 1) * 26;
        label = { x: 46, y: y + 1, anchor: "start", text: `${one ? "" : `${e.league} · `}${last(e.addName)}${e.dropName ? ` for ${last(e.dropName)}` : ""}`, sub: `the queue's check: ${holdTag(e)}`, hot: true };
      } else {
        x = HUB.x - 40 + ((j - 1) % 3) * 14;
        y = HUB.y + 66 + Math.floor((j - 1) / 3) * 14;
        label = j === 1 ? { x: HUB.x - 46, y: HUB.y + 92, anchor: "start", text: "at the desk", sub: h.at === "league" ? "its league" : "a claim already placed", hot: false } : null;
      }
      heldNow++;
    } else if (h && h.at === "belt") {
      const gk = BELT.findIndex((r) => r.key === h.rule);
      const key = `${e.date}|${h.rule}`;
      const j = (bays.get(key) ?? 0) + 1;
      bays.set(key, j);
      const gxk = gateX(gk) - 10;
      const t1 = 0.3 + (gxk - HUB.x) / 620;
      const bayY = BELT_Y + 40 + (j - 1) * 36 + (gk % 2) * 16;
      x = lerp(HUB.x + 30, gxk, ease(a / t1));
      y = lerp(BELT_Y, bayY, ease((a - t1) / 0.35));
      heldNow++;
      if (a > t1) gates[gk].hot = true;
      else if (a >= 0) travelling = true;
      label = a > t1 + 0.3 ? { x: x + 10, y: bayY + 17, anchor: "middle", text: last(e.addName), sub: one ? `gain +${(e.gain ?? 0).toFixed(2)}` : e.league, hot: false } : null;
    } else if (s === "queued" || s === "struck") {
      const ahead = queuedAhead.get(e.id) ?? 0;
      x = lerp(HUB.x + 30, GATE.x - 20 - Math.min(ahead, 30) * 15, ease(a / 1.1));
      waiting++;
      firstQueued = firstQueued ?? e;
      if (a < 1.1) {
        openAt.push(x);
        travelling = true;
      }
    } else if (s === "doing") {
      const u = f.unit && f.unit.entry === e.id ? f.unit : null;
      p = u ? clamp((t - u.start) / (u.end - u.start || 1)) : 0.5;
      x = mover.x + 1;
      y = mover.y - 21;
      k = 0.85;
      if (u && p < 0.12) {
        x = lerp(GATE.x - 20, mover.x + 1, p / 0.12);
        y = lerp(BELT_Y, mover.y - 21, p / 0.12);
      }
    } else show = false;
    if (show) tokens.push({ id: e.id, x, y, k: k * ease(a / 0.3), state: s, p, title: entryTitle(e), label });
    // a result flies back to the hub along a curve from its dock
    if (e.outcomeAt !== null && e.outcome) {
      const cp = age(e.outcomeAt) / 0.9;
      if (cp >= 0 && cp < 1) {
        flying = true;
        const q = ease(cp);
        const u = 1 - q;
        const x0 = laneX1 + 6;
        const y0 = yOfLeague(e.league);
        chips.push({ x: u * u * x0 + 2 * u * q * 650 + q * q * HUB.x, y: u * u * y0 + 2 * u * q * 132 + q * q * (HUB.y - 30), outcome: outcomeCls(e.outcome) });
      }
    }
  }
  for (const g of gates) g.open = g.hot ? 0 : clamp(Math.max(0, ...openAt.map((x) => 1 - Math.abs(x - g.x + 4) / 22)));

  const sAct = role === "solver" && !!working;
  const solver = {
    x: sx,
    open: sAct ? chomp(now) : 0.08,
    alpha: sAct || signHot[0] || signHot[1] ? 1 : 0.6,
    signs: signHot.map((hot) => (hot ? "hot" : sAct ? "on" : "")) as ("" | "on" | "hot")[],
    key: signHot,
    text: solving && f.unit?.league ? `in every search · solving ${f.unit.league}` : "in every search",
  };
  const building = st?.name === "queue_build" && !!working;
  const hub = {
    spin: building ? (now * 300) % 360 : 0,
    building,
    n: waiting,
    text: building ? "building the queue…" : waiting || heldNow ? `${waiting} waiting · ${heldNow} held` : "queue empty",
  };

  // The execute-time gate: its arm lifts while a pass takes what is due.
  const due = f.run?.steps.find((s) => s.name === "due");
  const hasDue = !!due && due.units.length > 0 && due.end !== null;
  const runEnd = f.run?.end ?? t + 60_000;
  const gate = {
    open: hasDue && due?.end ? clamp((t - due.end + 20_000) / 20_000) - clamp((t - runEnd + 20_000) / 20_000) : 0,
    face: i.executeTime,
    veto:
      firstQueued && !(f.run && f.run.routine.includes("pass")) && firstQueued.executesAt !== null && !firstQueued.struck
        ? `opens ${hhmm(firstQueued.executesAt)} · the next pass after it takes it · you can still strike it`
        : "",
  };

  // Lanes light while an agent runs them.
  const laneKeys = one ? [one, "*"] : order;
  const lanes = laneKeys.map((key) => ({ key, y: key === "*" ? 578 : yOfLeague(key), x1: laneX1, hot: 0, color: null as Agent | null }));
  if (working && working.units.length && working.cast.agent !== "scout") {
    for (const u of working.units) {
      const ln = lanes.find((l) => l.key === (one ? (u.league === one ? one : "*") : u.league));
      if (!ln) continue;
      const v = t < u.start ? 0 : t < u.end ? 1 : Math.max(0, 1 - (t - u.end) / 20_000);
      if (v * 0.8 > ln.hot) {
        ln.hot = v * 0.8;
        ln.color = working.cast.agent;
      }
    }
  }

  // The rack: an agent at work rides the lane of the league it works on.
  let moving: { u: FloorUnit; p: number; y: number } | null = null;
  const agents = RACK.map((r, k) => {
    let x = RACK_X;
    let y = rackY(k);
    const on = role === r && !!working;
    if (on && f.unit) {
      const u = f.unit;
      const ly = yOfLeague(u.league ?? "");
      const p = clamp((t - u.start) / (u.end - u.start || 1));
      const q = st?.name === "moves" ? lanePoint(ly, laneX1, ease(clamp((p - 0.12) / 0.66))) : lanePoint(ly, laneX1, ease(Math.min(1, p * 1.3)));
      x = q.x;
      y = q.y;
      if (st?.name === "moves") moving = { u, p, y: ly };
    } else if (on) {
      x = HUB.x + 58;
      y = BELT_Y + 40;
    }
    return { role: r, x, y: y - 2, open: on ? chomp(now) : 0.08, alpha: on ? 1 : 0.6, rackY: rackY(k) };
  });
  const mv = moving as { u: FloorUnit; p: number; y: number } | null;
  const steps3 = mv
    ? [0.3, 0.56, 0.82].map((q) => {
        const pt = lanePoint(mv.y, laneX1, q);
        return { x: pt.x, y: pt.y, done: ease(clamp((mv.p - 0.12) / 0.66)) > q - 0.03 };
      })
    : [];
  const moverNow = agents.find((a) => a.role === "mover");
  const sub = mv && moverNow ? { x: clamp(moverNow.x, GATE.x + 40, 1180), y: moverNow.y + 28, text: `${SUBS[Math.min(2, Math.floor(mv.p * 3))]}…` } : null;

  // The stage of the flow in play.
  let stage = 0;
  if (travelling) stage = 4;
  else if (working) {
    const nm = working.name ?? "";
    stage = nm === "queue_build" ? 3 : nm === "due" ? 6 : nm === "moves" || nm === "placed_il" ? 7 : role === "solver" ? 2 : role === "scout" ? 1 : 0;
  }
  if (!stage && flying) stage = 7;
  if (!stage && waiting && !f.run) stage = 5;

  // The docks: each league's last word today.
  const events = leagueEvents(tl, t, today);
  const docks = one
    ? []
    : i.leagues.map((l, k) => {
        const ev = events.get(l.league);
        return {
          league: l.league,
          y: dockY(k, n),
          mine: l.mine,
          pips: l.mine || !l.adds?.limit ? [] : Array.from({ length: Math.min(l.adds.limit, 8) }, (_, j) => j < l.adds!.used),
          budget: l.mine ? "suggestions only" : l.budget !== null ? `$${l.budget}` : "",
          res: ev?.text ?? (l.mine ? "nothing clicks here" : ""),
          cls: ev?.cls ?? "held",
        };
      });
  let court: Scene["court"] = null;
  if (one) {
    const l = shownLeague;
    const ev = events.get(one);
    const others = [...events.entries()].filter(([k]) => k !== one).sort((a, b) => b[1].at - a[1].at)[0]?.[1];
    court = {
      league: one,
      mine: !!l?.mine,
      sub: l?.mine ? "private · suggestions only · nothing clicks here" : `live${l?.adds?.limit ? ` · adds ${l.adds.used} of ${l.adds.limit}` : ""}${l?.budget !== null && l?.budget !== undefined ? ` · $${l.budget}` : ""}`,
      res: ev?.text ?? "",
      cls: ev?.cls ?? "",
      tiles: i.roster
        ? i.claims
          ? rosterAt(i.roster, tl.entries.filter((e) => e.league === one && weekOf(t).includes(e.date)), t, age, pass, f.unit)
          : i.roster.map((r) => ({ ...r, state: "" as const }))
        : [],
      other: { res: others?.text ?? "", cls: others?.cls ?? "" },
    };
  }

  return {
    days,
    lamps,
    rail,
    solver,
    hub,
    gates,
    stage,
    gate,
    lanes,
    docks,
    court,
    tokens,
    chips,
    agents,
    scout: scoutAt(f.run, st, t, age, now, order, one),
    steps3,
    sub,
    ledger: ledgerAt(tl, t, one),
    now: nowPanel(f, t, tl),
  };
}

/** The y of dock ``k`` of ``n``: 51 apart, closer when more than ten leagues share the column. */
export const dockY = (k: number, n: number) => 96 + k * Math.min(51, 460 / Math.max(1, n));

const pelletOf = (u: FloorUnit, t: number): PelletState => (t < u.start ? "todo" : t < u.end ? "doing" : "done");

/** Each league's last word of the day by ``t``: a step's unit there, an outcome, a hold. */
function leagueEvents(tl: Timeline, t: number, today: string): Map<string, { at: number; text: string; cls: string }> {
  const out = new Map<string, { at: number; text: string; cls: string }>();
  const put = (league: string | null, at: number, text: string, cls: string) => {
    if (!league || at > t) return;
    const was = out.get(league);
    if (!was || was.at <= at) out.set(league, { at, text, cls });
  };
  for (const r of tl.runs) {
    if (r.date !== today) continue;
    for (const s of r.steps) {
      if (s.name === "moves" || s.status === "skipped") continue;
      const text = UNIT_TEXT[s.name ?? ""];
      if (!text) continue;
      for (const u of s.units) put(u.league, u.end, text, s.cast.agent);
    }
  }
  for (const e of tl.entries) {
    if (e.date !== today) continue;
    if (e.queued && e.outcome && e.outcomeAt !== null) put(e.league, e.outcomeAt, `${MARK[e.outcome] ?? ""} ${last(e.addName)}${e.bid !== null ? ` $${e.bid}` : ""} · ${e.outcome}`, outcomeCls(e.outcome));
    else if (!e.queued && e.hold) put(e.league, e.builtAt, `held: ${last(e.addName)} · ${holdTag(e)}`, "held");
  }
  return out;
}

/** The ledger: the seven latest holds and outcomes by ``t``, newest first. */
export function ledgerAt(tl: Timeline, t: number, one: string | null): Scene["ledger"] {
  const rows = tl.entries
    .filter((e) => !one || e.league === one)
    .map((e) => {
      const at = e.queued ? e.outcomeAt : e.builtAt;
      if (at === null || at > t || (e.queued && !e.outcome)) return null;
      const text = e.queued
        ? `${e.outcome} · ${e.league} · ${last(e.addName)} for ${e.dropName ? last(e.dropName) : "an open spot"}${e.bid !== null ? ` · $${e.bid}` : ""}`
        : `held · ${e.league} · ${last(e.addName)} · ${holdTag(e)}`;
      return { at, text, cls: e.queued ? outcomeCls(e.outcome) : "held" };
    })
    .filter((x): x is { at: number; text: string; cls: string } => x !== null)
    .sort((a, b) => b.at - a.at)
    .slice(0, 7);
  return rows.map((r) => ({ at: `${DAY_NAMES[weekday(centralDate(r.at))]} ${hhmm(r.at)}`, text: r.text.length > 72 ? `${r.text.slice(0, 70)}…` : r.text, cls: r.cls }));
}

/** The Scout in the Sources room: along the stations while it reads, at its post otherwise. */
function scoutAt(run: FloorRun | null, st: FloorStep | null, t: number, age: SceneInput["age"], now: number, order: string[], one: string | null): Scene["scout"] {
  const yx = (league: string | null) => SITES[2].px(Math.max(0, order.indexOf(league ?? "")));
  const bbmEnd = SITES[0].px(4) + 8;
  const yc = SITES[2].px(Math.max(0, order.length - 1) / 2);
  const pellets: Record<SiteKey, PelletState[]> = {
    bbm: Array.from({ length: 5 }, () => "skipped"),
    espn: Array.from({ length: 3 }, () => "skipped"),
    yahoo: order.map(() => "skipped"),
  };
  let x: number = ROOM.rest;
  let on: SiteKey | null = null;
  let label = "";
  let working = false;
  let flip = false;
  const pulses: [number, number][] = [];
  const reading = st && st.cast.agent === "scout" && st.status !== "skipped" ? st : null;
  if (reading) {
    working = true;
    const p = clamp((t - reading.start) / ((reading.end ?? t + 1) - reading.start || 1));
    if (reading.name === "exports") {
      x = lerp(ROOM.rest, bbmEnd, p);
      on = "bbm";
      label = READS.exports;
      pellets.bbm = pellets.bbm.map((_, k) => (p >= (SITES[0].px(k) - ROOM.rest) / (bbmEnd - ROOM.rest) ? "done" : "todo"));
    } else if (reading.units.length) {
      const u = reading.units.find((v) => t >= v.start && t < v.end) ?? reading.units[reading.units.length - 1];
      x = yx(u.league);
      on = "yahoo";
      label = `${READS[reading.name ?? ""] ?? "reading"} ${u.league ?? ""}`.trim();
      pellets.yahoo = order.map((league) => {
        const us = reading.units.filter((v) => v.league === league);
        if (!us.length) return "skipped";
        if (us.some((v) => t >= v.start && t < v.end)) return "doing";
        return t >= us[us.length - 1].end ? "done" : "todo";
      });
      if (reading.name === "refresh") pellets.espn = pellets.espn.map(() => "done");
    } else if (reading.name === "claim_page") {
      x = lerp(ROOM.rest, yc, ease(p / 0.4));
      on = p > 0.4 ? "yahoo" : null;
      label = READS.claim_page;
    } else label = READS[reading.name ?? ""] ?? reading.name ?? "";
  } else if (run) {
    // Between reads, the Scout heads home from where its last read stood.
    const prev = [...run.steps].reverse().find((s) => s.cast.agent === "scout" && s.end !== null && s.end <= t && s.units.length);
    if (prev?.end) {
      const back = ease(age(prev.end) / 0.9);
      x = lerp(yx(prev.units[prev.units.length - 1].league), ROOM.rest, back);
      flip = back < 1;
    }
  }
  // Each read rides to where it is used: for the solve along the line into the engine, made at a
  // pass over to the execute-time gate.
  if (run) {
    for (const s of run.steps) {
      if (s.cast.agent !== "scout" || s.status === "skipped") continue;
      for (const u of s.units) {
        const q = age(u.end) / 0.9;
        if (q < 0 || q >= 1 || pulses.length >= 16) continue;
        const fx = yx(u.league);
        const pts: [number, number][] =
          s.cast.to === "gate"
            ? [[fx, ROOM.y], [fx, ROOM.line], [ROOM.up, ROOM.line], [ROOM.up, ROOM.over], [ROOM.gx, ROOM.over], [ROOM.gx, 296], [GATE.x - 5, 296], [GATE.x - 5, BELT_Y + 12]]
            : [[fx, ROOM.y], [fx, ROOM.line], [10, ROOM.line], [10, 250], [20, 250]];
        pulses.push(walk(pts, ease(q) * pathLength(pts)));
      }
    }
  }
  if (one) pellets.yahoo = pellets.yahoo.map((s, k) => (order[k] === one ? s : s === "skipped" ? s : "done"));
  return { x, open: working ? chomp(now) : 0.08, alpha: working || flip ? 1 : 0.6, flip, label, on, pellets, pulses };
}

const pathLength = (pts: [number, number][]) => pts.slice(1).reduce((sum, q, k) => sum + Math.abs(q[0] - pts[k][0]) + Math.abs(q[1] - pts[k][1]), 0);
function walk(pts: [number, number][], d: number): [number, number] {
  let left = d;
  for (let k = 1; k < pts.length; k++) {
    const [x0, y0] = pts[k - 1];
    const [x1, y1] = pts[k];
    const run = Math.abs(x1 - x0) + Math.abs(y1 - y0);
    if (left <= run || k === pts.length - 1) {
      const q = run ? Math.min(1, left / run) : 0;
      return [x0 + (x1 - x0) * q, y0 + (y1 - y0) * q];
    }
    left -= run;
  }
  return pts[pts.length - 1];
}

/** The panel under the floor: the run under way (its steps, its unit) or, at rest, the next timer. */
function nowPanel(f: ReturnType<typeof floorAt>, t: number, tl: Timeline): NowPanel {
  if (!f.run || !f.step) {
    // The next run the timeline holds (the Demo's week), else the next timer.
    const ahead = tl.runs.find((r) => r.start > t);
    const nx = ahead ? { label: ahead.label, at: ahead.start } : f.next;
    return {
      title: "Idle",
      agent: null,
      when: "",
      line: nx ? `Next: ${nx.label}, ${dayLabel(centralDate(nx.at))} ${hhmm(nx.at)}. Nothing runs between the timers.` : "Nothing runs between the timers.",
      steps: [],
      unit: null,
    };
  }
  const r = f.run;
  const s = f.step;
  const agent = s.cast.agent;
  const steps = r.steps.map((x) => ({
    name: x.name ?? `after ${x.after ?? "the start"}`,
    agent: x.cast.agent,
    state: (x.status === "running" ? "running" : t < x.start ? "todo" : x.status === "skipped" ? "skipped" : x.end === null || t < x.end ? "doing" : "done") as PelletState | "running",
    detail: x.detail,
  }));
  const span = (s.end ?? t) - s.start;
  const u = f.unit;
  const k = u ? s.units.indexOf(u) : -1;
  const up = u ? clamp((t - u.start) / (u.end - u.start || 1)) : 0;
  const unit: NowPanel["unit"] = u
    ? {
        big: s.name === "moves" ? `${u.league ?? ""} · entry ${k + 1} of ${s.units.length}` : `${s.name} · league ${u.league ?? ""}`,
        sub: s.name === "moves" ? `${SUBS[Math.min(2, Math.floor(up * 3))]}…` : `${k + 1} of ${s.units.length}`,
        p: up,
      }
    : { big: s.detail, sub: "", p: span > 0 ? clamp((t - s.start) / span) : s.end === null ? 0.5 : 1 };
  return {
    title: r.label,
    agent,
    when: `${dayLabel(r.date)} ${hhmm(r.start)}`,
    line: `${s.name ?? `under way after ${s.after ?? "the start"}`} · ${AGENTS[agent].label}${s.detail ? ` · ${s.detail}` : ""}`,
    steps,
    unit,
  };
}

