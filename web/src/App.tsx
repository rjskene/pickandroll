import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import Board from "./components/Board";
import PickLog from "./components/PickLog";
import Recommend from "./components/Recommend";
import SessionSetup from "./components/SessionSetup";

export default function App() {
  const queryClient = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(() => new URLSearchParams(location.search).get("session"));
  const session = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.session(sessionId!),
    enabled: !!sessionId,
  });

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
    source.addEventListener("hello", refresh); // also fires after an automatic reconnect
    source.addEventListener("pick", refresh);
    source.addEventListener("undo", refresh);
    return () => source.close();
  }, [sessionId, queryClient]);

  if (!sessionId || !session.data) {
    return (
      <main className="shell">
        <h1>pickandroll</h1>
        {session.error && <p className="error">{session.error.message}</p>}
        <SessionSetup onCreated={(s) => setSessionId(s.id)} onSelect={setSessionId} />
      </main>
    );
  }
  const s = session.data;
  return (
    <main className="shell draft">
      <header className="topbar">
        <h1>pickandroll</h1>
        <span className="muted">
          {s.projection} · {s.num_teams} teams · you pick {s.my_position} · pick {s.next_overall} of {s.num_teams * s.roster_size}
        </span>
        <button className="link" onClick={() => setSessionId(null)}>
          switch draft
        </button>
      </header>
      <div className="layout">
        <Board session={s} />
        <div className="side">
          <Recommend session={s} />
          <PickLog session={s} />
        </div>
      </div>
    </main>
  );
}
