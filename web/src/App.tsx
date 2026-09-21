import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, pickOwner, teamLabel, type SolveEvent } from "./api";
import Board from "./components/Board";
import PickLog from "./components/PickLog";
import Recommend from "./components/Recommend";
import SessionSetup from "./components/SessionSetup";
import TeamProfile from "./components/TeamProfile";

function useTicker(resetKey: number): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    setSeconds(0);
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [resetKey]);
  return seconds;
}

export default function App() {
  const queryClient = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(() => new URLSearchParams(location.search).get("session"));
  const [solveEvents, setSolveEvents] = useState<SolveEvent[]>([]);
  const [profile, setProfile] = useState<{ totals: Record<string, number>; punted: string[] } | null>(null);
  const [recommended, setRecommended] = useState<string | null>(null);
  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.session(sessionId!),
    enabled: !!sessionId,
  });
  const yahoo = useQuery({
    queryKey: ["yahoo", sessionId],
    queryFn: () => api.yahooStatus(sessionId!),
    enabled: !!sessionId,
    refetchInterval: 15000,
  });
  const sinceLastPick = useTicker(session.data?.picks_made ?? 0);

  useEffect(() => {
    const url = new URL(location.href);
    if (sessionId) url.searchParams.set("session", sessionId);
    else url.searchParams.delete("session");
    history.replaceState(null, "", url);
  }, [sessionId]);

  // Live feed: any pick (manual or from Yahoo) invalidates the board, picks and session.
  useEffect(() => {
    if (!sessionId) return;
    const source = new EventSource(api.eventsUrl(sessionId));
    const refresh = () => {
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["board", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["picks", sessionId] });
    };
    source.addEventListener("solve", (e) => {
      const event = JSON.parse((e as MessageEvent).data) as SolveEvent;
      setSolveEvents((prev) => (event.stage === "start" || event.stage === "roster" ? [event] : [...prev, event]));
    });
    source.addEventListener("hello", refresh);
    source.addEventListener("pick", refresh);
    source.addEventListener("undo", refresh);
    return () => source.close();
  }, [sessionId, queryClient]);

  if (!sessionId || !session.data) {
    return (
      <main className="shell">
        <header className="topbar">
          <div className="wordmark">
            PICK<span>&amp;</span>ROLL
          </div>
        </header>
        {session.error && <p className="error" style={{ padding: "0 24px" }}>{session.error.message}</p>}
        <SessionSetup onCreated={(s) => setSessionId(s.id)} onSelect={setSessionId} />
      </main>
    );
  }
  const s = session.data;
  const owner = pickOwner(s.num_teams, s.next_overall);
  const onClockTeam = teamLabel(s, owner.position);
  const mm = Math.floor(sinceLastPick / 60);
  const ss = String(sinceLastPick % 60).padStart(2, "0");
  return (
    <main className="shell">
      <header className="topbar">
        <div className="wordmark">
          PICK<span>&amp;</span>ROLL
        </div>
        <span className="muted">
          {s.projection} · {s.num_teams} teams · you pick {s.my_position}
        </span>
        <span style={{ flexGrow: 1 }} />
        {s.complete ? (
          <span className="pill">DRAFT COMPLETE</span>
        ) : (
          <>
            <span className="k">
              Pick {s.next_overall} · Round {owner.round}
            </span>
            <span className={`pill ${s.on_the_clock ? "hot" : ""}`}>{s.on_the_clock ? "YOU ARE ON THE CLOCK" : `${onClockTeam} on the clock`}</span>
            <span className="clock" title="time since the last pick">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <circle cx="12" cy="13" r="8" />
                <path d="M12 9v4l3 2M9 2h6" />
              </svg>
              {mm}:{ss}
            </span>
          </>
        )}
        <button className="link" onClick={() => setSessionId(null)}>
          switch draft
        </button>
      </header>
      <div className="layout">
        <div className="col">
          <Board session={s} recommended={recommended} />
        </div>
        <div className="col">
          <Recommend session={s} solveEvents={solveEvents} onResult={(r) => { setProfile({ totals: r.best_roster.cat_totals, punted: r.best_roster.punted }); setRecommended(r.candidates[0]?.player ?? null); }} />
        </div>
        <div className="col">
          <TeamProfile profile={profile} />
          <PickLog session={s} />
        </div>
      </div>
      <footer className="footer">
        <span>
          Feed:{" "}
          {yahoo.data?.attached ? (
            <span className={yahoo.data.last_error ? "bad" : "good"}>Yahoo {yahoo.data.league} {yahoo.data.running ? "polling" : "attached"}</span>
          ) : (
            "manual entry (Yahoo pending approval)"
          )}
        </span>
        <span>ADP: {s.adp_source}</span>
        <span>Positions: {s.unknown_positions === 0 ? "all known" : `${s.unknown_positions} unknown`}</span>
        <span className="grow" />
        <span>Session {s.id}</span>
      </footer>
    </main>
  );
}
