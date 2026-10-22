// The card rail, its two-half drawer and the keyboard shortcuts, shared by the draft screen and
// the league page (#109): the drawer's state changes, the key handler, each screen's cards, key
// map and key sheet. No React and no runtime imports, so `npm test` runs it under Node.
import type { DraftApi } from "./draft";

export type Half = "top" | "bottom";

export interface CardDef<Id extends string> {
  id: Id;
  title: string;
  blurb: string;
  /** False for a card that is not a drawer half (the league page's Waivers board). */
  halves?: boolean;
}

export interface Pair<Id extends string> {
  top: Id | null;
  bottom: Id | null;
}

export interface DrawerState<Id extends string> extends Pair<Id> {
  collapsed: boolean;
  /** Share of the drawer height given to the top card when both halves are open. */
  split: number;
  /** The last non-empty pair, restored by `]` after both halves were closed. */
  last: Pair<Id>;
  /** Drawer width in pixels, dragged at its left edge. */
  width: number;
}

export const DRAWER_WIDTH = 420;
export const MIN_DRAWER_WIDTH = 320;

// ---------------------------------------------------------------- the drawer
export function isOpen<Id extends string>(d: DrawerState<Id>): boolean {
  return !d.collapsed && (d.top !== null || d.bottom !== null);
}

/** Whether ``id`` is on show in one of the halves. */
export function isShown<Id extends string>(d: DrawerState<Id>, id: Id): boolean {
  return isOpen(d) && (d.top === id || d.bottom === id);
}

export const clampSplit = (ratio: number): number => Math.min(0.8, Math.max(0.2, ratio));

/** A card's key or rail click: open it in ``half``, or close it when it is already on show. */
export function openCard<Id extends string>(d: DrawerState<Id>, id: Id, half: Half = "top"): DrawerState<Id> {
  if (d.collapsed) {
    // Reopening: keep the pair if the card is already in it, else place the card.
    if (d.top === id || d.bottom === id) return { ...d, collapsed: false };
    const top = half === "top" ? id : d.top;
    const bottom = half === "bottom" ? id : d.bottom;
    return { ...d, top, bottom, collapsed: false, last: { top, bottom } };
  }
  let { top, bottom } = d;
  if (top === id) top = null;
  else if (bottom === id) bottom = null;
  else if (half === "top") top = id;
  else bottom = id;
  const empty = top === null && bottom === null;
  return { ...d, top, bottom, collapsed: empty, last: empty ? d.last : { top, bottom } };
}

export function closeCard<Id extends string>(d: DrawerState<Id>, id: Id): DrawerState<Id> {
  if (d.top !== id && d.bottom !== id) return d;
  const top = d.top === id ? null : d.top;
  const bottom = d.bottom === id ? null : d.bottom;
  const empty = top === null && bottom === null;
  return { ...d, top, bottom, collapsed: empty, last: empty ? d.last : { top, bottom } };
}

/** `]`: collapse an open drawer, or bring back its pair (``fallback`` when it never had one). */
export function toggleDrawer<Id extends string>(d: DrawerState<Id>, fallback: Pair<Id>): DrawerState<Id> {
  if (isOpen(d)) return { ...d, collapsed: true };
  if (d.top !== null || d.bottom !== null) return { ...d, collapsed: false };
  const last = d.last.top !== null || d.last.bottom !== null ? d.last : fallback;
  return { ...d, top: last.top, bottom: last.bottom, collapsed: false };
}

export function swapHalves<Id extends string>(d: DrawerState<Id>): DrawerState<Id> {
  return { ...d, top: d.bottom, bottom: d.top, last: { top: d.bottom, bottom: d.top } };
}

/** Show ``to`` in place of ``from`` (the league page's Moves and Trade share a half): where
 * ``from`` is, else in the top half; a card already on show stays where it is. */
export function replaceCard<Id extends string>(d: DrawerState<Id>, from: Id, to: Id): DrawerState<Id> {
  if (isShown(d, to)) return d;
  // A collapsed pair that holds it comes back as it was.
  if (d.top === to || d.bottom === to) return { ...d, collapsed: false };
  let { top, bottom } = d;
  if (bottom === from) bottom = to;
  else top = to;
  return { ...d, top, bottom, collapsed: false, last: { top, bottom } };
}

