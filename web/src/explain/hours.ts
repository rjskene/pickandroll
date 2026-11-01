// The strip's hour line (#286): one dot per step at its hour on a 24-hour axis, dots minutes
// apart nudged to keep a minimum gap, the last one never past the right end; the labels under
// the dots drop to a lower row where they would otherwise touch. No React, so the test runs
// under Node.

/** The x of each hour on the axis from `left` to `right`, at least `gap` apart. */
export function hourXs(hours: number[], left: number, right: number, gap: number): number[] {
  const xs = hours.map((h) => left + (h / 24) * (right - left));
  for (let i = 1; i < xs.length; i++) xs[i] = Math.max(xs[i], xs[i - 1] + gap);
  if (xs.length) xs[xs.length - 1] = Math.min(xs[xs.length - 1], right);
  for (let i = xs.length - 2; i >= 0; i--) xs[i] = Math.min(xs[i], xs[i + 1] - gap);
  return xs;
}

export type Anchor = "start" | "middle" | "end";

/** How a label sits on its dot: flush with the axis at either edge, centred elsewhere. */
export function hourAnchor(x: number, left: number, right: number): Anchor {
  return x < left + 40 ? "start" : x > right - 40 ? "end" : "middle";
}

/** The extent of a label of `w` px at `x`, by its anchor. */
function extent(x: number, w: number, anchor: Anchor): [number, number] {
  const x0 = anchor === "start" ? x : anchor === "end" ? x - w : x - w / 2;
  return [x0, x0 + w];
}

/** The row of each label (0 the top): the first row where it clears the labels already there by
 * `gap`, the last row when none does. `xs` ascend; a label's width is its length times `charW`. */
export function labelRows(xs: number[], labels: string[], anchors: Anchor[], charW: number, gap: number, rows = 3): number[] {
  const ends: number[] = [];
  return xs.map((x, i) => {
    const [x0, x1] = extent(x, labels[i].length * charW, anchors[i]);
    let row = 0;
    while (row < rows - 1 && ends[row] !== undefined && ends[row] + gap > x0) row++;
    ends[row] = x1;
    return row;
  });
}

/** The axis ticks: every three hours. */
export function hourTicks(left: number, right: number): { h: number; x: number }[] {
  const out: { h: number; x: number }[] = [];
  for (let h = 0; h <= 24; h += 3) out.push({ h, x: left + (h / 24) * (right - left) });
  return out;
}
