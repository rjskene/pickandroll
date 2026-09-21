import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, CAT_LABEL, CATS, pickOwner, teamLabel, type BoardPlayer, type SessionSummary } from "../api";

interface Props {
  session: SessionSummary;
}

function zColor(z: number): string {
  const clamped = Math.max(-3, Math.min(3, z));
  const alpha = Math.min(0.85, Math.abs(clamped) / 3);
  return clamped >= 0 ? `rgba(46, 160, 67, ${alpha})` : `rgba(218, 54, 51, ${alpha})`;
}

export default function Board({ session }: Props) {
  const queryClient = useQueryClient();
  const board = useQuery({ queryKey: ["board", session.id], queryFn: () => api.board(session.id) });
  const [search, setSearch] = useState("");
  const [hideTaken, setHideTaken] = useState(true);
  const owner = pickOwner(session.num_teams, session.next_overall);
  const [team, setTeam] = useState<string | null>(null);
  const draftingTeam = team ?? teamLabel(session, owner.position);

  const addPick = useMutation({
    mutationFn: (player: BoardPlayer) => api.addPick(session.id, { team: draftingTeam, player_id: player.player_id }),
    onSuccess: () => {
      setTeam(null);
      queryClient.invalidateQueries({ queryKey: ["session", session.id] });
      queryClient.invalidateQueries({ queryKey: ["board", session.id] });
      queryClient.invalidateQueries({ queryKey: ["picks", session.id] });
    },
  });

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (board.data?.players ?? []).filter(
      (p) => (!hideTaken || !p.taken) && (!needle || p.name.toLowerCase().includes(needle)),
    );
  }, [board.data, search, hideTaken]);

  const teams = Array.from({ length: session.num_teams }, (_, i) => teamLabel(session, i + 1));

  return (
    <section className="panel board">
      <header className="board-head">
        <h2>Board</h2>
        <input placeholder="Search player" value={search} onChange={(e) => setSearch(e.target.value)} />
        <label className="inline">
          <input type="checkbox" checked={hideTaken} onChange={(e) => setHideTaken(e.target.checked)} /> hide drafted
        </label>
        <label className="inline">
          Pick {session.next_overall} (R{owner.round}) goes to
          <select value={draftingTeam} onChange={(e) => setTeam(e.target.value)}>
            {teams.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </header>
      {addPick.error && <p className="error">{addPick.error.message}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Player</th>
              <th>Tm</th>
              <th>Pos</th>
              <th>GP</th>
              <th>Z</th>
              {CATS.map((c) => (
                <th key={c}>{CAT_LABEL[c]}</th>
              ))}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
              <tr key={p.player_id} className={p.taken ? "taken" : ""}>
                <td>{i + 1}</td>
                <td>{p.name}</td>
                <td>{p.team}</td>
                <td>{p.positions}</td>
                <td>{Math.round(p.games)}</td>
                <td className="num strong">{p.total.toFixed(1)}</td>
                {CATS.map((c) => (
                  <td key={c} className="num" style={{ background: zColor(p.z[c]) }}>
                    {p.z[c].toFixed(1)}
                  </td>
                ))}
                <td>
                  {!p.taken && !session.complete && (
                    <button className="small" onClick={() => addPick.mutate(p)} disabled={addPick.isPending}>
                      Draft
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
