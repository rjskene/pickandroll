import { useDraft } from "../../draft";
import { adpLabel, fmtCost, fmtObjective, oddsClass, pct, shortName } from "../../format";
import Skeleton from "../Skeleton";

export default function AltsCard() {
  const d = useDraft();
  const s = d.session;
  const result = d.result;
  const nextPick = s.my_next_pick;
  const pickAfter = s.my_picks.find((k) => nextPick !== null && k > nextPick);
  if (!result) return <p className="muted">{d.solving ? "Solving…" : "Appears after the first solve."}</p>;
  if (d.busy) return <Skeleton rows={10} note={`Re-planning for pick ${s.next_overall}…`} />;
  const scale = result.scale;
  const top = result.candidates[0];
  const tied = result.candidates.filter((c) => c.tie).length > 1;
  const band = scale === "z" ? `${result.tie_band.toFixed(1)} z` : `${result.tie_band.toFixed(2)} cats`;
  return (
    <>
      <div className="row">
        <span className="k">
          {result.candidates.length - 1} alternatives to {top?.name}
        </span>
        <span className="muted" style={{ fontSize: 11 }}>
          cost = {scale === "z" ? "z lost" : "categories won lost"} · ~ = time limit hit
        </span>
      </div>
      {tied && (
        <span className="muted" style={{ fontSize: 11 }}>
          <span className="tag tie">tie</span> = within {band} of the best: the model cannot separate them. ADP is the consensus order.
        </span>
      )}
      <table className="alts">
        <thead>
          <tr>
            <th>Player</th>
            <th className="num">{scale === "z" ? "Value" : "Cats won"}</th>
            <th className="num" title="exact re-solve with this player taken first, against the best plan · hover a cell for the first-order estimate">
              Cost
            </th>
            <th className="num" title={`average draft position: ${adpLabel(s.adp_source)}`}>
              ADP
            </th>
            {!s.on_the_clock && nextPick && (
              <th className="num" title={`chance he is still on the board at your pick ${nextPick}`}>
                At #{nextPick}
              </th>
            )}
            {pickAfter && <th title={`chance he is still on the board at your following pick, #${pickAfter}`}>Survives to #{pickAfter}</th>}
          </tr>
        </thead>
        <tbody>
          {result.candidates.map((c, i) => (
            <tr key={c.player} className={[i === 0 ? "reco" : "", c.tie ? "tie" : ""].filter(Boolean).join(" ")}>
              <td className={i === 0 ? "strong" : ""}>
                <button className="link" onClick={() => d.draftPlayer(c.player)} title="draft this player" disabled={s.complete}>
                  {c.name}
                </button>
                {i === 0 && <span className="tag accent" style={{ marginLeft: 6 }}>pick</span>}
                {i > 0 && c.tie && <span className="tag tie" style={{ marginLeft: 6 }}>tie</span>}
                {c.time_limited && <span className="dim" title="the exact re-solve hit its time limit; this is its incumbent" style={{ marginLeft: 6, fontSize: 11 }}>~</span>}
              </td>
              <td className="num">{fmtObjective(c.objective, scale)}</td>
              <td className="num" title={c.cost_first_order == null ? "exact re-solve" : `exact re-solve · first-order estimate ${fmtCost(c.cost_first_order, scale, true)}`}>
                {fmtCost(c.cost_vs_best, scale)}
              </td>
              <td className="num muted">{c.adp == null ? "" : c.adp.toFixed(0)}</td>
              {!s.on_the_clock && nextPick && <td className={`num ${oddsClass(c.p_available_first)}`}>{pct(c.p_available_first)}</td>}
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
      {result.scenarios.length > 0 && (
        <div className="block">
          <div className="row">
            <span className="k">If he is gone before #{nextPick}</span>
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
      <label className="inline muted" style={{ fontSize: 12 }}>
        candidates priced
        <input type="number" min={3} max={20} value={d.settings.n} onChange={(e) => d.setSettings({ n: Number(e.target.value) })} />
        <button className="small" onClick={d.solve}>re-solve</button>
      </label>
    </>
  );
}
