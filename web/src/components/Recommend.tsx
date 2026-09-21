import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, CAT_LABEL, CATS, type Cat, type Candidate, type SessionSummary, type SolveEvent } from "../api";

interface Props {
  session: SessionSummary;
  solveEvents: SolveEvent[];
}

function parsePunt(label: string): Cat[] {
  return label === "-" ? [] : (label.split("/") as Cat[]);
}

function fmtMs(ms: number | undefined): string {
  if (ms === undefined) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

export default function Recommend({ session, solveEvents }: Props) {
  const [auto, setAuto] = useState(true);
  const [punt, setPunt] = useState<Cat[]>([]);
  const [maxPunts, setMaxPunts] = useState(2);
  const [balance, setBalance] = useState(0);
  const [n, setN] = useState(8);
  const [refreshOnPick, setRefreshOnPick] = useState(true);
  const [horizon, setHorizon] = useState(true);
  const [showRoster, setShowRoster] = useState<string | null>(null);

  const params = { n, punt: auto ? null : punt, max_punts: maxPunts, balance, horizon };
  const recommend = useMutation({ mutationFn: () => api.recommend(session.id, params) });
  const { mutate } = recommend;

  // Re-solve whenever the board changes (session.version bumps on every pick). The ref keeps
  // React's development double-invoke from firing two solves for one version.
  const solvedFor = useRef<string>("");
  useEffect(() => {
    const key = `${session.id}:${session.version}`;
    if (refreshOnPick && !session.complete && solvedFor.current !== key) {
      solvedFor.current = key;
      mutate();
    }
  }, [session.id, session.version, session.complete, refreshOnPick, mutate]);

  const togglePunt = (c: Cat) => setPunt((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  const pinPunt = (label: string) => {
    setAuto(false);
    setPunt(parsePunt(label));
    setTimeout(() => mutate(), 0);
  };
  const result = recommend.data;
  const title = session.on_the_clock
    ? "You are on the clock"
    : session.my_next_pick
      ? `Your next pick: ${session.my_next_pick}`
      : "Draft complete";

  // Live view of the run in progress, built from the solve events.
  const live = useMemo(() => {
    const scan = solveEvents.filter((e) => e.stage === "punt_scan");
    const plan = solveEvents.find((e) => e.stage === "plan");
    const cands = solveEvents.filter((e) => e.stage === "candidates");
    const last = solveEvents[solveEvents.length - 1];
    const rows = new Map<string, Candidate>();
    for (const e of cands) if (e.candidate && !e.candidate.failed) rows.set(e.candidate.player, e.candidate);
    return {
      scanDone: scan.length ? scan[scan.length - 1].done : 0,
      scanTotal: scan.length ? scan[scan.length - 1].total : 0,
      best: scan.length ? scan[scan.length - 1] : undefined,
      plan,
      candDone: cands.length ? cands[cands.length - 1].done : 0,
      candTotal: cands.length ? cands[cands.length - 1].total : 0,
      rows: [...rows.values()].sort((x, y) => y.objective - x.objective),
      elapsed: last?.elapsed_ms ?? 0,
      autoPunt: solveEvents[0]?.auto_punt ?? true,
      error: solveEvents.find((e) => e.stage === "error")?.message,
    };
  }, [solveEvents]);

  return (
    <section className="panel recommend">
      <header className="board-head">
        <h2>{title}</h2>
        <button onClick={() => mutate()} disabled={recommend.isPending}>
          {recommend.isPending ? "Solving…" : "Re-solve"}
        </button>
        {result && !recommend.isPending && (
          <span className="muted">
            {fmtMs(result.timings.total_ms)} total
            {result.timings.solver_players ? `, ${result.timings.solver_players} players modelled` : ""}
          </span>
        )}
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

      {recommend.isPending && (
        <div className="solver">
          <div className="stage">
            <span className={`dot ${live.autoPunt ? (live.scanDone === live.scanTotal && live.scanTotal > 0 ? "ok" : "run") : "skip"}`} />
            <span className="stage-name">Punt strategy</span>
            {live.autoPunt ? (
              <>
                <progress value={live.scanDone} max={live.scanTotal || 1} />
                <span className="muted">
                  {live.scanDone}/{live.scanTotal || "…"} punt sets
                  {live.best ? ` · best so far: punt ${live.best.best_punt} (${live.best.best_objective?.toFixed(2)})` : ""}
                </span>
              </>
            ) : (
              <span className="muted">fixed: {punt.length ? punt.map((c) => CAT_LABEL[c]).join(", ") : "no punt"}</span>
            )}
          </div>
          <div className="stage">
            <span className={`dot ${live.plan ? "ok" : live.scanDone === live.scanTotal ? "run" : "wait"}`} />
            <span className="stage-name">Plan remaining picks</span>
            <span className="muted">
              {live.plan
                ? `first pick ${live.plan.first_pick_name ?? live.plan.first_pick}, objective ${live.plan.objective?.toFixed(2)}, punting ${live.plan.punt}`
                : "waiting"}
            </span>
          </div>
          <div className="stage">
            <span className={`dot ${live.candTotal && live.candDone === live.candTotal ? "ok" : live.plan ? "run" : "wait"}`} />
            <span className="stage-name">Price candidates</span>
            <progress value={live.candDone} max={live.candTotal || 1} />
            <span className="muted">
              {live.candDone}/{live.candTotal || "…"} priced · {fmtMs(live.elapsed)}
            </span>
          </div>
          {live.rows.length > 0 && (
            <table className="live-rows">
              <tbody>
                {live.rows.map((c) => (
                  <tr key={c.player}>
                    <td>{c.name}</td>
                    <td className="num">{c.objective.toFixed(2)}</td>
                    <td className="num muted">{((c.p_available_next ?? 0) * 100).toFixed(0)}% next</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {live.error && <p className="error">{live.error}</p>}
        </div>
      )}
      {recommend.error && <p className="error">{recommend.error.message}</p>}

      {result && !recommend.isPending && (
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

          {result.punt_scan.length > 0 && (
            <>
              <h3>
                Punt strategies{" "}
                <span className="muted">
                  {result.punt_scan.length} best of the scan in {fmtMs(result.timings.punt_scan_ms)}, click one to pin it
                </span>
              </h3>
              <table className="punt-scan">
                <thead>
                  <tr>
                    <th>Punt</th>
                    <th>Objective</th>
                    <th>Gap</th>
                    <th>Weakest cat</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {result.punt_scan.map((row, i) => (
                    <tr key={row.punt} className={i === 0 ? "best" : ""}>
                      <td>
                        <button className="link" onClick={() => pinPunt(row.punt)}>
                          {row.punt === "-" ? "no punt" : row.punt.split("/").map((c) => CAT_LABEL[c as Cat]).join(" + ")}
                        </button>
                      </td>
                      <td className="num">{row.objective.toFixed(2)}</td>
                      <td className="num">{row.gap_to_best.toFixed(2)}</td>
                      <td className="num">{row.min_active_total.toFixed(2)}</td>
                      <td>
                        <button className="small" onClick={() => setShowRoster(showRoster === row.punt ? null : row.punt)}>
                          {showRoster === row.punt ? "hide" : "roster"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {showRoster && (
                <p className="muted small-text">
                  {result.punt_scan.find((r) => r.punt === showRoster)?.roster.join(", ")}
                </p>
              )}
            </>
          )}

          {result.plan.length > 0 && (
            <>
              <h3>
                Plan for your remaining picks <span className="muted">(chance still there, planned in {fmtMs(result.timings.plan_ms)})</span>
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
                const v = result.best_roster.cat_totals[c] ?? 0;
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
