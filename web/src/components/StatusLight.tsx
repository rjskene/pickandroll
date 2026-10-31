import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type SeasonSummary, type StatusPayload, type StatusState } from "../api";
import { ageLabel, refreshNote } from "../season";
import { leagueOf, lightOf, overviewLine, sharedSections, sheetSections, STATE_TONE, STATE_WORD, STATES, statusLine, when, type SheetSection } from "../seasonStatus";
import { Close, StatusGlyph } from "./icons";

/** The freshness light's payload (#153), one query for the league page and the grid. */
export function useSeasonStatus() {
  return useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 60_000 });
}

/** The status icon (#253): a check, a clock or a warning in its tone, never colour alone (the
 * sheet's legend names each); the hover line on hover, the sheet on click. */
export function StatusIcon({ state, title, onOpen }: { state: StatusState; title: string; onOpen: () => void }) {
  return (
    <button
      className={`icon light ${STATE_TONE[state]}`}
      title={title}
      aria-label={`Updates ${STATE_WORD[state]}: open the details`}
      onClick={(e) => {
        e.stopPropagation();
        onOpen();
      }}
    >
      <StatusGlyph state={state} />
    </button>
  );
}

/** A league's icon: its light and hover line; nothing before the status reads. */
export function LeagueStatus({ p, league, onOpen }: { p: StatusPayload | undefined; league: string; onOpen: () => void }) {
  const state = lightOf(p, league);
  if (!p || !state) return null;
  return <StatusIcon state={state} title={statusLine(p, league, new Date())} onOpen={onOpen} />;
}

function Word({ state }: { state: StatusState }) {
  return <span className={STATE_TONE[state]}>{STATE_WORD[state]}</span>;
}

/** A state's glyph and word, for the section headers and the legend. */
function Mark({ state }: { state: StatusState }) {
  return (
    <span className={`status-mark ${STATE_TONE[state]}`}>
      <StatusGlyph state={state} size={14} />
      {STATE_WORD[state]}
    </span>
  );
}

function Legend() {
  return (
    <p className="status-legend" aria-label="What the icons mean">
      {STATES.map((s) => (
        <Mark key={s} state={s} />
      ))}
    </p>
  );
}

function Sections({ sections }: { sections: SheetSection[] }) {
  return sections.map((s) => (
    <div key={s.title} className="status-section">
      <div className="k">
        {s.title} · <Mark state={s.state} />
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
  ));
}

/** Esc for a sheet: the page's own Esc (its shortcuts on the window) waits for the next one. */
function useEsc(onEsc: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onEsc();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onEsc]);
}

/** The light's details (#153), in the knob sheet's shape and read-only: the daily run, the
 * Basketball Monster exports, the league's Yahoo reads and its recommendations, each row with
 * its time, state and reason; Refresh for a public league. ``note`` is the top line, the read's
 * age or the refresh's step (#253: the league page's words beside the icon moved here). Esc
 * or the shade closes it; opened from the overview, Esc and Back return there. */
export function StatusSheet({
  p,
  league,
  onClose,
  onBack,
  note,
  refresh,
}: {
  p: StatusPayload;
  league: string;
  onClose: () => void;
  onBack?: () => void;
  note?: string;
  refresh?: { run: () => void; running: boolean; title: string };
}) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.focus(), []);
  useEsc(onBack ?? onClose);
  const now = new Date();
  const l = leagueOf(p, league);
  const state = lightOf(p, league);
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div ref={box} tabIndex={-1} className="sheet pg-sheet status-sheet" role="dialog" aria-label="Updates" onClick={(e) => e.stopPropagation()}>
        <header>
          {onBack && (
            <button className="link" onClick={onBack} title="Every league's updates (Esc)">
              ← all leagues
            </button>
          )}
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
          {note && <p className="status-note">{note}</p>}
          <p className="muted">
            {state && <Word state={state} />} · {statusLine(p, league, now)} · the daily run is due {when(p.due_at, now)} · checked {when(p.generated_at, now)}
          </p>
          {l?.error && <p className="bad">{l.error}</p>}
          <Legend />
          <Sections sections={sheetSections(p, league, now)} />
        </div>
      </div>
    </div>
  );
}

/** The landing's overview (#253): the daily run and the exports every league shares, then one
 * row per league in the landing table's order with its icon, its Yahoo read and its hover line.
 * A league's row opens its own sheet in place; Esc there returns here. */
export function OverviewSheet({ p, leagues, now, onClose }: { p: StatusPayload; leagues: SeasonSummary[]; now: number; onClose: () => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const back = () => setOpen(null);
  if (open) return <StatusSheet p={p} league={open} onClose={onClose} onBack={back} />;
  return <Overview p={p} leagues={leagues} now={now} onClose={onClose} onLeague={setOpen} />;
}

function Overview({ p, leagues, now, onClose, onLeague }: { p: StatusPayload; leagues: SeasonSummary[]; now: number; onClose: () => void; onLeague: (league: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.focus(), []);
  useEsc(onClose);
  const date = new Date(now);
  const named = leagues.map((s) => ({ league: s.league, name: leagueOf(p, s.league)?.name ?? s.name ?? `League ${s.league}` }));
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div ref={box} tabIndex={-1} className="sheet pg-sheet status-sheet" role="dialog" aria-label="Updates" onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>Updates · all leagues</h2>
          <span className="grow" />
          <button className="icon" aria-label="Close" onClick={onClose}>
            <Close />
          </button>
        </header>
        <div className="pg-sheet-body">
          <p className="muted">
            <Word state={p.state} /> · {overviewLine(p, named, date)} · the daily run is due {when(p.due_at, date)} · checked {when(p.generated_at, date)}
          </p>
          <Legend />
          <Sections sections={sharedSections(p, date)} />
          <div className="status-section">
            <div className="k">Leagues · in the table's order</div>
            <table className="status-table">
              <tbody>
                {leagues.map((s, i) => {
                  const state = lightOf(p, s.league) ?? "amber";
                  const read = refreshNote(s.refresh) || (s.has_snapshot ? `Yahoo read ${ageLabel(s.updated_at, now)}` : "not read yet");
                  return (
                    <tr key={s.league}>
                      <td>
                        <button className="link" onClick={() => onLeague(s.league)} title="This league's updates">
                          {named[i].name}
                        </button>
                      </td>
                      <td>
                        <Mark state={state} />
                      </td>
                      <td className="num">{read}</td>
                      <td className="muted">{statusLine(p, s.league, date)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
