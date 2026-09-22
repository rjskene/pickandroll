import { useDraft } from "../draft";
import { Close } from "./icons";

function K({ children }: { children: string }) {
  return <kbd>{children}</kbd>;
}

const GROUPS: { title: string; rows: [string[], string][] }[] = [
  {
    title: "Cards",
    rows: [
      [["1", "…", "6"], "open that card in the top half; the same key again closes it"],
      [["⇧ 1", "…", "⇧ 6"], "open it in the bottom half (mouse: shift-click or right-click the rail icon)"],
      [["]"], "collapse the drawer to the rail, or bring it back with its two cards"],
      [["Esc"], "collapse the drawer; in a field it leaves the field first"],
      [["x"], "swap the top and bottom cards"],
    ],
  },
  {
    title: "Board",
    rows: [
      [["/"], "jump to search; Enter there drafts the first match"],
      [["↓", "j"], "move the highlight down"],
      [["↑", "k"], "move the highlight up"],
      [["Enter"], "draft the highlighted player to the team on the clock"],
      [["d"], "draft the recommended pick"],
      [["z"], "undo the last pick"],
      [["h"], "hide or show drafted players"],
    ],
  },
  {
    title: "Solver and simulation",
    rows: [
      [["r"], "re-solve now"],
      [["s"], "simulate the other teams up to my pick"],
      [["⇧ S"], "simulate one pick"],
      [["m"], "mock draft: run the whole draft, the other teams simulated and the solver drafting for you (never in a live draft)"],
      [["?"], "this sheet"],
    ],
  },
];

export default function KeySheet() {
  const d = useDraft();
  if (!d.sheetOpen) return null;
  return (
    <div className="sheet-backdrop" onClick={() => d.setSheetOpen(false)}>
      <div className="sheet" role="dialog" aria-label="Keyboard shortcuts" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>KEYBOARD</h2>
          <span className="muted">
            Cards are 1 Pick · 2 Alternatives · 3 Plan · 4 Team · 5 Log · 6 Solver, the numbers on the rail. Letters do nothing while you are typing in a field.
          </span>
          <span className="grow" />
          <button className="icon" aria-label="Close" onClick={() => d.setSheetOpen(false)}>
            <Close />
          </button>
        </header>
        <div className="groups">
          {GROUPS.map((g) => (
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
        <footer className="muted">Every key mirrors a visible control. Keys work while this sheet is open and close it. A pick made by key shows a toast with Undo for five seconds.</footer>
      </div>
    </div>
  );
}
