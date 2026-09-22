import { useDraft } from "../../draft";
import { oddsClass, pct, puntLabel, shortName } from "../../format";
import Stepper from "../Stepper";

export default function PickCard() {
  const d = useDraft();
  const s = d.session;
  const result = d.result;
  const top = result?.candidates[0];
  const nextPick = s.my_next_pick;
  const pickAfter = s.my_picks.find((k) => nextPick !== null && k > nextPick);
  const strategy = result ? puntLabel(result.punted.join("/") || "-") : d.settings.auto ? "auto" : puntLabel(d.settings.punt.join("/") || "-");
  const label = s.complete ? "Draft complete" : s.on_the_clock ? "Recommended pick" : nextPick ? `Recommended for your pick ${nextPick}` : "No picks left";

  return (
    <>
      <div className="hero">
        <div className="row">
          <span className="k">{label}</span>
          <span className="grow" />
          <button className="small" onClick={d.solve} disabled={d.solving} title="Re-solve (r)">
            {d.solving ? "Solving…" : "Re-solve"} <kbd>r</kbd>
          </button>
        </div>
        {top && !d.solving ? (
          <>
            <div className="name">{top.name}</div>
            <div className="muted" style={{ fontSize: 12 }}>
              {result?.mode === "horizon" ? "rolling-horizon plan" : "single roster"} · ADP from {result?.adp_source}
            </div>
            <div className="stats">
              <div className="stat">
                <span className="k">Plan value</span>
                <span className="v accent">{top.objective.toFixed(2)}</span>
              </div>
              {!s.on_the_clock && nextPick && (
                <div className="stat">
                  <span className="k">Still there at #{nextPick}</span>
                  <span className={`v ${oddsClass(top.p_available_first)}`}>{pct(top.p_available_first)}</span>
                </div>
              )}
              {pickAfter && (
                <div className="stat">
                  <span className="k">Lasts to #{pickAfter}</span>
                  <span className={`v ${oddsClass(top.p_available_next)}`}>{pct(top.p_available_next)}</span>
                </div>
              )}
              <div className="stat">
                <span className="k">Strategy</span>
                <span className="v">{strategy}</span>
              </div>
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
          <Stepper />
        )}
        {d.pickError && <p className="error">{d.pickError}</p>}
      </div>

      {result && !d.solving && result.candidates.length > 1 && (
        <div className="block">
          <div className="row">
            <span className="k">Next best</span>
            <span className="muted" style={{ fontSize: 11 }}>
              cost = plan value lost{pickAfter ? ` · lasts to #${pickAfter}` : ""}
            </span>
          </div>
          <table>
            <tbody>
              {result.candidates.slice(1, 4).map((c) => (
                <tr key={c.player}>
                  <td>
                    <button className="link" onClick={() => d.draftPlayer(c.player)} title="draft this player" disabled={s.complete}>
                      {c.name}
                    </button>
                  </td>
                  <td className="num">−{c.cost_vs_best.toFixed(2)}</td>
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
            all {result.candidates.length - 1} alternatives <kbd>⇧2</kbd>
          </button>
        </div>
      )}
    </>
  );
}
