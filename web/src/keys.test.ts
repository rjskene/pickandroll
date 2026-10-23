// Node's own test runner with its built-in type stripping (`npm test`), as format.test.ts: the
// shared rail, drawer and key handler (#109), on the draft screen's keys and the league page's.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { DraftApi } from "./draft";
import {
  cardDigit,
  closeCard,
  DRAFT_CARDS,
  DRAFT_SHEET,
  draftKeys,
  handleKey,
  DEFAULT_VIEWS,
  openCard,
  parseDrawer,
  parseViews,
  replaceCard,
  SEASON_CARDS,
  SEASON_SHEET,
  SEASON_VIEWS,
  seasonKeys,
  stepHighlight,
  swapHalves,
  toggleDrawer,
  type DrawerState,
  type KeyLike,
  type SeasonKeys,
} from "./keys.ts";

type Id = "a" | "b" | "c";
const drawer = (over: Partial<DrawerState<Id>> = {}): DrawerState<Id> => ({
  top: "a",
  bottom: "b",
  collapsed: false,
  split: 0.5,
  last: { top: "a", bottom: "b" },
  width: 420,
  ...over,
});

// ---------------------------------------------------------------- the drawer
test("a card opens in its half and closes on the same key", () => {
  const d = openCard(drawer(), "c", "bottom");
  assert.deepEqual([d.top, d.bottom], ["a", "c"]);
  const again = openCard(d, "c", "bottom");
  assert.deepEqual([again.top, again.bottom], ["a", null]);
  const both = openCard(openCard(drawer(), "a"), "b");
  assert.equal(both.collapsed, true, "closing both halves collapses the drawer");
  assert.deepEqual(both.last, { top: null, bottom: "b" }, "and remembers the last pair on show");
});

test("a collapsed drawer reopens with its pair, or places the card", () => {
  const d = drawer({ collapsed: true });
  assert.deepEqual(openCard(d, "b"), { ...d, collapsed: false });
  const placed = openCard(d, "c", "top");
  assert.deepEqual([placed.top, placed.bottom, placed.collapsed], ["c", "b", false]);
});

test("] collapses, brings the pair back, or opens the fallback", () => {
  const d = drawer();
  assert.equal(toggleDrawer(d, { top: "c", bottom: null }).collapsed, true);
  assert.equal(toggleDrawer(drawer({ collapsed: true }), { top: "c", bottom: null }).collapsed, false);
  const empty = drawer({ top: null, bottom: null, collapsed: true, last: { top: null, bottom: null } });
  const back = toggleDrawer(empty, { top: "c", bottom: null });
  assert.deepEqual([back.top, back.bottom, back.collapsed], ["c", null, false]);
});

test("closing and swapping", () => {
  assert.deepEqual([closeCard(drawer(), "a").top, closeCard(drawer(), "a").bottom], [null, "b"]);
  const d = drawer();
  assert.equal(closeCard(d, "c"), d, "a card off show is left alone");
  const s = swapHalves(drawer());
  assert.deepEqual([s.top, s.bottom], ["b", "a"]);
});

test("replaceCard takes the other card's half, else the top", () => {
  // a = moves, c = trade
  assert.deepEqual([replaceCard(drawer(), "a", "c").top, replaceCard(drawer(), "a", "c").bottom], ["c", "b"]);
  const below = drawer({ top: "b", bottom: "a" });
  assert.deepEqual([replaceCard(below, "a", "c").top, replaceCard(below, "a", "c").bottom], ["b", "c"]);
  const neither = drawer({ top: "b", bottom: null });
  assert.deepEqual([replaceCard(neither, "a", "c").top, replaceCard(neither, "a", "c").bottom], ["c", null]);
  const d = drawer();
  assert.equal(replaceCard(d, "c", "a"), d, "on show: unchanged");
  const collapsed = drawer({ collapsed: true });
  const back = replaceCard(collapsed, "c", "a");
  assert.deepEqual([back.top, back.bottom, back.collapsed], ["a", "b", false], "a collapsed pair holding it comes back");
  const swapped = replaceCard(collapsed, "a", "c");
  assert.deepEqual([swapped.top, swapped.bottom, swapped.collapsed], ["c", "b", false]);
});

