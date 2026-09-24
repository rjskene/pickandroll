import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, CAT_LABEL, CATS, teamLabel, type BoardPlayer, type SimStrategy } from "../api";
import { useDraft } from "../draft";
import { fmtCost, oddsClass } from "../format";

function heat(z: number): string | undefined {
  if (Math.abs(z) < 0.5) return undefined;
  const t = Math.min(3, Math.abs(z));
  return z > 0 ? `hsl(150 45% ${14 + t * 8}%)` : `hsl(0 45% ${14 + t * 7}%)`;
}

const NOISE = [
  { value: 0, label: "no randomness" },
  { value: 0.5, label: "a little randomness" },
  { value: 1, label: "normal randomness" },
  { value: 2, label: "wild" },
];
const STRATEGIES: { value: SimStrategy; label: string; title: string }[] = [
  { value: "z", label: "by z-score", title: "Each team takes one of the best players by total z; randomness favours the ones closest to the top" },
  { value: "adp", label: "by ADP", title: "Each team takes the earliest noisy ADP slot, the spread the availability model assumes" },
  { value: "lp", label: "by LP", title: "Each team solves its own roster problem (with a punt of its own) and takes the best new player from it" },
];

export default function Board() {
  const d = useDraft();
  const s = d.session;
  const board = useQuery({ queryKey: ["board", s.id], queryFn: () => api.board(s.id) });
  const [search, setSearch] = useState("");
  const wide = !d.drawerOpen;
  const recommended = d.result?.candidates[0]?.player ?? null;

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (board.data?.players ?? []).filter(
      (p) => (!d.hideTaken || !p.taken) && (!needle || p.name.toLowerCase().includes(needle)),
    );
  }, [board.data, search, d.hideTaken]);
  useEffect(() => {
    d.setVisibleRows(rows.filter((p) => !p.taken).map((p) => p.player_id));
  }, [rows, d.setVisibleRows]);
  useEffect(() => {
    if (d.highlight) document.querySelector("tr.hl")?.scrollIntoView({ block: "nearest" });
  }, [d.highlight]);

  const teams = Array.from({ length: s.num_teams }, (_, i) => teamLabel(s, i + 1));
  const draftFirstMatch = () => {
    const first = rows.find((p) => !p.taken);
    if (first && search.trim()) d.draftPlayer(first.player_id, { via: "key" });
  };
  const nextPick = board.data?.next_pick ?? null;
  const priced = board.data?.prices_version != null;
  const scale = board.data?.scale ?? undefined;
  const busy = d.drafting || d.simulating;
  const draftRow = (p: BoardPlayer) => d.draftPlayer(p.player_id);

  return (
    <section className="panel board">
      <header className="board-head">
        <h2>BOARD</h2>
        <input
          ref={d.searchRef}
          type="search"
          placeholder="Search  /"
          title="Search (/) · Enter drafts the first match"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && draftFirstMatch()}
        />
        <label className="inline muted" title="Hide drafted players (h)">
          <input
            type="checkbox"
            checked={d.hideTaken}
            onChange={(e) => {
              d.setHideTaken(e.target.checked);
              e.currentTarget.blur();
            }}
          />{" "}
          hide drafted
        </label>
        {!s.complete && !d.live && (
          <span className="inline muted sim" title="Simulate the other teams' picks">
            <span className="k">Sim</span>
            <button className="small" disabled={busy} onClick={() => d.simulate({ count: 1, until_my_pick: false })} title="Simulate one pick (shift+S)">
              next pick
            </button>
            <button className="small" disabled={busy || s.on_the_clock} onClick={() => d.simulate({ until_my_pick: true })} title="Simulate up to my pick (s)">
              to my pick
            </button>
            <button className={`small ${d.mock ? "primary" : ""}`} onClick={() => d.setMock(!d.mock)} title="Run the whole mock draft: the other teams are simulated, the solver drafts for you (m)">
              {d.mock ? "■ stop mock draft" : "▶ mock draft"}
            </button>
            <select
              value={d.strategy}
              onChange={(e) => {
                d.setStrategy(e.target.value as SimStrategy);
                e.currentTarget.blur();
              }}
              aria-label="Simulation strategy"
              title={STRATEGIES.find((x) => x.value === d.strategy)?.title}
            >
              {STRATEGIES.map((o) => (
                <option key={o.value} value={o.value} title={o.title}>
                  {o.label}
                </option>
              ))}
            </select>
            <select
              value={d.noise}
              onChange={(e) => {
                d.setNoise(Number(e.target.value));
                e.currentTarget.blur();
              }}
              aria-label="Simulation randomness"
            >
              {NOISE.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </span>
        )}
        <span className="grow" />
        {!s.complete && (
          <label className="inline muted">
            Pick {s.next_overall} goes to
            <select
              value={d.draftingTeam}
              onChange={(e) => {
                d.setTeamOverride(e.target.value);
                e.currentTarget.blur();
              }}
            >
              {teams.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>
      {d.pickError && <p className="error">{d.pickError}</p>}
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
              <th className="num" title="cost of taking this player with your next pick instead of the plan's choice (first-order, on the objective's scale)">
                Cost
              </th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => {
              const cls = [p.taken ? "taken" : "", p.player_id === recommended ? "reco" : "", p.player_id === d.highlight ? "hl" : ""].filter(Boolean).join(" ");
              return (
                <tr key={p.player_id} className={cls} onClick={() => !p.taken && d.setHighlight(p.player_id)}>
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
                            <span className={oddsClass(p.p_next)} style={{ width: `${Math.round(p.p_next * 100)}%` }} />
                          </span>
                          <span className="muted">{Math.round(p.p_next * 100)}%</span>
                        </span>
                      )}
                    </td>
                  )}
                  <td className={`num ${p.cost != null && p.cost < 0.005 ? "good" : "muted"}`}>
                    {!p.taken && priced && p.cost != null ? fmtCost(p.cost, scale, true) : ""}
                  </td>
                  <td>
                    {!p.taken && !s.complete && (
                      <button
                        className={`small ${p.player_id === recommended ? "primary" : ""}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          draftRow(p);
                        }}
                        disabled={busy}
                      >
                        Draft
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