/** A drawer saved in the browser, or ``defaults`` (blocked storage, a bad value). */
export function parseDrawer<Id extends string>(
  raw: string | null,
  isCard: (v: unknown) => v is Id,
  defaults: DrawerState<Id>,
  clampWidth: (px: number) => number,
): DrawerState<Id> {
  if (!raw) return defaults;
  try {
    const d = JSON.parse(raw) as Partial<DrawerState<Id>>;
    const top = isCard(d.top) ? d.top : null;
    const bottom = isCard(d.bottom) ? d.bottom : null;
    return {
      top,
      bottom,
      collapsed: !!d.collapsed,
      split: typeof d.split === "number" ? clampSplit(d.split) : defaults.split,
      width: clampWidth(typeof d.width === "number" ? d.width : defaults.width),
      last:
        d.last && (isCard(d.last.top) || isCard(d.last.bottom))
          ? { top: isCard(d.last.top) ? d.last.top : null, bottom: isCard(d.last.bottom) ? d.last.bottom : null }
          : { top, bottom },
    };
  } catch {
    return defaults;
  }
}

// ---------------------------------------------------------------- keys
/** The parts of a keydown the handler reads (a DOM KeyboardEvent has them all). */
export interface KeyLike {
  key: string;
  code?: string;
  shiftKey?: boolean;
  metaKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  target?: unknown;
}

interface TargetLike {
  tagName?: string;
  type?: string;
  isContentEditable?: boolean;
  blur?: () => void;
}

const TEXT_INPUTS = new Set(["text", "search", "number", "email", "password", "url", "tel"]);
const SHIFTED_DIGITS: Record<string, number> = { "!": 1, "@": 2, "#": 3, $: 4, "%": 5, "^": 6, "&": 7, "*": 8, "(": 9 };

/** The card digit (1 to ``count``) from the physical key when the browser reports it, else
 * from the typed character. */
export function cardDigit(e: KeyLike, count: number): number | null {
  const physical = /^Digit([1-9])$/.exec(e.code ?? "");
  const n = physical ? Number(physical[1]) : /^[1-9]$/.test(e.key) ? Number(e.key) : (SHIFTED_DIGITS[e.key] ?? null);
  return n !== null && n <= count ? n : null;
}

/** What has focus: text entry swallows letters; a focused checkbox, slider or select does not. */
function focus(target: unknown): { tag: string; typing: boolean; control: boolean; blur: () => void } {
  const t = (target ?? {}) as TargetLike;
  const tag = t.tagName ?? "";
  return {
    tag,
    typing: tag === "TEXTAREA" || !!t.isContentEditable || (tag === "INPUT" && TEXT_INPUTS.has(t.type ?? "")),
    control: tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || tag === "BUTTON" || tag === "A",
    blur: () => t.blur?.(),
  };
}

/** A screen's keys: its card count, its sheet, what its digits and Esc do and its letters. */
export interface KeyMap {
  /** The digits 1 to ``cards`` open a card (shifted: in the bottom half). */
  cards: number;
  openCard: (index: number, half: Half) => void;
  sheetOpen: boolean;
  setSheetOpen: (open: boolean) => void;
  /** Esc once the sheet is closed and no field has focus. */
  escape: () => void;
  /** The other keys by ``KeyboardEvent.key``; a handler returning false leaves the key alone. */
  keys: Record<string, (ctx: { control: boolean }) => boolean | void>;
}

/** One keydown: true when a shortcut took it (the caller prevents the browser's default).
 * Letters are ignored while a field has focus; Esc leaves the field first. Any shortcut used
 * while the key sheet is open also closes the sheet, so keys can be tried from it. */
export function handleKey(e: KeyLike, map: KeyMap): boolean {
  const f = focus(e.target);
  if (e.key === "Escape") {
    if (map.sheetOpen) map.setSheetOpen(false);
    else if (f.typing || f.tag === "SELECT") f.blur();
    else {
      if (f.control) f.blur();
      map.escape();
    }
    return true;
  }
  if (f.typing || e.metaKey || e.ctrlKey || e.altKey) return false;
  if (e.key === "?") {
    map.setSheetOpen(!map.sheetOpen);
    return true;
  }
  const closeSheet = () => {
    if (map.sheetOpen) map.setSheetOpen(false);
  };
  const digit = cardDigit(e, map.cards);
  if (digit) {
    map.openCard(digit - 1, e.shiftKey ? "bottom" : "top");
    closeSheet();
    return true;
  }
  if (f.tag === "SELECT") return false; // letters change the selection natively
  const run = Object.hasOwn(map.keys, e.key) ? map.keys[e.key] : undefined;
  if (!run || run({ control: f.control }) === false) return false;
  closeSheet();
  return true;
}

