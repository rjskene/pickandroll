// A step card's view on the Explain screen (#337): the layout and which panels show. Pure, so
// `npm test` runs it under Node.

export type Layout = "side" | "stack";
export type Show = "both" | "fig" | "text";

export interface CardView {
  layout: Layout;
  show: Show;
}

/** Where this browser keeps the layout, beside the rail's fold. A hidden panel is never kept, so a
 * visit does not open on half a card. */
export const VIEW_KEY = "pickandroll.explain.view";

/** The kept layout; a value it does not know reads as side by side. */
export function savedLayout(saved: string | null): Layout {
  return saved === "stack" ? "stack" : "side";
}

/** A layout chosen: both panels come back, since the layout shows only with both. */
export function chooseLayout(layout: Layout): (v: CardView) => CardView {
  return () => ({ layout, show: "both" });
}

/** Panels chosen: the layout stays for when both come back. */
export function chooseShow(show: Show): (v: CardView) => CardView {
  return (v) => ({ ...v, show });
}

/** `v`: the other layout. */
export function flipLayout(v: CardView): CardView {
  return chooseLayout(v.layout === "side" ? "stack" : "side")(v);
}

const NEXT: Record<Show, Show> = { both: "fig", fig: "text", text: "both" };

/** `h`: both panels, the figure alone, the text alone, and round. */
export function cycleShow(v: CardView): CardView {
  return chooseShow(NEXT[v.show])(v);
}

/** The stage's classes: a hidden panel wins over the layout. */
export function stageClass(all: boolean, v: CardView): string {
  const view = v.show === "fig" ? " only-fig" : v.show === "text" ? " only-text" : v.layout === "stack" ? " stack" : "";
  return `ex-stage${all ? " all" : ""}${view}`;
}
