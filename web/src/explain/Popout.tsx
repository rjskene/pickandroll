// The popouts (#282): a step's worked example, or a formula in words, formally, with every
// variable and a sample worked step by step; in a sheet that slides in like the glossary's (up
// from the bottom on a phone). One popout is open at a time; the screen holds which.
import type { ReactNode } from "react";
import { Close } from "../components/icons";
import { Bullets } from "./Bullets";
import { shown } from "./formulas";
import MathView from "./MathView";
import type { Example, ExampleTable, Formula } from "./types";

interface DrawerProps {
  open: boolean;
  /** Which popout is shown: a new one opens scrolled to its top. */
  view: string;
  label: string;
  title: string;
  sub?: string;
  onClose: () => void;
  children: ReactNode;
}

/** The sheet: a heading, a close button, the body scrolling under it. */
export function Drawer({ open, view, label, title, sub, onClose, children }: DrawerProps) {
  return (
    <>
      <div className={`ex-backdrop${open ? " on" : ""}`} onClick={onClose} />
      <aside className={`ex-sheet wide${open ? " on" : ""}`} role="dialog" aria-label={label} aria-hidden={!open}>
        <header>
          <div className="ex-pop-head">
            <h3>{title}</h3>
            {sub && <span className="muted">{sub}</span>}
          </div>
          <button className="icon" aria-label="Close" title="Close (Esc)" onClick={onClose}>
            <Close />
          </button>
        </header>
        <div className="ex-pop" key={view}>
          {children}
        </div>
      </aside>
    </>
  );
}

export function XTable({ table }: { table: ExampleTable }) {
  const num = new Set(table.num ?? []);
  return (
    <div className="ex-xwrap">
      <table className="ex-xtable">
        <thead>
          <tr>
            {table.head.map((h, i) => (
              <th key={i} className={num.has(i) ? "num" : undefined} scope="col">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} className={num.has(j) ? "num" : undefined}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A step's worked example: what it sets up, the table, what to read from it. */
export function ExampleBody({ example }: { example: Example }) {
  return (
    <>
      <h4 className="ex-pop-title">{example.title}</h4>
      <Bullets bullets={example.lead} className="ex-bullets ex-pop-bullets" />
      {example.table && <XTable table={example.table} />}
      {example.read && example.read.length > 0 && (
        <>
          <h5 className="ex-pop-sec">Reading it</h5>
          <Bullets bullets={example.read} className="ex-bullets ex-pop-bullets" />
        </>
      )}
      <p className="ex-pop-note">Fictional players and made-up numbers; the rules are the code's.</p>
    </>
  );
}

/** A formula: what it does, the definition, every variable, a sample worked step by step. */
export function FormulaBody({ formula: f }: { formula: Formula }) {
  const last = f.steps.length - 1;
  return (
    <>
      <h4 className="ex-pop-title">{f.name}</h4>
      <p className="ex-pop-what">{f.what}</p>
      <div className="ex-math-lines">
        {f.lines.map((l, i) => (
          <div key={i} className="ex-math-line">
            <MathView node={l} block />
          </div>
        ))}
      </div>
      <h5 className="ex-pop-sec">Every variable</h5>
      <div className="ex-xwrap">
        <table className="ex-xtable ex-vars">
          <tbody>
            {f.vars.map((x, i) => (
              <tr key={i}>
                <th scope="row">
                  <MathView node={x.sym} />
                </th>
                <td>{x.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h5 className="ex-pop-sec">A sample, step by step</h5>
      <div className="ex-xwrap">
        <table className="ex-xtable ex-vars">
          <tbody>
            {f.given.map((g, i) => (
              <tr key={i}>
                <th scope="row">
                  <MathView node={g.sym} />
                </th>
                <td className="num">{g.value}</td>
                <td>{g.say}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ol className="ex-work">
        {f.steps.map((s, i) => (
          <li key={i} className={i === last ? "last" : undefined}>
            <span className="ex-say">{s.say}</span>
            <span className="ex-calc">
              <MathView node={s.math} />
              <span className="ex-eq">=</span>
              <b>{shown(s.value, s.shown)}</b>
            </span>
          </li>
        ))}
      </ol>
      <p className="ex-pop-note">From {f.source}. A fictional sample; the rule is the code's.</p>
    </>
  );
}