// ---------------------------------------------------------------- key sheets
export interface Sheet {
  /** The header line naming the cards by their numbers. */
  cards: string;
  groups: { title: string; rows: [string[], string][] }[];
  footer: string;
}

// ---------------------------------------------------------------- the draft screen
export type DraftCardId = "pick" | "cats" | "alts" | "plan" | "team" | "log" | "solver" | "sync";

export const DRAFT_CARDS: CardDef<DraftCardId>[] = [
  { id: "pick", title: "Pick", blurb: "recommended pick" },
  { id: "cats", title: "Categories", blurb: "odds of winning each category, and the league" },
  { id: "alts", title: "Alternatives", blurb: "priced alternatives and what-if scenarios" },
  { id: "plan", title: "Plan", blurb: "plan for the remaining picks" },
  { id: "team", title: "Team", blurb: "score, expected profile and roster" },
  { id: "log", title: "Log", blurb: "every pick so far" },
  { id: "solver", title: "Solver", blurb: "timings, objective, settings" },
  { id: "sync", title: "Yahoo sync", blurb: "the Yahoo draft room: sync, mode, aliases, fidelity" },
];

/** The draft screen's keys, on its state (``DraftApi``). */
export function draftKeys(d: DraftApi): KeyMap {
  return {
    cards: DRAFT_CARDS.length,
    openCard: (i, half) => d.openCard(DRAFT_CARDS[i].id, half),
    sheetOpen: d.sheetOpen,
    setSheetOpen: d.setSheetOpen,
    escape: d.collapseDrawer,
    keys: {
      "]": () => d.toggleDrawer(),
      x: () => d.swapHalves(),
      "/": () => {
        d.searchRef.current?.focus();
        d.searchRef.current?.select();
      },
      ArrowDown: () => d.moveHighlight(1),
      j: () => d.moveHighlight(1),
      ArrowUp: () => d.moveHighlight(-1),
      k: () => d.moveHighlight(-1),
      Enter: ({ control }) => {
        if (control || !d.highlight) return false; // let the focused control act
        d.draftPlayer(d.highlight, { via: "key" });
      },
      d: () => {
        const top = d.result?.candidates[0];
        if (!top || d.busy || d.done) return false; // never draft from a stale answer
        d.draftPlayer(top.player, { via: "key" });
      },
      z: () => d.undo(),
      h: () => d.toggleAvailableOnly(),
      r: () => d.solve(),
      s: () => {
        if (d.session.on_the_clock) d.showToast({ message: "You are on the clock: make your pick first" });
        else d.simulate({ until_my_pick: true });
      },
      S: () => d.simulate({ count: 1, until_my_pick: false }),
      m: () => {
        if (d.mock) {
          d.setMock(false);
          d.showToast({ message: "Mock draft stopped" });
        } else if (!d.live) {
          d.setMock(true);
          d.showToast({ message: "Mock draft running: other teams simulated, the solver drafts for you" });
        } else d.setMock(true); // shows the live-draft toast
      },
    },
  };
}

