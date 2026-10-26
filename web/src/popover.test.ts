// Node's own test runner with its built-in type stripping (`npm test`), as format.test.ts.
import assert from "node:assert/strict";
import { test } from "node:test";
import { outside, placePopover, POPOVER_WIDTH, WIDE_WIDTH } from "./popover.ts";

const VIEW = { width: 1280, height: 800 };
// A 16 px "i" at (x, y).
const at = (x: number, y: number) => ({ left: x, right: x + 16, top: y, bottom: y + 16 });

test("an explanation opens below its button, 6 px under it, as tall as the room below", () => {
  const p = placePopover(at(100, 100), 200, VIEW);
  assert.deepEqual(p, { left: 100, width: POPOVER_WIDTH, maxHeight: 800 - 116 - 16, top: 122, bottom: null });
});

test("it opens above when it is taller than the room below and there is more room above", () => {
  // The bottom of a scrolled column: 40 px below the button, 700 above.
  const p = placePopover(at(100, 744), 300, VIEW);
  assert.equal(p.top, null);
  assert.equal(p.bottom, 800 - 744 + 6);
  assert.equal(p.maxHeight, 744 - 16);
  // It fits below: below, whatever the room above.
  assert.equal(placePopover(at(100, 500), 200, VIEW).top, 522);
});

test("it is at least 120 px tall, and scrolls past that", () => {
  const p = placePopover(at(100, 60), 400, { width: 1280, height: 160 });
  assert.equal(p.top, 82);
  assert.equal(p.maxHeight, 120);
});

test("right-aligned it ends at the button's right edge; either way it stays 8 px inside the window", () => {
  assert.equal(placePopover(at(900, 100), 100, VIEW, "right").left, 916 - POPOVER_WIDTH);
  // An "i" near the right edge: pulled in so the explanation never spills off-screen.
  assert.equal(placePopover(at(1250, 100), 100, VIEW).left, 1280 - POPOVER_WIDTH - 8);
  // Near the left edge, right-aligned: pushed back in.
  assert.equal(placePopover(at(20, 100), 100, VIEW, "right").left, 8);
});

test("its width is clamped to the window's less 16 px, the legend's too", () => {
  const phone = { width: 375, height: 800 };
  assert.equal(placePopover(at(20, 100), 100, VIEW, "left", WIDE_WIDTH).width, WIDE_WIDTH);
  const p = placePopover(at(300, 100), 100, phone, "left", WIDE_WIDTH);
  assert.equal(p.width, 375 - 16);
  assert.equal(p.left, 8);
  assert.equal(placePopover(at(20, 100), 100, phone).width, POPOVER_WIDTH);
});

test("a button scrolled out of its column's view is outside it; one still showing is not", () => {
  const column = { left: 0, right: 600, top: 100, bottom: 700 };
  assert.equal(outside(at(100, 300), column), false);
  assert.equal(outside(at(100, 90), column), false);
  assert.equal(outside(at(100, 80), column), true);
  assert.equal(outside(at(100, 700), column), true);
  assert.equal(outside(at(600, 300), column), true);
});
