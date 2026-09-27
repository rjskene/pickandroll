// A large, short-lived announcement when a pick lands from any source (a click, a key, the
// simulation, the mock draft, the live feed). Separate from the toast, which only follows my
// own actions and carries Undo. Picks that land together are shown one after another, faster
// when the queue is long, and the overlay never takes clicks.
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type PickRow } from "../api";
import { useDraft } from "../draft";

export interface Announcement {
  id: number;
  pick: PickRow;
}

const HOLD_MS = 1800;
const QUICK_HOLD_MS = 900;
const FADE_MS = 260;

export default function Announcer({ queue, onShown }: { queue: Announcement[]; onShown: (id: number) => void }) {
  const d = useDraft();
  const s = d.session;
  const board = useQuery({ queryKey: ["board", s.id], queryFn: () => api.board(s.id) });
  const current = queue[0];
  const id = current?.id ?? null;
  const pending = useRef(queue.length);
  pending.current = queue.length;
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    if (id == null) return;
    setLeaving(false);
    const hold = pending.current > 2 ? QUICK_HOLD_MS : HOLD_MS;
    const fade = window.setTimeout(() => setLeaving(true), hold);
    const done = window.setTimeout(() => onShown(id), hold + FADE_MS);
    return () => {
      window.clearTimeout(fade);
      window.clearTimeout(done);
    };
  }, [id, onShown]);
  if (!current) return null;
  const pick = current.pick;
  const player = board.data?.players.find((p) => p.player_id === pick.player_id);
  const mine = pick.position === s.my_position;
  return (
    <div className={`announce ${leaving ? "out" : "in"} ${mine ? "mine" : ""}`} role="status" aria-live="polite">
      <span className="k">Pick {pick.overall}</span>
      <span className="team">{pick.team}</span>
      <span className="name">{pick.name}</span>
      {player && (
        <span className="meta">
          {player.team}
          {player.positions ? ` · ${player.positions}` : ""}
        </span>
      )}
    </div>
  );
}
