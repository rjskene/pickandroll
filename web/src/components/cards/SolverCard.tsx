import { CAT_LABEL, CATS } from "../../api";
import { useDraft } from "../../draft";
import { fmtMs } from "../../format";
import Stepper from "../Stepper";

export default function SolverCard() {
  const d = useDraft();
  const { settings, setSettings, result } = d;
  const s = d.session;
  const curve = s.curve;
  return (
    <>
      <div className="block">
        <div className="row">
          <span className="k">Last solve</span>
          {result && !d.solving && (
            <span className="muted" style={{ fontSize: 11 }}>
              {fmtMs(result.timings.total_ms)} · {result.timings.solver_players ?? "?"} players modelled · for pick {result.next_overall}
            </span>
          )}
        </div>
        {d.solving || !result ? (
          <Stepper compact />
        ) : (
          <div className="solver">
            <div className="stage">
              <span className={`dot ${result.fallback ? "skip" : "ok"}`} />
              <span className="name">Plan {result.plan.length || ""} picks</span>
              <div className="bar"><span className="good" style={{ width: "100%" }} /></div>
              <span className="note">
                {fmtMs(result.timings.plan_ms ?? result.timings.total_ms)}
                {result.best_roster.time_limited ? " · time limit, incumbent kept" : ""}
                {result.fallback ? " · fell back to sum" : ""}
              </span>
            </div>
            <div className="stage">
              <span className="dot ok" />
              <span className="name">Price alternatives</span>
              <div className="bar"><span className="good" style={{ width: "100%" }} /></div>
              <span className="note">
                {result.candidates.length} exact · {fmtMs(result.timings.candidates_ms)}
              </span>
            </div>
            <div className="stage">
              <span className={`dot ${result.scenarios.length ? "ok" : "skip"}`} />
              <span className="name">If he is gone</span>
              <div className="bar"><span className="good" style={{ width: result.scenarios.length ? "100%" : "0%" }} /></div>
              <span className="note">{result.scenarios.length ? `${result.scenarios.length} scenarios` : s.on_the_clock ? "on the clock" : "none"}</span>
            </div>
          </div>
        )}
      </div>

      <div className="block">
        <div className="row">
          <span className="k">Objective</span>
          <span className="muted" style={{ fontSize: 11 }}>
            {s.objective === "win" ? "expected categories won" : "sum of z"} · {s.solver.enabled ? "re-solved in the background after every pick" : "solved on demand"}
          </span>
        </div>
        {curve ? (
          <>
            <span className="muted" style={{ fontSize: 11 }}>
              Curve: {curve.source}. A category counts for Φ((total − μ) / σ), the chance of beating a team drawn from the league.
            </span>
            <table className="curve">
              <tbody>
                <tr>
                  <td className="dim">μ</td>
                  {CATS.map((c) => (
                    <td key={c} className="num" title={CAT_LABEL[c]}>
                      {curve.mu[c]?.toFixed(1)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="dim">σ</td>
                  {CATS.map((c) => (
                    <td key={c} className="num" title={CAT_LABEL[c]}>
                      {curve.sigma[c]?.toFixed(1)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </>
        ) : (
          <span className="muted" style={{ fontSize: 11 }}>Plain sum of category z. Wins are still scored on the simulated league curve.</span>
        )}
        <span className="muted" style={{ fontSize: 11 }}>
          Availability: {s.availability_source === "survival" ? `simulated survival table (${s.survival.sims} drafts${s.survival.source ? `, ${s.survival.source}` : ""})` : `ADP formula (${s.adp_source})`}.
        </span>
      </div>

      <div className="block">
        <div className="row">
          <span className="k">Settings</span>
          <span className="muted" style={{ fontSize: 11 }}>
            apply on the next solve
          </span>
        </div>
        <div className="controls">
          <label>
            objective
            <select value={settings.objective ?? ""} onChange={(e) => setSettings({ objective: (e.target.value || null) as "win" | "sum" | null })}>
              <option value="">session default ({s.objective})</option>
              <option value="win">categories won</option>
              <option value="sum">sum of z</option>
            </select>
          </label>
          <label>
            candidates <input type="number" min={3} max={20} value={settings.n} onChange={(e) => setSettings({ n: Number(e.target.value) })} />
          </label>
          <label title="plans solved ahead for the candidates likely to be taken before your pick">
            if-gone scenarios <input type="number" min={0} max={8} value={settings.scenarios} onChange={(e) => setSettings({ scenarios: Number(e.target.value) })} />
          </label>
          {!s.solver.enabled && (
            <label>
              <input type="checkbox" checked={settings.refreshOnPick} onChange={(e) => setSettings({ refreshOnPick: e.target.checked })} /> re-solve on every pick
            </label>
          )}
          <label>
            <input type="checkbox" checked={settings.horizon} onChange={(e) => setSettings({ horizon: e.target.checked })} /> plan all remaining picks
          </label>
          <button className="small" onClick={d.solve} disabled={d.solving}>
            {d.solving ? "Solving…" : "Re-solve"} <kbd>r</kbd>
          </button>
        </div>
      </div>
    </>
  );
}
