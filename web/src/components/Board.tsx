import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, CAT_LABEL, CATS, pickOwner, teamLabel, type BoardPlayer, type SessionSummary } from "../api";

interface Props {
  session: SessionSummary;
  recommended: string | null;
}

function heat(z: number): string | undefined {
  if (Math.abs(z) < 0.5) return undefined;
  const t = Math.min(3, Math.abs(z));
  return z > 0 ? `hsl(150 45% ${14 + t * 8}%)` : `hsl(0 45% ${14 + t * 7}%)`;
}

export default function Board({ session, recommended }: Props) {
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
  const draftFirstMatch = () => {
    const first = rows.find((p) => !p.taken);
    if (first && search.trim()) addPick.mutate(first);
  };

  return (
    <section className="panel board">
      <header className="board-head">
        <h2>BOARD</h2>
        <input
          type="search"
          placeholder="Search, Enter drafts first match"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && draftFirstMatch()}
        />
        <label className="inline muted">
          <input type="checkbox" checked={hideTaken} onChange={(e) => setHideTaken(e.target.checked)} /> hide drafted
        </label>
        <span style={{ flexGrow: 1 }} />
        {!session.complete && (
          <label className="inline muted">
            Pick {session.next_overall} goes to
            <select value={draftingTeam} onChange={(e) => setTeam(e.target.value)}>
              {teams.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>
      {addPick.error && <p className="error">{addPick.error.message}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Player</th>
              <th>Pos</th>
              <th className="num">GP</th>
              <th className="num">Z</th>
              {CATS.map((c) => (
                <th key={c} className="num">
                  {CAT_LABEL[c]}
                </th>
              ))}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => (
              <tr key={p.player_id} className={p.taken ? "taken" : p.player_id === recommended ? "reco" : ""}>
                <td className="dim">{i + 1}</td>
                <td className={p.player_id === recommended ? "strong" : ""}>
                  {p.name} <span className="dim">{p.team}</span>
                </td>
                <td>{p.positions || <span className="dim">?</span>}</td>
                <td className="num">{Math.round(p.games)}</td>
                <td className="num strong">{p.total.toFixed(1)}</td>
                {CATS.map((c) => (
                  <td key={c} className="num">
                    <span className="cell" style={{ background: heat(p.z[c]) }}>
                      {p.z[c].toFixed(1)}
                    </span>
                  </td>
                ))}
                <td>
                  {!p.taken && !session.complete && (
                    <button
                      className={`small ${p.player_id === recommended ? "primary" : ""}`}
                      onClick={() => addPick.mutate(p)}
                      disabled={addPick.isPending}
                    >
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
