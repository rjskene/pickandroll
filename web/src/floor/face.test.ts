// The in-season page's faces (#461): list by default, the flip, and where the flip icon shows.
import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_FACE, faceShown, flipFace, flipLabel, hasFlip } from "./face.ts";

test("the page opens on the floor and f flips between the faces (#461, #462)", () => {
  assert.equal(DEFAULT_FACE, "floor");
  assert.equal(faceShown(DEFAULT_FACE, "season", true), "list");
  assert.equal(flipFace("list"), "floor");
  assert.equal(flipFace(flipFace("list")), "list");
  assert.match(flipLabel("list"), /floor/);
  assert.match(flipLabel("floor"), /list/);
});

test("the floor shows only on the in-season page and never on a phone (#461)", () => {
  assert.equal(faceShown("floor", "season", false), "floor");
  assert.equal(faceShown("floor", "season", true), "list");
  assert.equal(faceShown("floor", "draft", false), "list");
  assert.equal(faceShown("list", "season", false), "list");
  assert.equal(hasFlip("season", false), true);
  assert.equal(hasFlip("season", true), false);
  assert.equal(hasFlip("draft", false), false);
});
