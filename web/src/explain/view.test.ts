import assert from "node:assert/strict";
import { test } from "node:test";
import { chooseLayout, chooseShow, cycleShow, flipLayout, savedLayout, stageClass, type CardView } from "./view.ts";

const SIDE: CardView = { layout: "side", show: "both" };
const STACK: CardView = { layout: "stack", show: "both" };

test("the kept layout reads as stacked only when it says so", () => {
  assert.equal(savedLayout("stack"), "stack");
  assert.equal(savedLayout("side"), "side");
  assert.equal(savedLayout(null), "side");
  assert.equal(savedLayout("sideways"), "side");
});

test("choosing a layout brings both panels back", () => {
  assert.deepEqual(chooseLayout("stack")({ layout: "side", show: "fig" }), STACK);
  assert.deepEqual(chooseLayout("side")({ layout: "stack", show: "text" }), SIDE);
  assert.deepEqual(flipLayout({ layout: "side", show: "text" }), STACK);
  assert.deepEqual(flipLayout(STACK), SIDE);
});

test("the panels key goes both, figure, text and round, and keeps the layout", () => {
  const one = cycleShow(STACK);
  const two = cycleShow(one);
  assert.deepEqual([one.show, two.show, cycleShow(two).show], ["fig", "text", "both"]);
  assert.equal(two.layout, "stack");
});

test("choosing panels keeps the layout", () => {
  assert.deepEqual(chooseShow("text")(STACK), { layout: "stack", show: "text" });
});

test("the stage carries the view, a hidden panel winning over the layout", () => {
  assert.equal(stageClass(false, SIDE), "ex-stage");
  assert.equal(stageClass(false, STACK), "ex-stage stack");
  assert.equal(stageClass(true, STACK), "ex-stage all stack");
  assert.equal(stageClass(false, { layout: "stack", show: "fig" }), "ex-stage only-fig");
  assert.equal(stageClass(true, { layout: "side", show: "text" }), "ex-stage all only-text");
});
