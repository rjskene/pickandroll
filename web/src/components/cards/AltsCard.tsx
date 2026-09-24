import { useDraft } from "../../draft";
import { fmtCost, fmtObjective, oddsClass, pct, shortName } from "../../format";

export default function AltsCard() {
  const d = useDraft();
  const s = d.session;
  const result = d.result;
  const nextPick = s.my_next_pick;
  const pickAfter = s.my_picks.find((k) => nextPick !== null && k > nextPick);
  if (!result) return <p className="muted">{d.solving ? "Solving…" : "Appears after the first solve."}</p>;
  const scale = result.scale;
  return (
    <>
      <div className="row">
        <span className="k">{result.candidates.length - 1} alternatives to {result.candidates[0]?.name}</span>
        <span className="muted" style={{ fontSize: 11 }}>
          cost = {scale === "z" ? "z lost" : "categories won lost"} · hover for the first-order estimate
        </span>
      </div>
      {d.stale && <p className="accent" style={{ fontSize: 12 }}>Board moved since this solve · re-planning…</p>}
      <table>
        <thead>
          <tr>
            <th>Player</th>
            <th className="num">{scale === "z" ? "Value" : "Cats won"}</th>
            <th className="num">Cost</th>
            {!s.on_the_clock && nextPick && <th className="num">At #{nextPick}</th>}
            {pickAfter && <th>Lasts to #{pickAfter}</th>}
          </tr>
        </thead>
        <tbody>
          {result.candidates.slice(1).map((c) => (
            <tr key={c.player}>
              <td>
                <button className="link" onClick={() => d.draftPlayer(c.player)} title="draft this player" disabled={s.complete}>
                  {c.name}
                </button>
                {c.time_limited && <span className="dim" title="the exact re-solve hit its time limit; this is its incumbent" style={{ marginLeft: 6, fontSize: 11 }}>~</span>}
              </td>
              <td className="num">{fmtObjective(c.objective, scale)}</td>
              <td className="num" title={c.cost_first_order == null ? "" : `first-order estimate ${fmtCost(c.cost_first_order, scale, true)}`}>
                {fmtCost(c.cost_vs_best, scale)}
              </td>
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
