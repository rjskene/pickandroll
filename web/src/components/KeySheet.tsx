import type { Sheet } from "../keys";
import { Close } from "./icons";

function K({ children }: { children: string }) {
  return <kbd>{children}</kbd>;
}

/** The keyboard shortcut sheet (?): a screen's keys, from keys.ts. */
export default function KeySheet({ sheet, open, onClose }: { sheet: Sheet; open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-label="Keyboard shortcuts" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>KEYBOARD</h2>
          <span className="muted">{sheet.cards}</span>
          <span className="grow" />
          <button className="icon" aria-label="Close" onClick={onClose}>
            <Close />
          </button>
        </header>
        <div className="groups">
          {sheet.groups.map((g) => (
            <div key={g.title}>
              <span className="k">{g.title}</span>
              {g.rows.map(([keys, what]) => (
                <div key={what} className="krow">
                  <span className="keys">
                    {keys.map((k, i) => (k === "…" ? <span key={i} className="dim">…</span> : <K key={i}>{k}</K>))}
                  </span>
                  <span>{what}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
        <footer className="muted">{sheet.footer}</footer>
      </div>
    </div>
  );
}
