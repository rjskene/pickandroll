import { useState } from "react";
import { CAT_LABEL, CATS, type Cat } from "../../api";
import { useDraft } from "../../draft";
import { fmtMs, puntLabel } from "../../format";
import Stepper from "../Stepper";

export default function SolverCard() {
  const d = useDraft();
  const { settings, setSettings, result } = d;
  const [showRoster, setShowRoster] = useState<string | null>(null);
  const togglePunt = (c: Cat) => setSettings({ punt: settings.punt.includes(c) ? settings.punt.filter((x) => x !== c) : [...settings.punt, c] });
  return (
    <>
      <div className="block">
        <div className="row">
          <span className="k">Last solve</span>
          {result && !d.solving && (
            <span className="muted" style={{ fontSize: 11 }}>
              {fmtMs(result.timings.total_ms)} · {result.timings.solver_players ?? "?"} players modelled
            </span>
          )}
        </div>
        {d.solving || !result ? (
          <Stepper compact />
        ) : (
          <div className="solver">
            <div className="stage">
              <span className={`dot ${result.punt_scan.length ? "ok" : "skip"}`} />
              <span className="name">Punt strategy</span>
              <div className="bar"><span className="good" style={{ width: "100%" }} /></div>
              <span className="note">{result.punt_scan.length ? `46 sets · ${fmtMs(result.timings.punt_scan_ms)}` : "fixed"}</span>
            </div>
            <div className="stage">
              <span className="dot ok" />
              <span className="name">Plan {result.plan.length || ""} picks</span>
              <div className="bar"><span className="good" style={{ width: "100%" }} /></div>
              <span className="note">{fmtMs(result.timings.plan_ms ?? result.timings.total_ms)}</span>
            </div>
            <div className="stage">
              <span className="dot ok" />
              <span className="name">Price candidates</span>
              <div className="bar"><span className="good" style={{ width: "100%" }} /></div>
              <span className="note">
                {result.candidates.length} · {fmtMs(result.timings.candidates_ms)}
              </span>
            </div>
          </div>
        )}
      </div>

      {result && !d.solving && result.punt_scan.length > 0 && (
        <div className="block">
          <div className="row">
            <span className="k">Punt strategies</span>
            <span className="muted" style={{ fontSize: 11 }}>
              click to pin · hover for the roster
            </span>
          </div>
          <div className="punts">
            {result.punt_scan.slice(0, 6).map((row, i) => (
              <button
                key={row.punt}
                className={`pill clickable ${i === 0 ? "hot" : ""}`}
                onClick={() => d.pinPunt(row.punt)}
                onMouseEnter={() => setShowRoster(row.punt)}
                onMouseLeave={() => setShowRoster(null)}
                title={row.roster.join(", ")}
              >
                {puntLabel(row.punt)} · {i === 0 ? row.objective.toFixed(2) : `−${row.gap_to_best.toFixed(2)}`}
              </button>
            ))}
          </div>
          {showRoster && (
            <span className="muted" style={{ fontSize: 11 }}>
              {result.punt_scan.find((r) => r.punt === showRoster)?.roster.join(", ")}
            </span>
          )}
        </div>
      )}

      <div className="block">
        <div className="row">
          <span className="k">Settings</span>
          <span className="muted" style={{ fontSize: 11 }}>
            apply on the next solve
          </span>
        </div>
        <div className="controls">
          <label>
            <input type="checkbox" checked={settings.auto} onChange={(e) => setSettings({ auto: e.target.checked })} /> choose punts automatically
          </label>
          {settings.auto ? (
            <label>
              max punts <input type="number" min={0} max={4} value={settings.maxPunts} onChange={(e) => setSettings({ maxPunts: Number(e.target.value) })} />
            </label>
          ) : (
            <div className="punts">
              {CATS.map((c) => (
                <label key={c} className={`chip ${settings.punt.includes(c) ? "on" : ""}`}>
                  <input type="checkbox" checked={settings.punt.includes(c)} onChange={() => togglePunt(c)} />
                  punt {CAT_LABEL[c]}
                </label>
              ))}
            </div>
          )}
          <label>
            balance {settings.balance.toFixed(2)} <input type="range" min={0} max={1} step={0.05} value={settings.balance} onChange={(e) => setSettings({ balance: Number(e.target.value) })} />
          </label>
          <label>
            candidates <input type="number" min={3} max={20} value={settings.n} onChange={(e) => setSettings({ n: Number(e.target.value) })} />
          </label>
          <label>
            <input type="checkbox" checked={settings.refreshOnPick} onChange={(e) => setSettings({ refreshOnPick: e.target.checked })} /> re-solve on every pick
          </label>
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