export const DRAFT_SHEET: Sheet = {
  cards:
    "Cards are 1 Pick · 2 Categories · 3 Alternatives · 4 Plan · 5 Team · 6 Log · 7 Solver · 8 Yahoo sync, the numbers on the rail. Letters do nothing while you are typing in a field.",
  groups: [
    {
      title: "Cards",
      rows: [
        [["1", "…", "8"], "open that card in the top half; the same key again closes it"],
        [["⇧ 1", "…", "⇧ 8"], "open it in the bottom half (mouse: shift-click or right-click the rail icon)"],
        [["]"], "collapse the drawer to the rail, or bring it back with its two cards"],
        [["Esc"], "collapse the drawer; in a field it leaves the field first"],
        [["x"], "swap the top and bottom cards"],
      ],
    },
    {
      title: "Board",
      rows: [
        [["/"], "jump to search; Enter there drafts the first match"],
        [["↓", "j"], "move the highlight down"],
        [["↑", "k"], "move the highlight up"],
        [["Enter"], "draft the highlighted player to the team on the clock"],
        [["d"], "draft the recommended pick"],
        [["z"], "undo the last pick"],
        [["h"], "available players only, or everyone (drafted players marked)"],
      ],
    },
    {
      title: "Solver and simulation",
      rows: [
        [["r"], "re-solve now (the server also re-solves after every pick)"],
        [["s"], "simulate the other teams up to my pick"],
        [["⇧ S"], "simulate one pick"],
        [["m"], "mock draft: run the whole draft, the other teams simulated and the solver drafting for you (never while a Yahoo feed or room is attached)"],
        [["?"], "this sheet"],
      ],
    },
  ],
  footer: "Every key mirrors a visible control. Keys work while this sheet is open and close it. A pick made by key shows a toast with Undo for five seconds.",
};

// ---------------------------------------------------------------- the league page
export type SeasonCardId = "waivers" | "moves" | "trade" | "flags" | "roster" | "league" | "strategy";

export const SEASON_CARDS: CardDef<SeasonCardId>[] = [
  { id: "waivers", title: "Waivers", blurb: "the available players; the board at full width", halves: false },
  { id: "moves", title: "Moves", blurb: "the recommended moves, and a player's move" },
  { id: "trade", title: "Trade", blurb: "a trade with another team, both sides before and after" },
  { id: "flags", title: "Flags", blurb: "breakout flags on the available players" },
  { id: "roster", title: "My roster", blurb: "my players and their games this week" },
  { id: "league", title: "The league", blurb: "the standings and the weeks recorded, or this week's matchups" },
  { id: "strategy", title: "Strategy", blurb: "this week against the rest of the season: the recommended set at each weight" },
];

/** The views of the league page's pane (#116), the tabs of the drawer at its left edge. */
export type SeasonViewId = "waivers" | "matchup";

export interface ViewDef {
  id: SeasonViewId;
  title: string;
  /** The letter that shows it. */
  key: string;
  blurb: string;
}

export const SEASON_VIEWS: ViewDef[] = [
  { id: "waivers", title: "Waivers", key: "w", blurb: "the available players and their moves" },
  { id: "matchup", title: "Matchup", key: "h", blurb: "this week's matchup and what each player adds to it" },
];

/** The view on show and whether the drawer is shown or down to its handle. */
export interface Views {
  view: SeasonViewId;
  shown: boolean;
}

export const DEFAULT_VIEWS: Views = { view: "waivers", shown: true };

/** The views saved in the browser, or the defaults (blocked storage, a bad value). */
export function parseViews(raw: string | null): Views {
  if (!raw) return DEFAULT_VIEWS;
  try {
    const v = JSON.parse(raw) as Partial<Views>;
    const view = SEASON_VIEWS.some((d) => d.id === v.view) ? (v.view as SeasonViewId) : DEFAULT_VIEWS.view;
    return { view, shown: typeof v.shown === "boolean" ? v.shown : DEFAULT_VIEWS.shown };
  } catch {
    return DEFAULT_VIEWS;
  }
}

/** The Waivers highlight moved by ``delta`` through the rows on show (j, k and the arrows):
 * from the first or last row when nothing on show is highlighted. */
export function stepHighlight(rows: number[], h: number | null, delta: number): number | null {
  if (!rows.length) return null;
  let i = h === null ? -1 : rows.indexOf(h);
  if (i < 0) i = delta > 0 ? -1 : rows.length;
  return rows[Math.min(rows.length - 1, Math.max(0, i + delta))];
}

