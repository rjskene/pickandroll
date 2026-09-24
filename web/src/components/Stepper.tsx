import { useMemo } from "react";
import type { Candidate, SolveEvent } from "../api";
import { useDraft } from "../draft";
import { fmtCost, fmtMs, fmtObjective, pct } from "../format";

export function useLive(solveEvents: SolveEvent[]) {
  return useMemo(() => {
    const plan = solveEvents.find((e) => e.stage === "plan");
    const prices = solveEvents.find((e) => e.stage === "prices");
    const cands = solveEvents.filter((e) => e.stage === "candidates");
    const scen = solveEvents.filter((e) => e.stage === "scenarios");
    const last = solveEvents[solveEvents.length - 1];
    const rows = new Map<string, Candidate>();
    for (const e of cands) if (e.candidate && !e.candidate.failed) rows.set(e.candidate.player, e.candidate);
    const first = solveEvents[0]?.objective;
    return {
      objective: typeof first === "string" ? first : undefined,
      plan,
      prices: prices?.prices,
      candDone: cands.length ? cands[cands.length - 1].done : 0,
      candTotal: cands.length ? cands[cands.length - 1].total : prices ? prices.total : 0,
      scenDone: scen.length ? scen[scen.length - 1].done : 0,
      scenTotal: scen.length ? scen[scen.length - 1].total : 0,
      rows: [...rows.values()].sort((x, y) => y.objective - x.objective),
      elapsed: last?.elapsed_ms ?? 0,
      done: solveEvents.some((e) => e.stage === "done"),
      error: solveEvents.find((e) => e.stage === "error")?.message,
    };
  }, [solveEvents]);
}

/** Live solver progress: plan, prices (first-order at once, exact as they land), scenarios. */
export default function Stepper({ compact = false }: { compact?: boolean }) {
  const d = useDraft();
  const live = useLive(d.solveEvents);
  const scale = live.objective === "sum" ? "z" : "wins";
  const priced = live.candTotal ? (100 * live.candDone) / live.candTotal : 0;
  return (
    <div className="solver">
      <div className="stage">
        <span className={`dot ${live.plan ? "ok" : d.solving ? "run" : "skip"}`} />
        <span className="name">Plan remaining picks</span>
        <div className="bar"><span style={{ width: live.plan ? "100%" : "0%" }} /></div>
        <span className="note">
          {live.plan
            ? `${live.plan.first_pick_name ?? live.plan.first_pick} · ${fmtObjective(live.plan.wins ?? (typeof live.plan.objective === "number" ? live.plan.objective : null), scale)}${live.plan.time_limited ? " · time limit" : ""}${live.plan.fallback ? " · sum fallback" : ""}`
            : d.solving
              ? "solving"
              : "waiting"}
        </span>
      </div>
      <div className="stage">
        <span className={`dot ${live.candTotal && live.candDone === live.candTotal ? "ok" : live.plan ? "run" : "skip"}`} />
        <span className="name">Price alternatives</span>
        <div className="bar"><span style={{ width: `${priced}%` }} /></div>
        <span className="note">
          {live.prices ? `${Object.keys(live.prices).length} first-order · ` : ""}
          {live.candDone}/{live.candTotal || "…"} exact
        </span>
      </div>
      <div className="stage">
        <span className={`dot ${live.done ? "ok" : live.scenTotal ? "run" : "skip"}`} />
        <span className="name">If he is gone</span>
        <div className="bar"><span style={{ width: `${live.scenTotal ? (100 * live.scenDone) / live.scenTotal : live.done ? 100 : 0}%` }} /></div>
        <span className="note">
          {live.scenTotal ? `${live.scenDone}/${live.scenTotal} scenarios · ` : ""}
          {fmtMs(live.elapsed)}
        </span>
      </div>
      {!compact && live.rows.length > 0 && (
        <table className="live-rows">
          <tbody>
            {live.rows.slice(0, 5).map((c) => (
              <tr key={c.player}>
                <td>{c.name}</td>
                <td className="num">{fmtObjective(c.objective, scale)}</td>
                <td className="num">{fmtCost(c.cost_vs_best, scale)}</td>
                <td className="num muted">{pct(c.p_available_next)} next</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {live.error && <p className="error">{live.error}</p>}
      {d.solveError && <p className="error">{d.solveError}</p>}
    </div>
  );
}
