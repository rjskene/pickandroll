import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LeagueSummary, type RoomSummary, type SessionSummary } from "../api";
import { armLabel, draftDay, draftsAhead, draftState, untilLabel } from "../format";
import { leagueTitle } from "../season";

/** The drafts the user can still arm (#67, #108): one card per league whose draft is ahead,
 * started with no room, or not scheduled yet, with Arm (confirmed in a second click), Open when
 * a session or room exists for it, and Set up, which fills the New draft form. A finished draft
 * is never here: it carries no Arm and no armed state. No session or script arms a league
 * (CLAUDE.md, the 2026-10-16 exception). */
export default function DraftsAhead({ now, onOpen, onSetUp }: { now: number; onOpen: (sessionId: string) => void; onSetUp: (league: string) => void }) {
  const queryClient = useQueryClient();
  const leagues = useQuery({ queryKey: ["leagues"], queryFn: api.leagues, refetchInterval: 30_000 });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: api.rooms, refetchInterval: 5000 });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  // The leagues' names as read from Yahoo (the live-draft cards' query); one not read goes by its id.
  const seasons = useQuery({ queryKey: ["seasons"], queryFn: api.seasons, refetchInterval: 60_000 });
  const names = new Map((seasons.data ?? []).map((s) => [s.league, s.name]));
  // The league whose arm is waiting on its confirming click.
  const [confirming, setConfirming] = useState<string | null>(null);
  const arm = useMutation({
    mutationFn: ({ league, armed }: { league: string; armed: boolean }) => api.armLeague(league, armed),
    onSettled: () => {
      setConfirming(null);
      void queryClient.invalidateQueries({ queryKey: ["leagues"] });
    },
  });
  if (leagues.error) return <p className="error">{leagues.error.message}</p>;
  const ahead = draftsAhead(leagues.data ?? [], rooms.data ?? [], now);
  if (!ahead.length) return <p className="muted">{leagues.isPending ? "Reading the leagues…" : "No league has a draft ahead."}</p>;
  return (
    <div className="upcoming">
      {ahead.map((l) => (
        <DraftCard
          key={l.league}
          l={l}
          name={names.get(l.league) ?? null}
          now={now}
          open={openId(l, rooms.data ?? [], sessions.data ?? [])}
          confirming={confirming === l.league}
          busy={arm.isPending}
          onArm={() => setConfirming(l.league)}
          onConfirm={() => arm.mutate({ league: l.league, armed: true })}
          onCancel={() => setConfirming(null)}
          onDisarm={() => arm.mutate({ league: l.league, armed: false })}
          onOpen={onOpen}
          onSetUp={() => onSetUp(l.league)}
        />
      ))}
      {arm.isError && <p className="warn">{String(arm.error)}</p>}
    </div>
  );
}

/** The session a league's draft opens in: its room's, else the latest made from its folder. */
function openId(l: LeagueSummary, rooms: RoomSummary[], sessions: SessionSummary[]): string | null {
  const room = rooms.find((r) => r.draft_id === l.league);
  if (room) return room.session_id;
  const made = sessions.filter((s) => s.league === l.league);
  return made.length ? made[made.length - 1].id : null;
}

function DraftCard({
  l,
  name,
  now,
  open,
  confirming,
  busy,
  onArm,
  onConfirm,
  onCancel,
  onDisarm,
  onOpen,
  onSetUp,
}: {
  l: LeagueSummary;
  name: string | null;
  now: number;
  open: string | null;
  confirming: boolean;
  busy: boolean;
  onArm: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  onDisarm: () => void;
  onOpen: (sessionId: string) => void;
  onSetUp: () => void;
}) {
  const started = draftState(l, [], now) === "started";
  const soon = started || (!!l.draft_time && Date.parse(l.draft_time) - now < 24 * 3600_000);
  const format = l.scoring === "points" ? "H2H points" : "H2H categories";
  return (
    <div className={`dcard${soon ? " soon" : ""}`}>
      <div>
        <span className="k">
          {leagueTitle(name, l.league)} · {format}
          {l.num_teams ? ` · ${l.num_teams} teams` : ""}
        </span>
        <div className="when" title={l.draft_time ?? undefined}>
          {draftDay(l.draft_time)}
        </div>
        <span className="muted">
          {untilLabel(l.draft_time, now)} · {l.armed ? armLabel(l.armed) : "not armed: Yahoo autopicks your turns if you are away"}
          {l.players_file ? "" : " · no players file"}
          {l.error ? ` · its folder does not read: ${l.error}` : ""}
        </span>
      </div>
      <div className="dactions">
        {l.armed ? (
          <>
            <span className="pill hot" title={`armed ${l.armed.at} by ${l.armed.by}`}>
              ARMED
            </span>
            <button className="small" disabled={busy} onClick={onDisarm}>
              Disarm
            </button>
          </>
        ) : confirming ? (
          <>
            <button className="small primary" disabled={busy} onClick={onConfirm}>
              Confirm: arm {l.league}
            </button>
            <button className="small" onClick={onCancel}>
              Cancel
            </button>
          </>
        ) : (
          <button className="small" onClick={onArm} title="Let pickandroll pick for you in this draft">
            Arm draft
          </button>
        )}
        {open && (
          <button className="small primary" onClick={() => onOpen(open)}>
            Open the draft
          </button>
        )}
        <button className="small" disabled={!l.resolved} onClick={onSetUp} title={l.resolved ? "Fill the New draft form with this league" : "Its folder does not read"}>
          Set up
        </button>
      </div>
    </div>
  );
}