/** What the league page's keys act on. */
export interface SeasonKeys {
  /** The view on show: the Waivers keys (the arrows, j, k, Enter) act only in its view. */
  view: SeasonViewId;
  setView: (view: SeasonViewId) => void;
  /** Show the view drawer, or take it down to its handle. */
  toggleViews: () => void;
  openCard: (id: SeasonCardId, half: Half) => void;
  toggleDrawer: () => void;
  swapHalves: () => void;
  /** Esc's last step: the panel collapses to the rail. */
  collapse: () => void;
  /** Esc's first step: close an open flag breakdown (#113); false when none is open. */
  closeBreakdown: () => boolean;
  /** Esc's middle step: close the move drawer; false when none is open. */
  closeMove: () => boolean;
  /** The panel shows Trade (t) or Moves (m) in the half the other holds. */
  show: (card: "moves" | "trade") => void;
  /** The Waivers search, in the Waivers view. */
  focusSearch: () => void;
  moveHighlight: (delta: number) => void;
  /** The highlighted Waivers row's player. */
  highlight: number | null;
  /** Open a player's move drawer. */
  openMove: (player: number) => void;
  /** Read the league again; null when it cannot be (a private league, a refresh running). */
  refresh: (() => void) | null;
  sheetOpen: boolean;
  setSheetOpen: (open: boolean) => void;
}

export function seasonKeys(s: SeasonKeys): KeyMap {
  const waivers = (run: () => void) => () => {
    if (s.view !== "waivers") return false;
    run();
  };
  const views = Object.fromEntries(SEASON_VIEWS.map((v) => [v.key, () => s.setView(v.id)]));
  return {
    cards: SEASON_CARDS.length,
    openCard: (i, half) => s.openCard(SEASON_CARDS[i].id, half),
    sheetOpen: s.sheetOpen,
    setSheetOpen: s.setSheetOpen,
    escape: () => {
      if (!s.closeBreakdown() && !s.closeMove()) s.collapse();
    },
    keys: {
      ...views,
      "[": () => s.toggleViews(),
      "]": () => s.toggleDrawer(),
      x: () => s.swapHalves(),
      "/": () => s.focusSearch(),
      ArrowDown: waivers(() => s.moveHighlight(1)),
      j: waivers(() => s.moveHighlight(1)),
      ArrowUp: waivers(() => s.moveHighlight(-1)),
      k: waivers(() => s.moveHighlight(-1)),
      Enter: ({ control }) => {
        if (control || s.highlight === null || s.view !== "waivers") return false; // let the focused control act
        s.openMove(s.highlight);
      },
      t: () => s.show("trade"),
      m: () => s.show("moves"),
      r: () => {
        if (!s.refresh) return false;
        s.refresh();
      },
    },
  };
}

export const SEASON_SHEET: Sheet = {
  cards:
    "Cards are 1 Waivers · 2 Moves · 3 Trade · 4 Flags · 5 My roster · 6 The league · 7 Strategy, the numbers on the rail. Views are w Waivers · h Matchup, the tabs of the drawer at the left. Letters do nothing while you are typing in a field.",
  groups: [
    {
      title: "Views",
      rows: [
        [["w"], "the Waivers view: the available players and their moves"],
        [["h"], "the Matchup view: this week's matchup and what each player adds to it"],
        [["["], "take the view drawer down to its handle, or show it (the letters work either way)"],
      ],
    },
    {
      title: "Cards",
      rows: [
        [["1", "…", "7"], "open that card in the top half; the same key again closes it (1 Waivers shows the Waivers view; there it gives the board the full width, and again brings the panel back)"],
        [["⇧ 2", "…", "⇧ 7"], "open it in the bottom half (mouse: shift-click or right-click the rail icon)"],
        [["]"], "collapse the panel to the rail, or bring it back with its two cards"],
        [["x"], "swap the top and bottom cards"],
        [["Esc"], "leave a field, then close a flag breakdown, then the move drawer, then collapse the panel"],
      ],
    },
    {
      title: "Waivers",
      rows: [
        [["/"], "jump to the Waivers search (from any view)"],
        [["↓", "j"], "move the highlight down (in the Waivers view)"],
        [["↑", "k"], "move the highlight up"],
        [["Enter"], "open the highlighted player's move drawer"],
      ],
    },
    {
      title: "League",
      rows: [
        [["t"], "the panel shows Trade"],
        [["m"], "the panel shows Moves"],
        [["r"], "refresh the league (public leagues)"],
        [["?"], "this sheet"],
      ],
    },
  ],
  footer: "Every key mirrors a visible control. Keys work while this sheet is open and close it. The draft screen keeps its own keys.",
};
