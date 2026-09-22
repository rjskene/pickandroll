import { useMemo } from "react";
import type { Candidate, SolveEvent } from "../api";
import { useDraft } from "../draft";
import { fmtMs, pct, puntLabel } from "../format";

export function useLive(solveEvents: SolveEvent[]) {
  return useMemo(() => {
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
}

/** Live solver progress: the three stages with bars, plus the candidates priced so far. */
export default function Stepper({ compact = false }: { compact?: boolean }) {
  const d = useDraft();
  const live = useLive(d.solveEvents);
  const fixed = puntLabel(d.settings.punt.join("/") || "-");
  return (
    <div className="solver">
      <div className="stage">
        <span className={`dot ${live.autoPunt ? (live.scanTotal && live.scanDone === live.scanTotal ? "ok" : "run") : "skip"}`} />
        <span className="name">Punt strategy</span>
        {live.autoPunt ? (
          <>
            <div className="bar"><span style={{ width: `${live.scanTotal ? (100 * live.scanDone) / live.scanTotal : 0}%` }} /></div>
            <span className="note">
              {live.scanDone}/{live.scanTotal || "…"} sets{live.best ? ` · best ${puntLabel(live.best.best_punt ?? "-")} ${live.best.best_objective?.toFixed(2)}` : ""}
            </span>
          </>
        ) : (
          <>
            <span />
            <span className="note">fixed: {fixed}</span>
          </>
        )}
      </div>
      <div className="stage">
        <span className={`dot ${live.plan ? "ok" : !live.autoPunt || live.scanDone === live.scanTotal ? "run" : "skip"}`} />
        <span className="name">Plan remaining picks</span>
        <div className="bar"><span style={{ width: live.plan ? "100%" : "0%" }} /></div>
        <span className="note">{live.plan ? `first ${live.plan.first_pick_name ?? live.plan.first_pick}, ${live.plan.objective?.toFixed(2)}` : "waiting"}</span>
      </div>
      <div className="stage">
        <span className={`dot ${live.candTotal && live.candDone === live.candTotal ? "ok" : live.plan ? "run" : "skip"}`} />
        <span className="name">Price candidates</span>
        <div className="bar"><span style={{ width: `${live.candTotal ? (100 * live.candDone) / live.candTotal : 0}%` }} /></div>
        <span className="note">
          {live.candDone}/{live.candTotal || "…"} · {fmtMs(live.elapsed)}
        </span>
      </div>
      {!compact && live.rows.length > 0 && (
        <table className="live-rows">
          <tbody>
            {live.rows.slice(0, 5).map((c) => (
              <tr key={c.player}>
                <td>{c.name}</td>
                <td className="num">{c.objective.toFixed(2)}</td>
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
