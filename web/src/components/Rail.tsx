import { CARDS, useDraft } from "../draft";
import { CARD_ICONS, Chevron } from "./icons";

export default function Rail() {
  const d = useDraft();
  const { top, bottom, collapsed } = d.drawer;
  return (
    <nav className="rail" aria-label="Cards">
      {CARDS.map((c, i) => {
        const on = !collapsed && (top === c.id || bottom === c.id);
        return (
          <button
            key={c.id}
            className={on ? "on" : ""}
            aria-pressed={on}
            title={`${c.title}: ${c.blurb} (${i + 1}, shift+${i + 1} for the bottom half)`}
            onClick={(e) => d.openCard(c.id, e.shiftKey ? "bottom" : "top")}
          >
            {CARD_ICONS[c.id]}
            <span className="num">{i + 1}</span>
          </button>
        );
      })}
      <span className="grow" />
      <button title="Keyboard shortcuts (?)" aria-label="Keyboard shortcuts" onClick={() => d.setSheetOpen(true)}>
        <span className="q">?</span>
      </button>
      <button title={d.drawerOpen ? "Collapse the drawer (])" : "Open the drawer (])"} aria-label={d.drawerOpen ? "Collapse the drawer" : "Open the drawer"} onClick={d.toggleDrawer}>
        <Chevron dir={d.drawerOpen ? "right" : "left"} />
      </button>
    </nav>
  );
}
