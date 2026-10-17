import { useQuery } from "@tanstack/react-query";
import { api, type LeagueSummary, type RoomSummary } from "../api";
import { armLabel, draftWhen, nextDraft, roomOrder, turnFlag } from "../format";
import { syncState, useNow } from "./YahooSync";

/** The landing page's live drafts (#74): one card per attached room, with the league, my seat,
 * the room's mode and the user's pre-arm, the picks made, my next pick and the clock, and a
 * button into the session's draft view. With none, the next league draft. */
export default function LiveDrafts({ onOpen }: { onOpen: (sessionId: string) => void }) {
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: api.rooms, refetchInterval: 5000 });
  const leagues = useQuery({ queryKey: ["leagues"], queryFn: api.leagues, refetchInterval: 30_000 });
  const now = useNow();
  const byId = new Map((leagues.data ?? []).map((l) => [l.league, l]));
  const list = roomOrder(rooms.data ?? []);
  const next = nextDraft(leagues.data ?? [], now);
  return (
    <section className="panel live" aria-label="Live drafts">
      <h2>LIVE DRAFTS</h2>
      {rooms.error && <p className="error">{rooms.error.message}</p>}
      {list.length === 0 && !rooms.isPending && (
        <p className="muted">
          No live draft.
          {next ? ` Next: ${next.league}, ${draftWhen(next.draft_time, now)}.` : " No league draft is scheduled."}
        </p>
      )}
      {list.map((room) => (
        <RoomCard key={room.draft_id} room={room} league={byId.get(room.draft_id)} now={now} onOpen={onOpen} />
      ))}
    </section>
  );
}

function RoomCard({ room, league, now, onOpen }: { room: RoomSummary; league?: LeagueSummary; now: number; onOpen: (id: string) => void }) {
  const state = syncState(room, now);
  const total = room.num_teams * room.rounds;
  const turn = turnFlag(room, true);
  const format = league ? (league.scoring === "points" ? "H2H points" : "H2H categories") : "no league folder";
  return (
    <div className={`room-card${room.complete ? " done" : ""}`}>
      <div className="row">
        <strong>{league ? `League ${league.league}` : `Room ${room.draft_id}`}</strong>
        <span className="dim">{format}</span>
        <span className="grow" />
        <span className={`pill ${state.tone}`} title={state.title}>
          {state.label}
        </span>
      </div>
      <dl className="room-facts">
        <div>
          <dt>Seat</dt>
          <dd>{room.slot}</dd>
        </div>
        <div>
          <dt>Picks</dt>
          <dd>
            {room.picks_applied}/{total}
          </dd>
        </div>
        <div>
          <dt>My next</dt>
          <dd>{room.complete || room.my_next_pick == null ? "none" : `#${room.my_next_pick}`}</dd>
        </div>
        <div>
          <dt>Clock</dt>
          <dd>{room.clock_s != null ? `${room.clock_s} s` : "fixed"}</dd>
        </div>
      </dl>
      <div className="row">
        <span className={turn?.tone === "warn" ? "accent" : "muted"}>{room.complete ? "draft complete" : (turn?.text ?? "no pick of mine left")}</span>
        <span className="dim" title={room.pre_armed ? `pre-armed by ${room.pre_armed.by}` : undefined}>
          {room.mode === "autopilot" ? "armed" : "mirror"}
          {room.pre_armed ? ` · pre-${armLabel(room.pre_armed)}` : ""}
        </span>
        <span className="grow" />
        <button className="primary small" onClick={() => onOpen(room.session_id)}>
          Open draft
        </button>
      </div>
    </div>
  );
}
