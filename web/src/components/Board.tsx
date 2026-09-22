import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, CAT_LABEL, CATS, pickOwner, teamLabel, type BoardPlayer, type SessionSummary } from "../api";

interface Props {
  session: SessionSummary;
  recommended: string | null;
  /** The board is the only wide column: show ADP and the odds each player lasts to my next pick. */
  wide: boolean;
}

function heat(z: number): string | undefined {
  if (Math.abs(z) < 0.5) return undefined;
  const t = Math.min(3, Math.abs(z));
  return z > 0 ? `hsl(150 45% ${14 + t * 8}%)` : `hsl(0 45% ${14 + t * 7}%)`;
}

function survivalClass(p: number): string {
  return p >= 0.7 ? "good" : p >= 0.35 ? "" : "bad";
}

const NOISE = [
  { value: 0, label: "naive (best ADP)" },
  { value: 0.5, label: "a little noise" },
  { value: 1, label: "model spread" },
  { value: 2, label: "wild" },
];

export default function Board({ session, recommended, wide }: Props) {
  const queryClient = useQueryClient();
  const board = useQuery({ queryKey: ["board", session.id], queryFn: () => api.board(session.id) });
  const [search, setSearch] = useState("");
  const [hideTaken, setHideTaken] = useState(true);
  const [noise, setNoise] = useState(1);
  const owner = pickOwner(session.num_teams, session.next_overall);
  const [team, setTeam] = useState<string | null>(null);
  const draftingTeam = team ?? teamLabel(session, owner.position);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["session", session.id] });
    queryClient.invalidateQueries({ queryKey: ["board", session.id] });
    queryClient.invalidateQueries({ queryKey: ["picks", session.id] });
  };
  const addPick = useMutation({
    mutationFn: (player: BoardPlayer) => api.addPick(session.id, { team: draftingTeam, player_id: player.player_id }),
    onSuccess: () => {
      setTeam(null);
      invalidate();
    },
  });
  const autopick = useMutation({
    mutationFn: (body: { count?: number; until_my_pick: boolean }) => api.autopick(session.id, { ...body, noise }),
    onSuccess: invalidate,
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
  const nextPick = board.data?.next_pick ?? null;
  const busy = addPick.isPending || autopick.isPending;
  const error = addPick.error ?? autopick.error;

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
        {!session.complete && (
          <span className="inline muted sim" title="Auto-pick for the other teams: each pick takes the earliest noisy ADP slot">
            <span className="k">Sim</span>
            <button className="small" disabled={busy} onClick={() => autopick.mutate({ count: 1, until_my_pick: false })}>
              next pick
            </button>
            <button className="small" disabled={busy || session.on_the_clock} onClick={() => autopick.mutate({ until_my_pick: true })}>
              to my pick
            </button>
            <select value={noise} onChange={(e) => setNoise(Number(e.target.value))} aria-label="Simulation noise">
              {NOISE.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </span>
        )}
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
      {error && <p className="error">{error.message}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Player</th>
              <th>Pos</th>
              <th className="num">GP</th>
              {wide && <th className="num">ADP</th>}
              <th className="num">Z</th>
              {CATS.map((c) => (
                <th key={c} className="num">
                  {CAT_LABEL[c]}
                </th>
              ))}
              {wide && <th>{nextPick ? `Lasts to #${nextPick}` : "Lasts"}</th>}
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
                {wide && <td className="num">{p.adp == null ? "" : p.adp.toFixed(1)}</td>}
                <td className="num strong">{p.total.toFixed(1)}</td>
                {CATS.map((c) => (
                  <td key={c} className="num">
                    <span className="cell" style={{ background: heat(p.z[c]) }}>
                      {p.z[c].toFixed(1)}
                    </span>
                  </td>
                ))}
                {wide && (
                  <td>
                    {!p.taken && p.p_next != null && (
                      <span className="survival">
                        <span className="bar">
                          <span className={survivalClass(p.p_next)} style={{ width: `${Math.round(p.p_next * 100)}%` }} />
                        </span>
                        <span className="muted">{Math.round(p.p_next * 100)}%</span>
                      </span>
                    )}
                  </td>
                )}
                <td>
                  {!p.taken && !session.complete && (
                    <button
                      className={`small ${p.player_id === recommended ? "primary" : ""}`}
                      onClick={() => addPick.mutate(p)}
                      disabled={busy}
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