test("a saved drawer is read back, a bad one gives the defaults", () => {
  const isCard = (v: unknown): v is Id => v === "a" || v === "b" || v === "c";
  const defaults = drawer();
  const clamp = (px: number) => Math.min(600, Math.max(320, px));
  assert.equal(parseDrawer(null, isCard, defaults, clamp), defaults);
  assert.equal(parseDrawer("{not json", isCard, defaults, clamp), defaults);
  const read = parseDrawer(JSON.stringify({ top: "c", bottom: "z", collapsed: true, split: 0.95, width: 900 }), isCard, defaults, clamp);
  assert.deepEqual(read, { top: "c", bottom: null, collapsed: true, split: 0.8, width: 600, last: { top: "c", bottom: null } });
});

// ---------------------------------------------------------------- keys
const field = { tagName: "INPUT", type: "search", blurred: 0, blur() { this.blurred++; } };
const checkbox = { tagName: "INPUT", type: "checkbox", blurred: 0, blur() { this.blurred++; } };
const select = { tagName: "SELECT", blurred: 0, blur() { this.blurred++; } };
const key = (k: string, over: Partial<KeyLike> = {}): KeyLike => ({ key: k, target: { tagName: "BODY" }, ...over });
const digit = (n: number, shift = false): KeyLike => key(shift ? "!@#$%^&*("[n - 1] : String(n), { code: `Digit${n}`, shiftKey: shift });

test("card digits: the physical key, the typed one, shifted ones, none past the count", () => {
  assert.equal(cardDigit({ key: "@", code: "Digit2" }, 8), 2);
  assert.equal(cardDigit({ key: "3" }, 8), 3);
  assert.equal(cardDigit({ key: "#" }, 8), 3);
  assert.equal(cardDigit({ key: "7", code: "Digit7" }, 6), null);
  assert.equal(cardDigit({ key: "9", code: "Digit9" }, 8), null);
  assert.equal(cardDigit({ key: "a", code: "KeyA" }, 8), null);
});

/** The draft screen's state with every action recorded. */
function fakeDraft(over: Record<string, unknown> = {}) {
  const calls: unknown[][] = [];
  const rec =
    (name: string) =>
    (...args: unknown[]) => {
      calls.push([name, ...args]);
    };
  const d = {
    sheetOpen: false,
    setSheetOpen: rec("sheet"),
    openCard: rec("open"),
    collapseDrawer: rec("collapse"),
    toggleDrawer: rec("toggle"),
    swapHalves: rec("swap"),
    searchRef: { current: { focus: rec("focus"), select: rec("select") } },
    moveHighlight: rec("highlight"),
    highlight: null,
    draftPlayer: rec("draft"),
    result: undefined,
    busy: false,
    done: false,
    undo: rec("undo"),
    toggleAvailableOnly: rec("availableOnly"),
    solve: rec("solve"),
    session: { on_the_clock: false },
    showToast: rec("toast"),
    simulate: rec("simulate"),
    mock: false,
    live: false,
    setMock: rec("mock"),
    ...over,
  };
  return { map: draftKeys(d as unknown as DraftApi), calls };
}

test("draft: digits 1 to 8 open the eight cards, shifted in the bottom half", () => {
  for (const [i, c] of DRAFT_CARDS.entries()) {
    const { map, calls } = fakeDraft();
    assert.equal(handleKey(digit(i + 1), map), true);
    assert.equal(handleKey(digit(i + 1, true), map), true);
    assert.deepEqual(calls, [
      ["open", c.id, "top"],
      ["open", c.id, "bottom"],
    ]);
  }
  const { map, calls } = fakeDraft();
  assert.equal(handleKey(digit(9), map), false);
  assert.deepEqual(calls, []);
});

