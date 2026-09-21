import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, CAT_LABEL, CATS, type Cat, type SessionSummary } from "../api";

interface Props {
  session: SessionSummary;
}

export default function Recommend({ session }: Props) {
  const [auto, setAuto] = useState(true);
  const [punt, setPunt] = useState<Cat[]>([]);
  const [maxPunts, setMaxPunts] = useState(2);
  const [balance, setBalance] = useState(0);
  const [n, setN] = useState(8);
  const [refreshOnPick, setRefreshOnPick] = useState(true);
  const [horizon, setHorizon] = useState(true);

  const recommend = useMutation({
    mutationFn: () =>
      api.recommend(session.id, { n, punt: auto ? null : punt, max_punts: maxPunts, balance, horizon }),
  });
  const { mutate } = recommend;

  // Re-solve whenever the board changes (session.version bumps on every pick) if asked to.
  useEffect(() => {
    if (refreshOnPick && !session.complete) mutate();
  }, [session.version, session.complete, refreshOnPick, mutate]);

  const togglePunt = (c: Cat) => setPunt((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  const result = recommend.data;
  const title = session.on_the_clock
    ? "You are on the clock"
    : session.my_next_pick
      ? `Your next pick: ${session.my_next_pick}`
      : "Draft complete";

  return (
    <section className="panel recommend">
      <header className="board-head">
        <h2>{title}</h2>
        <button onClick={() => mutate()} disabled={recommend.isPending}>
          {recommend.isPending ? "Solving…" : "Re-solve"}
        </button>
      </header>
      <div className="controls">
        <label className="inline">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> choose punts automatically
        </label>
        {auto ? (
          <label className="inline">
            max punts
            <input type="number" min={0} max={4} value={maxPunts} onChange={(e) => setMaxPunts(+e.target.value)} />
          </label>
        ) : (
          <div className="punts">
            {CATS.map((c) => (
              <label key={c} className={`chip ${punt.includes(c) ? "on" : ""}`}>
                <input type="checkbox" checked={punt.includes(c)} onChange={() => togglePunt(c)} />
                punt {CAT_LABEL[c]}
              </label>
            ))}
          </div>
        )}
        <label className="inline">
          balance {balance.toFixed(2)}
          <input type="range" min={0} max={1} step={0.05} value={balance} onChange={(e) => setBalance(+e.target.value)} />
        </label>
        <label className="inline">
          candidates
          <input type="number" min={3} max={20} value={n} onChange={(e) => setN(+e.target.value)} />
        </label>
        <label className="inline">
          <input type="checkbox" checked={refreshOnPick} onChange={(e) => setRefreshOnPick(e.target.checked)} /> re-solve on every pick
        </label>
        <label className="inline">
          <input type="checkbox" checked={horizon} onChange={(e) => setHorizon(e.target.checked)} /> plan all remaining picks
        </label>
      </div>
      {recommend.error && <p className="error">{recommend.error.message}</p>}
      {result && (
        <>
          <h3>
            Candidates{" "}
            <span className="muted">
              {result.mode === "horizon"
                ? `cost includes the risk of waiting, punting ${result.punted.map((c) => CAT_LABEL[c]).join(", ") || "nothing"}, ADP from ${result.adp_source}`
                : "cost = objective lost by taking them now"}
            </span>
          </h3>
          <table>
            <thead>
              <tr>
                <th>Player</th>
                <th>Objective</th>
                <th>Cost</th>
                {result.mode === "horizon" && !result.on_the_clock && <th>P(my pick)</th>}
                {result.mode === "horizon" ? <th>P(pick after)</th> : <th>Punts</th>}
                <th>Weakest cat</th>
              </tr>
            </thead>
            <tbody>
              {result.candidates.map((c, i) => (
                <tr key={c.player} className={i === 0 ? "best" : ""}>
                  <td>{c.name}</td>
                  <td className="num">{c.objective.toFixed(2)}</td>
                  <td className="num">{c.cost_vs_best.toFixed(2)}</td>
                  {result.mode === "horizon" && !result.on_the_clock && (
                    <td className="num">{((c.p_available_first ?? 0) * 100).toFixed(0)}%</td>
                  )}
                  {result.mode === "horizon" ? (
                    <td className="num">{((c.p_available_next ?? 0) * 100).toFixed(0)}%</td>
                  ) : (
                    <td>{c.punted}</td>
                  )}
                  <td className="num">{c.min_active_total.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.plan.length > 0 && (
            <>
              <h3>
                Plan for your remaining picks <span className="muted">(chance still there)</span>
              </h3>
              <ul className="plan">
                {result.plan.map((p) => (
                  <li key={p.pick}>
                    <span className="slot">#{p.pick}</span> {p.name}
                    <span className="muted"> {(p.availability * 100).toFixed(0)}%</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <h3>
            {result.mode === "horizon" ? "Expected roster if the plan holds" : "Best roster from here"}{" "}
            <span className="muted">
              obj {result.best_roster.objective.toFixed(2)}, punting{" "}
              {result.best_roster.punted.map((c) => CAT_LABEL[c]).join(", ") || "nothing"},{" "}
              {(result.best_roster.solve_seconds * 1000).toFixed(0)} ms
            </span>
          </h3>
          <div className="roster-grid">
            <ul className="roster">
              {result.best_roster.roster.map((r) => (
                <li key={r.slot} className={session.my_roster.includes(r.player) ? "mine" : ""}>
                  <span className="slot">{r.slot}</span> {r.name}
                </li>
              ))}
            </ul>
            <ul className="totals">
              {CATS.map((c) => {
                const v = result.best_roster.cat_totals[c];
                const punted = result.best_roster.punted.includes(c);
                return (
                  <li key={c} className={punted ? "punted" : ""}>
                    <span className="slot">{CAT_LABEL[c]}</span>
                    <span className="bar" style={{ width: `${Math.min(100, Math.max(2, (v + 20) * 2))}%` }} />
                    <span className="num">{v.toFixed(1)}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </>
      )}
    </section>
  );
}
