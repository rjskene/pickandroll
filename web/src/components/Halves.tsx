import { useRef, type CSSProperties, type ReactNode } from "react";
import { DRAWER_WIDTH, type CardDef, type Half } from "../keys";
import type { DrawerApi } from "../useKeys";
import { Chevron, Grip, GripV, Swap } from "./icons";

/** The drawer state and changes the frame uses (the draft's DraftApi has them too). */
type HalvesApi<Id extends string> = Pick<DrawerApi<Id>, "drawer" | "drawerOpen" | "closeCard" | "swapHalves" | "setSplit" | "setWidth">;

/** What a card shows in its half: its body, and optionally its own title, a note and an action
 * in its header. */
export interface Face {
  body: ReactNode;
  title?: string;
  note?: string;
  action?: ReactNode;
}

function CardFrame<Id extends string>({
  d,
  cards,
  id,
  half,
  face,
  style,
  hidden,
}: {
  d: HalvesApi<Id>;
  cards: CardDef<Id>[];
  id: Id;
  half: Half;
  face: Face;
  style?: CSSProperties;
  hidden?: boolean;
}) {
  const i = cards.findIndex((c) => c.id === id);
  const title = cards[i].title;
  return (
    <section className="card" style={style} aria-label={title} hidden={hidden}>
      <header>
        <h2>{face.title ?? title.toUpperCase()}</h2>
        <span className="dim">
          {face.note ? `${face.note} · ` : ""}
          {half} · card {i + 1} of {cards.length}
        </span>
        <span className="grow" />
        {face.action}
        {d.drawer.top && d.drawer.bottom && (
          <button className="icon" aria-label="Swap the top and bottom cards" title="Swap halves (x)" onClick={d.swapHalves}>
            <Swap />
          </button>
        )}
        <button className="icon" aria-label={`Close ${title}`} title={`Close (${i + 1})`} onClick={() => d.closeCard(id)}>
          <Chevron dir={half === "top" ? "up" : "down"} />
        </button>
      </header>
      <div className="body">{face.body}</div>
    </section>
  );
}

/** A screen's drawer: the card in each half, a draggable split between them and a draggable
 * left edge. ``keep`` are cards that stay mounted, hidden, while off show (a trade being put
 * together survives a look at the moves); with any, the collapsed drawer stays mounted too. */
export default function Halves<Id extends string>({
  d,
  cards,
  face,
  keep = [],
  className,
}: {
  d: HalvesApi<Id>;
  cards: CardDef<Id>[];
  face: (id: Id, half: Half) => Face;
  keep?: Id[];
  className?: string;
}) {
  const ref = useRef<HTMLElement | null>(null);
  const open = d.drawerOpen;
  if (!open && keep.length === 0) return null;
  const { top, bottom, split, width } = d.drawer;

  const startDrag = (e: React.PointerEvent) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const move = (ev: PointerEvent) => d.setSplit((ev.clientY - rect.top) / rect.height);
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    e.preventDefault();
  };

  const startWidthDrag = (e: React.PointerEvent) => {
    const startX = e.clientX;
    const startWidth = width;
    const move = (ev: PointerEvent) => d.setWidth(startWidth + (startX - ev.clientX));
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    };
    // No text selection or cursor flicker while the pointer crosses the board.
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    e.preventDefault();
  };

  // One keyed list, so a kept card moving between a half and the hidden rest keeps its state.
  const shownTop = open ? top : null;
  const shownBottom = open ? bottom : null;
  const items: ReactNode[] = [];
  if (shownTop) {
    items.push(<CardFrame key={shownTop} d={d} cards={cards} id={shownTop} half="top" face={face(shownTop, "top")} style={{ flex: shownBottom ? `${split} 1 0%` : "1 1 0%" }} />);
  }
  if (shownTop && shownBottom) {
    items.push(
      <div key="divider" className="divider" role="separator" aria-orientation="horizontal" title="Drag to resize · x swaps the halves" onPointerDown={startDrag}>
        <Grip />
      </div>,
    );
  }
  if (shownBottom) {
    items.push(<CardFrame key={shownBottom} d={d} cards={cards} id={shownBottom} half="bottom" face={face(shownBottom, "bottom")} style={{ flex: shownTop ? `${1 - split} 1 0%` : "1 1 0%" }} />);
  }
  for (const id of keep) {
    if (id !== shownTop && id !== shownBottom) items.push(<CardFrame key={id} d={d} cards={cards} id={id} half="top" face={face(id, "top")} hidden />);
  }

  return (
    <>
      {open && (
        <div
          className="vdivider"
          role="separator"
          aria-orientation="vertical"
          title="Drag to resize the drawer · double-click resets it"
          onPointerDown={startWidthDrag}
          onDoubleClick={() => d.setWidth(DRAWER_WIDTH)}
        >
          <GripV />
        </div>
      )}
      <aside className={className ? `drawer ${className}` : "drawer"} ref={ref} style={{ width }} hidden={!open}>
        {items}
      </aside>
    </>
  );
}
