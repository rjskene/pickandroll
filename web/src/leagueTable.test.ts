import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// The leagues table's Record column (#392): its own column on a screen wide enough for it, under
// the place in the place's cell below 1640 px and on a phone, where the column goes and the table
// keeps the width it had.
const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const block = (from: number) => {
  let depth = 0;
  for (let i = css.indexOf("{", from); i < css.length; i++) {
    if (css[i] === "{") depth++;
    if (css[i] === "}" && --depth === 0) return css.slice(from, i + 1);
  }
  throw new Error("unclosed block");
};
const rule = (text: string, sel: string) => {
  const m = new RegExp(`(?:^|\\n)\\s*${sel.replace(/[.]/g, "\\.")} \\{([^}]*)\\}`).exec(text);
  return m ? m[1] : null;
};
const cols = (decl: string | null) => /--lt-cols: ([^;]+);/.exec(decl ?? "")?.[1].trim().split(/ (?![^(]*\))/) ?? [];
const minWidth = (decl: string | null) => Number(/min-width: (\d+)px/.exec(decl ?? "")?.[1]);
const phone = [...css.matchAll(/@media \(max-width: 1640px\) \{/g)].map((m) => block(m.index)).find((b) => b.includes(".lt-rec"));

test("the Record column follows the place on a wide screen and moves under it below 1640 px and on a phone (#392)", () => {
  assert.ok(phone, "a phone rule for the record");
  const wide = cols(rule(css, ".lt"));
  const narrow = cols(rule(phone, ".lt"));
  // One column more on a wide screen, right after the place's 78 px.
  assert.equal(wide.length, 12);
  assert.equal(narrow.length, 11);
  assert.deepEqual([...wide.slice(0, 5), ...wide.slice(6)], narrow);
  assert.equal(wide[4], "78px");
  assert.equal(minWidth(rule(css, ".lt")) - minWidth(rule(phone, ".lt")), Number.parseInt(wide[5]) + 14);
  // Narrower, the table is as wide as before the column: 1360 px, scrolled sideways in its section.
  assert.equal(minWidth(rule(phone, ".lt")), 1360);
  assert.match(rule(css, ".lt-scroll") ?? "", /overflow-x: auto/);
  // The record's own cell shows on a wide screen, the one under the place on a phone.
  assert.match(rule(css, ".lt-rec-under") ?? "", /display: none/);
  assert.match(rule(phone, ".lt-rec") ?? "", /display: none/);
  assert.match(rule(phone, ".lt-rec-under") ?? "", /display: block/);
  // A league not read yet spans the columns between its name and its read either way.
  assert.equal(rule(css, ".lt-wide")?.trim(), "grid-column: span 8;");
  assert.equal(rule(phone, ".lt-wide")?.trim(), "grid-column: span 7;");
});