test("draft: every letter key does what it did", () => {
  const cases: [KeyLike, unknown[][], Record<string, unknown>?][] = [
    [key("]"), [["toggle"]]],
    [key("x"), [["swap"]]],
    [key("/"), [["focus"], ["select"]]],
    [key("j"), [["highlight", 1]]],
    [key("ArrowDown"), [["highlight", 1]]],
    [key("k"), [["highlight", -1]]],
    [key("ArrowUp"), [["highlight", -1]]],
    [key("Enter"), [["draft", "p7", { via: "key" }]], { highlight: "p7" }],
    [key("d"), [["draft", "p1", { via: "key" }]], { result: { candidates: [{ player: "p1" }] } }],
    [key("z"), [["undo"]]],
    [key("h"), [["availableOnly"]]],
    [key("r"), [["solve"]]],
    [key("s"), [["simulate", { until_my_pick: true }]]],
    [key("s"), [["toast", { message: "You are on the clock: make your pick first" }]], { session: { on_the_clock: true } }],
    [key("S"), [["simulate", { count: 1, until_my_pick: false }]]],
    [key("m"), [["mock", true], ["toast", { message: "Mock draft running: other teams simulated, the solver drafts for you" }]]],
    [key("m"), [["mock", false], ["toast", { message: "Mock draft stopped" }]], { mock: true }],
    [key("m"), [["mock", true]], { live: true }],
  ];
  for (const [e, want, over] of cases) {
    const { map, calls } = fakeDraft(over);
    assert.equal(handleKey(e, map), true, e.key);
    assert.deepEqual(calls, want, e.key);
  }
});

test("draft: keys that must not act", () => {
  const none: [KeyLike, Record<string, unknown>?][] = [
    [key("Enter")], // nothing highlighted
    [key("Enter", { target: { tagName: "BUTTON" } }), { highlight: "p7" }], // the focused button acts
    [key("d"), { result: { candidates: [{ player: "p1" }] }, busy: true }], // never from a stale answer
    [key("d"), { result: { candidates: [{ player: "p1" }] }, done: true }],
    [key("d")],
    [key("j", { target: field })], // typing
    [key("j", { target: select })], // letters change the selection
    [key("j", { metaKey: true })],
    [key("q")],
    [key("constructor")],
  ];
  for (const [e, over] of none) {
    const { map, calls } = fakeDraft(over);
    assert.equal(handleKey(e, map), false, e.key);
    assert.deepEqual(calls, [], e.key);
  }
});

test("draft: ? toggles the sheet; a key used from the sheet closes it; Esc steps back", () => {
  let f = fakeDraft();
  assert.equal(handleKey(key("?"), f.map), true);
  assert.deepEqual(f.calls, [["sheet", true]]);
  f = fakeDraft({ sheetOpen: true });
  handleKey(digit(2), f.map);
  assert.deepEqual(f.calls, [["open", "cats", "top"], ["sheet", false]]);
  f = fakeDraft({ sheetOpen: true });
  handleKey(key("Escape"), f.map);
  assert.deepEqual(f.calls, [["sheet", false]], "Esc closes the sheet first");
  f = fakeDraft();
  const input = { ...field, blurred: 0 };
  handleKey(key("Escape", { target: input }), f.map);
  assert.deepEqual([f.calls, input.blurred], [[], 1], "then leaves the field");
  f = fakeDraft();
  const box = { ...checkbox, blurred: 0 };
  handleKey(key("Escape", { target: box }), f.map);
  assert.deepEqual([f.calls, box.blurred], [[["collapse"]], 1], "a control loses focus and the drawer collapses");
  f = fakeDraft();
  assert.equal(handleKey(digit(1), { ...f.map }), true);
  assert.equal(handleKey(key("1", { target: checkbox }), f.map), true, "a focused checkbox does not block a digit");
});

