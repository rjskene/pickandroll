import type { ReactElement } from "react";
import type { CardDef, Half } from "../keys";
import { Chevron } from "./icons";

/** The right-hand rail of a screen's cards (#109): one numbered button per card, pressed while
 * the card is on show, then the key sheet and the drawer's collapse chevron. A click opens the
 * card in the top half; shift-click or right-click in the bottom half, where it has halves. */
export default function Rail<Id extends string>({
  cards,
  icons,
  on,
  onOpen,
  onSheet,
  open,
  onToggle,
  noun = "drawer",
}: {
  cards: CardDef<Id>[];
  icons: Record<Id, ReactElement>;
  on: (id: Id) => boolean;
  onOpen: (id: Id, half: Half) => void;
  onSheet: () => void;
  /** Whether the drawer is open (the chevron collapses it) or collapsed (it brings it back). */
  open: boolean;
  onToggle: () => void;
  /** What the chevron collapses: the draft's drawer, the league page's panel. */
  noun?: string;
}) {
  return (
    <nav className="rail" aria-label="Cards">
      {cards.map((c, i) => {
        const pressed = on(c.id);
        const keys =
          c.halves === false
            ? `Key ${i + 1} or click.`
            : `Key ${i + 1} or click: top half. Shift+${i + 1}, shift-click or right-click: bottom half.`;
        return (
          <button
            key={c.id}
            className={pressed ? "on" : ""}
            aria-pressed={pressed}
            aria-label={c.title}
            title={`${c.title}: ${c.blurb}. ${keys}`}
            onClick={(e) => onOpen(c.id, e.shiftKey ? "bottom" : "top")}
            onContextMenu={(e) => {
              e.preventDefault();
              onOpen(c.id, "bottom");
            }}
          >
            {icons[c.id]}
            <span className="num">{i + 1}</span>
          </button>
        );
      })}
      <span className="grow" />
      <button title="Keyboard shortcuts (?)" aria-label="Keyboard shortcuts" onClick={onSheet}>
        <span className="q">?</span>
      </button>
      <button title={open ? `Collapse the ${noun} (])` : `Open the ${noun} (])`} aria-label={open ? `Collapse the ${noun}` : `Open the ${noun}`} onClick={onToggle}>
        <Chevron dir={open ? "right" : "left"} />
      </button>
    </nav>
  );
}
