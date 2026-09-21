import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type SessionSummary } from "../api";

interface Props {
  session: SessionSummary;
}

export default function PickLog({ session }: Props) {
  const queryClient = useQueryClient();
  const picks = useQuery({ queryKey: ["picks", session.id], queryFn: () => api.picks(session.id) });
  const undo = useMutation({
    mutationFn: () => api.undoPick(session.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["session", session.id] });
      queryClient.invalidateQueries({ queryKey: ["board", session.id] });
      queryClient.invalidateQueries({ queryKey: ["picks", session.id] });
    },
  });
  const rows = [...(picks.data ?? [])].reverse();
  return (
    <section className="panel picklog">
      <header className="board-head">
        <h2>Picks</h2>
        <button className="small" onClick={() => undo.mutate()} disabled={!rows.length || undo.isPending}>
          Undo last
        </button>
      </header>
      <ol reversed>
        {rows.map((p) => (
          <li key={p.overall} className={p.team === session.my_team ? "mine" : ""}>
            <span className="slot">
              {p.round}.{String(p.position).padStart(2, "0")}
            </span>{" "}
            {p.name} <span className="muted">{p.team}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