/** The league page's actions, recorded. */
function fakeSeason(over: Partial<SeasonKeys> = {}) {
  const calls: unknown[][] = [];
  const rec =
    (name: string) =>
    (...args: unknown[]) => {
      calls.push([name, ...args]);
    };
  const s: SeasonKeys = {
    view: "waivers",
    setView: rec("view"),
    toggleViews: rec("views"),
    openCard: rec("open"),
    toggleDrawer: rec("toggle"),
    swapHalves: rec("swap"),
    collapse: rec("collapse"),
    closeBreakdown: () => false,
    closeMove: () => false,
    show: rec("show"),
    focusSearch: rec("search"),
    moveHighlight: rec("highlight"),
    highlight: null,
    openMove: rec("move"),
    refresh: rec("refresh"),
    sheetOpen: false,
    setSheetOpen: rec("sheet"),
    ...over,
  };
  return { map: seasonKeys(s), calls };
}

test("season: digits 1 to 7 open the seven cards, shifted in the bottom half", () => {
  assert.deepEqual(
    SEASON_CARDS.map((c) => c.id),
    ["waivers", "moves", "trade", "flags", "roster", "league", "strategy"],
  );
  for (const [i, c] of SEASON_CARDS.entries()) {
    const { map, calls } = fakeSeason();
    assert.equal(handleKey(digit(i + 1), map), true);
    assert.equal(handleKey(digit(i + 1, true), map), true);
    assert.deepEqual(calls, [
      ["open", c.id, "top"],
      ["open", c.id, "bottom"],
    ]);
  }
  for (const n of [8, 9]) {
    const { map, calls } = fakeSeason();
    assert.equal(handleKey(digit(n), map), false);
    assert.deepEqual(calls, []);
  }
});

test("season: ] / j k arrows Enter t m r x", () => {
  const cases: [KeyLike, unknown[][], Partial<SeasonKeys>?][] = [
    [key("]"), [["toggle"]]],
    [key("x"), [["swap"]]],
    [key("/"), [["search"]]],
    [key("j"), [["highlight", 1]]],
    [key("ArrowDown"), [["highlight", 1]]],
    [key("k"), [["highlight", -1]]],
    [key("ArrowUp"), [["highlight", -1]]],
    [key("Enter"), [["move", 42]], { highlight: 42 }],
    [key("t"), [["show", "trade"]]],
    [key("m"), [["show", "moves"]]],
    [key("r"), [["refresh"]]],
  ];
  for (const [e, want, over] of cases) {
    const { map, calls } = fakeSeason(over);
    assert.equal(handleKey(e, map), true, e.key);
    assert.deepEqual(calls, want, e.key);
  }
});

test("season: w, h, s and l show their views, [ the drawer, whatever the view", () => {
  assert.deepEqual(
    SEASON_VIEWS.map((v) => [v.key, v.id]),
    [
      ["w", "waivers"],
      ["h", "matchup"],
      ["s", "season"],
      ["l", "lineup"],
    ],
  );
  for (const view of ["waivers", "matchup", "season", "lineup"] as const) {
    const cases: [KeyLike, unknown[][]][] = [
      [key("w"), [["view", "waivers"]]],
      [key("h"), [["view", "matchup"]]],
      [key("s"), [["view", "season"]]],
      [key("l"), [["view", "lineup"]]],
      [key("["), [["views"]]],
      [key("/"), [["search"]]],
    ];
    for (const [e, want] of cases) {
      const { map, calls } = fakeSeason({ view });
      assert.equal(handleKey(e, map), true, e.key);
      assert.deepEqual(calls, want, `${e.key} in ${view}`);
    }
  }
});

test("season: the Waivers keys rest in the Matchup and Season views", () => {
  for (const view of ["matchup", "season"] as const) {
    for (const e of [key("j"), key("k"), key("ArrowDown"), key("ArrowUp"), key("Enter")]) {
      const { map, calls } = fakeSeason({ view, highlight: 42 });
      assert.equal(handleKey(e, map), false, e.key);
      assert.deepEqual(calls, [], e.key);
    }
  }
});

