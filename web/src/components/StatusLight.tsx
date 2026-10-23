import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type StatusPayload, type StatusState } from "../api";
import { leagueOf, lightOf, sheetSections, STATE_TONE, STATE_WORD, statusLine, when } from "../seasonStatus";
import { Close } from "./icons";

/** The freshness light's payload (#153), one query for the league page and the grid. */
export function useSeasonStatus() {
  return useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 60_000 });
}

/** The dot and its word for a league: the hover line on hover, its sheet on click. */
export function StatusDot({ p, league, onOpen }: { p: StatusPayload | undefined; league: string; onOpen: () => void }) {
  const state = lightOf(p, league);
  if (!p || !state) return null;
  return (
    <button
      className="light"
      title={statusLine(p, league, new Date())}
      aria-label={`Updates ${STATE_WORD[state]}: open the details`}
      onClick={(e) => {
        e.stopPropagation();
        onOpen();
      }}
    >
      <span className={`dot ${STATE_TONE[state]}`} />
      <span className={STATE_TONE[state]}>{STATE_WORD[state]}</span>
    </button>
  );
}

function Word({ state }: { state: StatusState }) {
  return <span className={STATE_TONE[state]}>{STATE_WORD[state]}</span>;
}

/** The light's details (#153), in the knob sheet's shape and read-only: the daily run, the
 * Basketball Monster exports, the league's Yahoo reads and its recommendations, each row with
 * its time, state and reason; Refresh for a public league. Esc or the shade closes it. */
export function StatusSheet({
  p,
  league,
  onClose,
  refresh,
}: {
  p: StatusPayload;
  league: string;
  onClose: () => void;
  refresh?: { run: () => void; running: boolean; title: string };
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.focus(), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // The page's own Esc (its shortcuts on the window) waits for the next one.
      e.stopPropagation();
      onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  const now = new Date();
  const l = leagueOf(p, league);
  const state = lightOf(p, league);
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div ref={box} tabIndex={-1} className="sheet pg-sheet status-sheet" role="dialog" aria-label="Updates" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>Updates · {l?.name ?? `League ${league}`}</h2>
          <span className="grow" />
          {refresh && (
            <button className="small" disabled={refresh.running} onClick={refresh.run} title={refresh.title}>
              {refresh.running ? "Refreshing…" : "Refresh"}
            </button>
          )}
          <button className="icon" aria-label="Close" onClick={onClose}>
            <Close />
          </button>
        </header>
        <div className="pg-sheet-body">
          <p className="muted">
            {state && <Word state={state} />} · {statusLine(p, league, now)} · the daily run is due {when(p.due_at, now)} · checked {when(p.generated_at, now)}
          </p>
          {l?.error && <p className="bad">{l.error}</p>}
          {sheetSections(p, league, now).map((s) => (
            <div key={s.title} className="status-section">
              <div className="k">
                <span className={`dot ${STATE_TONE[s.state]}`} /> {s.title} · <Word state={s.state} />
              </div>
              <table className="status-table">
                <tbody>
                  {s.rows.map((r) => (
                    <tr key={r.key}>
                      <td>{r.label}</td>
                      <td className="num">{r.time}</td>
                      <td>
                        {r.state && (
                          <>
                            <Word state={r.state} />{" "}
                          </>
                        )}
                        <span className="muted">{r.reason}</span>
                      </td>
                      <td className="dim">{r.detail ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
