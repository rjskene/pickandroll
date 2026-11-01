// The glossary (#283): a term in a card opens the sheet on its definition; the sheet slides in
// from the right (up from the bottom on a phone); the full table ends the screen.
import { Fragment, createContext, useContext, useEffect, useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { Close } from "../components/icons";
import { GLOSSARY, termById } from "./terms";

const OpenTerm = createContext<(id: string) => void>(() => {});

export function GlossaryProvider({ onOpen, children }: { onOpen: (id: string) => void; children: ReactNode }) {
  return <OpenTerm.Provider value={onOpen}>{children}</OpenTerm.Provider>;
}

/** A defined term in the text: a `dfn` that opens the glossary on its definition. */
export function Term({ id, children }: { id: string; children?: ReactNode }) {
  const open = useContext(OpenTerm);
  const t = termById(id);
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open(id);
    }
  };
  return (
    <dfn className="ex-term" title={t ? `${t.term}: ${t.def}` : undefined} tabIndex={0} onClick={() => open(id)} onKeyDown={onKey}>
      {children ?? t?.term ?? id}
    </dfn>
  );
}

export function GlossarySheet({ open, term, onClose }: { open: boolean; term: string | null; onClose: () => void }) {
  const list = useRef<HTMLDListElement>(null);
  useEffect(() => {
    if (!open || !term) return;
    list.current?.querySelector(`#ex-def-${term}`)?.scrollIntoView({ block: "center" });
  }, [open, term]);
  return (
    <>
      <div className={`ex-backdrop${open ? " on" : ""}`} onClick={onClose} />
      <aside className={`ex-sheet${open ? " on" : ""}`} role="dialog" aria-label="Glossary" aria-hidden={!open}>
        <header>
          <h3>GLOSSARY</h3>
          <span className="muted">one line each; the full table ends the page</span>
          <button className="icon" aria-label="Close" title="Close (Esc)" onClick={onClose}>
            <Close />
          </button>
        </header>
        <div className="ex-sheet-list">
          <dl ref={list}>
            {GLOSSARY.map((g) => (
              <Fragment key={g.id}>
                <dt id={`ex-def-${g.id}`} className={g.id === term ? "flash" : ""}>
                  {g.term}
                </dt>
                <dd>{g.def}</dd>
              </Fragment>
            ))}
          </dl>
        </div>
      </aside>
    </>
  );
}

/** The definitions table at the end of the screen. */
export function GlossaryTable() {
  return (
    <section className="ex-gloss" aria-label="Definitions">
      <h3>Definitions</h3>
      <p className="muted">Every term the cards underline, one line each.</p>
      <table>
        <tbody>
          {GLOSSARY.map((g) => (
            <tr key={g.id} id={`ex-term-${g.id}`}>
              <th scope="row">{g.term}</th>
              <td>{g.def}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