test("the views come back from the browser, or the defaults", () => {
  assert.deepEqual(parseViews(null), DEFAULT_VIEWS);
  assert.deepEqual(parseViews("{"), DEFAULT_VIEWS);
  assert.deepEqual(parseViews(JSON.stringify({ view: "matchup", shown: false })), { view: "matchup", shown: false });
  assert.deepEqual(parseViews(JSON.stringify({ view: "season", shown: true })), { view: "season", shown: true });
  assert.deepEqual(parseViews(JSON.stringify({ view: "bogus", shown: "no" })), DEFAULT_VIEWS);
  assert.deepEqual(DEFAULT_VIEWS, { view: "waivers", shown: true });
});

test("season: keys that must not act", () => {
  const none: [KeyLike, Partial<SeasonKeys>?][] = [
    [key("Enter")], // nothing highlighted
    [key("Enter", { target: { tagName: "BUTTON" } }), { highlight: 42 }],
    [key("r"), { refresh: null }], // a private league, or a refresh running
    [key("t", { target: field })],
    [key("m", { target: select })],
    [key("t", { ctrlKey: true })],
    [key("d")],
    [key("z")],
  ];
  for (const [e, over] of none) {
    const { map, calls } = fakeSeason(over);
    assert.equal(handleKey(e, map), false, e.key);
    assert.deepEqual(calls, [], e.key);
  }
});

test("season: Esc closes an open flag breakdown before the move drawer", () => {
  let moved = 0;
  const f = fakeSeason({ closeBreakdown: () => true, closeMove: () => (moved++, true) });
  handleKey(key("Escape"), f.map);
  assert.deepEqual([f.calls, moved], [[], 0]);
});

test("season: Esc leaves a field, then closes the move drawer, then collapses the panel", () => {
  let f = fakeSeason({ sheetOpen: true });
  handleKey(key("Escape"), f.map);
  assert.deepEqual(f.calls, [["sheet", false]]);
  const input = { ...field, blurred: 0 };
  f = fakeSeason({ closeMove: () => true });
  handleKey(key("Escape", { target: input }), f.map);
  assert.deepEqual([f.calls, input.blurred], [[], 1]);
  let closed = 0;
  f = fakeSeason({ closeMove: () => (closed++, true) });
  handleKey(key("Escape"), f.map);
  assert.deepEqual([f.calls, closed], [[], 1]);
  f = fakeSeason();
  handleKey(key("Escape"), f.map);
  assert.deepEqual(f.calls, [["collapse"]]);
});

test("season: ? opens the sheet, a key from it closes it", () => {
  let f = fakeSeason();
  handleKey(key("?"), f.map);
  assert.deepEqual(f.calls, [["sheet", true]]);
  f = fakeSeason({ sheetOpen: true });
  handleKey(key("t"), f.map);
  assert.deepEqual(f.calls, [["show", "trade"], ["sheet", false]]);
});

test("the Waivers highlight steps through the rows on show", () => {
  const rows = [11, 22, 33];
  assert.equal(stepHighlight(rows, null, 1), 11);
  assert.equal(stepHighlight(rows, null, -1), 33);
  assert.equal(stepHighlight(rows, 11, 1), 22);
  assert.equal(stepHighlight(rows, 33, 1), 33);
  assert.equal(stepHighlight(rows, 11, -1), 11);
  assert.equal(stepHighlight(rows, 99, 1), 11, "a row filtered away starts over");
  assert.equal(stepHighlight([], 11, 1), null);
});

test("each sheet names its screen's cards and lists its keys", () => {
  assert.ok(DRAFT_SHEET.cards.startsWith(`Cards are ${DRAFT_CARDS.map((c, i) => `${i + 1} ${c.title}`).join(" · ")},`));
  assert.ok(SEASON_SHEET.cards.startsWith(`Cards are ${SEASON_CARDS.map((c, i) => `${i + 1} ${c.title}`).join(" · ")},`));
  const listed = SEASON_SHEET.groups.flatMap((g) => g.rows.flatMap(([keys]) => keys));
  for (const k of ["1", "7", "⇧ 2", "]", "[", "w", "h", "s", "l", "x", "Esc", "/", "j", "k", "↓", "↑", "Enter", "t", "m", "r", "?"]) assert.ok(listed.includes(k), k);
});
