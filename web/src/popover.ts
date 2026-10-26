// Where an "i" opens its explanation (#185): pure, so Node's runner tests it without a DOM.

/** The explanation's width, and the flags legend's. */
export const POPOVER_WIDTH = 340;
export const WIDE_WIDTH = 440;
/** The room kept free at the window's edges, the gap to the button and the least height. */
const EDGE = 8;
const ROOM = 16;
const GAP = 6;
const MIN_HEIGHT = 120;

export interface Box {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface Placement {
  left: number;
  width: number;
  maxHeight: number;
  /** Below the button: its top; above it: its bottom, from the window's bottom edge. */
  top: number | null;
  bottom: number | null;
}

/** Below the button, or above it when the explanation is taller than the room below and there is
 * more room above; as tall as that room (at least 120 px), and scrolling past it. Its width is
 * clamped to the window's less 16 px, and it is kept 8 px inside the window: from the button's
 * left edge, or its right edge with ``align="right"``. */
export function placePopover(
  button: Box,
  height: number,
  view: { width: number; height: number },
  align: "left" | "right" = "left",
  want: number = POPOVER_WIDTH,
): Placement {
  const width = Math.max(0, Math.min(want, view.width - ROOM));
  const below = view.height - button.bottom - ROOM;
  const above = button.top - ROOM;
  const up = height > below && above > below;
  const from = align === "right" ? button.right - width : button.left;
  const left = Math.max(EDGE, Math.min(from, view.width - width - EDGE));
  return {
    left,
    width,
    maxHeight: Math.max(MIN_HEIGHT, up ? above : below),
    top: up ? null : button.bottom + GAP,
    bottom: up ? view.height - button.top + GAP : null,
  };
}

/** Whether the button has left its scrolling column's visible area: the explanation then closes
 * rather than float over a row that has gone. */
export function outside(button: Box, column: Box): boolean {
  return button.bottom <= column.top || button.top >= column.bottom || button.right <= column.left || button.left >= column.right;
}
