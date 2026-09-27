import { useDraft } from "../../draft";
import { fmtCost, fmtObjective, oddsClass, pct, shortName } from "../../format";
import CatStrip from "../CatStrip";
import Skeleton from "../Skeleton";
import Stepper from "../Stepper";

export default function PickCard() {
  const d = useDraft();
  const s = d.session;
  const result = d.result;
  const top = result?.candidates[0];
  const nextPick = s.my_next_pick;
  const pickAfter = s.my_picks.find((k) => nextPick !== null && k > nextPick);
  const label = s.complete ? "Draft complete" : s.on_the_clock ? "Recommended pick" : nextPick ? `Recommended for your pick ${nextPick}` : "No picks left";
  const scale = result?.scale;
  // While a solve runs, or the answer is for an earlier board, the hero shows the solver's
  // progress instead of a name that may just have been drafted.
  const ready = !!result && !!top && !d.busy;
  const ties = result && !d.busy ? result.candidates.filter((c) => c.tie) : [];
  const tied = ties.length > 1;
  const band = result ? (scale === "z" ? `${result.tie_band.toFixed(1)} z` : `${result.tie_band.toFixed(2)} cats`) : "";

  return (
    <>
      <div className="hero">
        <div className="row">
          <span className="k">{label}</span>
          {tied && (
            <span className="pill tie" title={`${ties.length} candidates within ${band} of the best: the model cannot separate them`}>
              TIE
            </span>
          )}
          <span className="grow" />
          <button className="small" onClick={d.solve} disabled={d.solving} title="Re-solve (r)">
            {d.solving ? "Solving…" : "Re-solve"} <kbd>r</kbd>
          </button>
        </div>
        {ready && result && top ? (
          <>
            <div className="name">{top.name}</div>
            {tied && (
              <div className="tie-list">
                <span className="muted">or</span>
                {ties
                  .filter((c) => c.player !== top.player)
                  .map((c) => (
                    <button key={c.player} className="link" onClick={() => d.draftPlayer(c.player)} title={`draft ${c.name}`} disabled={s.complete}>
                      {c.name}{" "}
                      <span className="dim">
                        {fmtCost(c.cost_vs_best, scale)}
                        {c.adp != null ? ` · ADP ${c.adp.toFixed(0)}` : ""}
                      </span>
                    </button>
                  ))}
                <span className="dim">
                  within {band}
                  {top.adp != null ? ` · ${shortName(top.name)} ADP ${top.adp.toFixed(0)}` : ""}
                </span>
              </div>
            )}
            <CatStrip rows={result.categories} />
            <div className="muted" style={{ fontSize: 12 }}>
              {result.mode === "horizon" ? "rolling-horizon plan" : "single roster"} · {result.objective === "win" ? "expected categories won" : "sum of z"}
              {result.fallback ? " · sum fallback (no incumbent in time)" : ""} · survival odds from {result.availability_source === "survival" ? "simulated drafts" : "the ADP formula"}
            </div>
            <div className="stats">
              <div className="stat" title="expected number of the nine categories won if the plan holds">
                <span className="k">{scale === "z" ? "Plan value" : "Expected cats won"}</span>
                <span className="v accent">{fmtObjective(result.wins, "wins")}</span>
              </div>
              <div className="stat" title="opponents beaten in a majority of categories on projected finals">
                <span className="k">Matchups</span>
                <span className="v">{result.league.matchups_won} of {result.league.opponents.length}</span>
              </div>
              {!s.on_the_clock && nextPick && (
                <div className="stat" title={`chance he is still on the board at your pick ${nextPick}`}>
                  <span className="k">Survives to #{nextPick}</span>
                  <span className={`v ${oddsClass(top.p_available_first)}`}>{pct(top.p_available_first)}</span>
                </div>
              )}
              {pickAfter && (
                <div className="stat" title={`chance he is still on the board at your following pick, #${pickAfter}`}>
                  <span className="k">Survives to #{pickAfter}</span>
                  <span className={`v ${oddsClass(top.p_available_next)}`}>{pct(top.p_available_next)}</span>
                </div>
              )}
            </div>
            {!s.complete && (
              <div className="row">
                <button className="primary" style={{ fontSize: 15, padding: "9px 18px" }} onClick={() => d.draftPlayer(top.player)} disabled={d.drafting} title="Draft the recommended pick (d)">
                  Draft {shortName(top.name)}
                  {s.on_the_clock ? "" : ` to ${d.draftingTeam}`} <kbd>d</kbd>
                </button>
              </div>
            )}
          </>
        ) : (
          <>
            {result && d.busy && (
              <span className="accent" style={{ fontSize: 12 }}>
                Re-planning for pick {s.next_overall}…
              </span>
            )}
            <Stepper />
          </>
        )}
        {d.pickError && <p className="error">{d.pickError}</p>}
      </div>

      {ready && result && result.candidates.length > 1 && (
        <div className="block">
          <div className="row">
            <span className="k">Next best</span>
            <span className="muted" style={{ fontSize: 11 }}>
              cost = {scale === "z" ? "z lost" : "categories won lost"}{pickAfter ? ` · survives to #${pickAfter}` : ""}
            </span>
          </div>
          <table>
            <tbody>
              {result.candidates.slice(1, 4).map((c) => (
                <tr key={c.player} className={c.tie ? "tie" : ""}>
                  <td>
                    <button className="link" onClick={() => d.draftPlayer(c.player)} title="draft this player" disabled={s.complete}>
                      {c.name}
                    </button>
                    {c.tie && <span className="tag tie" style={{ marginLeft: 6 }}>tie</span>}
                  </td>
                  <td className="num" title={c.cost_first_order == null ? "exact re-solve" : `exact re-solve · first-order estimate ${fmtCost(c.cost_first_order, scale, true)}`}>
                    {fmtCost(c.cost_vs_best, scale)}
                  </td>
                  {pickAfter && (
                    <td>
                      <span className="survival">
                        <span className="bar">
                          <span className={oddsClass(c.p_available_next)} style={{ width: pct(c.p_available_next) }} />
                        </span>
                        <span className="muted">{pct(c.p_available_next)}</span>
                      </span>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <button className="link" style={{ fontSize: 12 }} onClick={() => d.openCard("alts", "bottom")}>
            all {result.candidates.length - 1} alternatives <kbd>⇧3</kbd>
          </button>
        </div>
      )}

      {ready && result && result.scenarios.length > 0 && (
        <div className="block">
          <div className="row">
            <span className="k">If he is gone before #{nextPick}</span>
            <span className="muted" style={{ fontSize: 11 }}>
              solved ahead, ready when your pick comes
            </span>
          </div>
          <table>
            <tbody>
              {result.scenarios.map((sc) => (
                <tr key={sc.gone}>
                  <td className="muted">{shortName(sc.gone_name)} taken</td>
                  <td>
                    → <strong>{sc.pick_name ?? "—"}</strong>
                  </td>
                  <td className="num muted">{fmtObjective(sc.wins ?? sc.objective, scale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {result && d.busy && (
        <div className="block">
          <Skeleton rows={4} />
        </div>
      )}
    </>
  );
}
