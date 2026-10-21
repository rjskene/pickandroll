import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { draftDay, finishedDrafts } from "../format";
import DraftsAhead from "./DraftsAhead";
import LiveDrafts from "./LiveDrafts";
import OpenSessions from "./OpenSessions";
import SessionSetup from "./SessionSetup";
import { Close } from "./icons";

export type DrawerView = "drafts" | "new";

/** The in-season page's Drafts drawer (#108): the drafts ahead with Arm, the live drafts, the
 * finished drafts (no Arm and no armed state), the sessions on this server, and the New draft
 * form. Esc or the shade closes it. */
export default function DraftsDrawer({
  view,
  setView,
  setup,
  onSetUp,
  onClose,
  onOpenSession,
  now,
}: {
  view: DrawerView;
  setView: (v: DrawerView) => void;
  setup: { key: number; league?: string };
  onSetUp: (league: string) => void;
  onClose: () => void;
  onOpenSession: (id: string) => void;
  now: number;
}) {
  const leagues = useQuery({ queryKey: ["leagues"], queryFn: api.leagues, refetchInterval: 30_000 });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: api.rooms, refetchInterval: 5000 });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const finished = finishedDrafts(leagues.data ?? [], rooms.data ?? [], now);
  return (
    <>
      <div className="shade" onClick={onClose} />
      <aside className="slide" role="dialog" aria-label="Drafts">
        <header>
          <h2>DRAFTS</h2>
          <span className="grow" />
          {view === "new" ? (
            <button className="small" onClick={() => setView("drafts")}>
              Drafts
            </button>
          ) : (
            <button className="small primary" onClick={() => setView("new")}>
              New draft
            </button>
          )}
          <button className="icon" aria-label="Close the drafts drawer" title="Close (Esc)" onClick={onClose}>
            <Close />
          </button>
        </header>
        <div className="body">
          {view === "new" ? (
            <SessionSetup key={setup.key} initialLeague={setup.league} onCreated={(s) => onOpenSession(s.id)} />
          ) : (
            <>
              <div className="drawer-section">
                <span className="k">Ahead</span>
                <DraftsAhead now={now} onOpen={onOpenSession} onSetUp={onSetUp} />
              </div>
              <LiveDrafts onOpen={onOpenSession} />
              <div className="drawer-section">
                <span className="k">Finished · {finished.length}</span>
                {finished.length ? (
                  <table className="finished">
                    <tbody>
                      {finished.map((l) => (
                        <tr key={l.league}>
                          <td>League {l.league}</td>
                          <td className="dim">{l.scoring === "points" ? "H2H points" : "H2H categories"}</td>
                          <td className="dim" title={l.draft_time ?? undefined}>
                            {draftDay(l.draft_time)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="muted">No finished draft.</p>
                )}
              </div>
              <div className="drawer-section">
                <span className="k">Sessions on this server</span>
                <OpenSessions onSelect={onOpenSession} />
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
