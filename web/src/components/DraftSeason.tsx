import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { ordinal, scoreLabel } from "../season";
import DraftsAhead from "./DraftsAhead";
import LiveDrafts from "./LiveDrafts";
import OpenSessions from "./OpenSessions";
import SessionSetup from "./SessionSetup";

/** The landing page in draft season (#108, variant C): the drafts ahead with Arm, Open and Set
 * up, the live drafts, the leagues in season as chips and the sessions on this server, beside
 * the New draft form. */
export default function DraftSeason({
  now,
  setup,
  onSetUp,
  onOpenSession,
  onOpenLeague,
}: {
  now: number;
  setup: { key: number; league?: string };
  onSetUp: (league: string) => void;
  onOpenSession: (id: string) => void;
  onOpenLeague: (league: string) => void;
}) {
  const form = useRef<HTMLDivElement | null>(null);
  return (
    <div className="season-mode">
      <div className="draft-col">
        <div className="lg-head">
          <h2>DRAFTS AHEAD</h2>
          <span className="muted">arm a draft to let pickandroll pick for you in it; unarmed, Yahoo autopicks your turns</span>
        </div>
        <DraftsAhead
          now={now}
          onOpen={onOpenSession}
          onSetUp={(league) => {
            onSetUp(league);
            // On a phone the form sits below: bring it up.
            form.current?.scrollIntoView({ block: "start", behavior: "smooth" });
          }}
        />
        <LiveDrafts onOpen={onOpenSession} />
        <div className="lg-head">
          <h2>LEAGUES IN SEASON</h2>
          <span className="muted">click one for its league page</span>
        </div>
        <LeagueChips onOpen={onOpenLeague} />
        <div className="lg-head">
          <h2>SESSIONS</h2>
          <span className="muted">draft sessions on this server</span>
        </div>
        <OpenSessions onSelect={onOpenSession} />
      </div>
      <div ref={form}>
        <SessionSetup key={setup.key} initialLeague={setup.league} onCreated={(s) => onOpenSession(s.id)} />
      </div>
    </div>
  );
}

/** The leagues read so far, compact: the name, this week's score and my place. */
function LeagueChips({ onOpen }: { onOpen: (league: string) => void }) {
  const seasons = useQuery({ queryKey: ["seasons"], queryFn: api.seasons, refetchInterval: 60_000 });
  const read = (seasons.data ?? []).filter((s) => s.has_snapshot && !s.error).sort((a, b) => (a.name ?? a.league).localeCompare(b.name ?? b.league));
  if (seasons.error) return <p className="error">{seasons.error.message}</p>;
  if (!read.length) return <p className="muted">{seasons.isPending ? "Reading the leagues…" : "No league read yet."}</p>;
  return (
    <div className="chips">
      {read.map((s) => (
        <button key={s.league} className="chip" onClick={() => onOpen(s.league)} title={`Open ${s.name ?? s.league}'s league page`}>
          <span>{s.name ?? `League ${s.league}`}</span>
          <span className="dim">
            {scoreLabel(s)}
            {s.my_team?.rank != null ? ` · ${ordinal(s.my_team.rank)}` : ""}
          </span>
        </button>
      ))}
    </div>
  );
}
