import { useDraft } from "../../draft";
import { oddsClass, pct } from "../../format";

export default function AltsCard() {
  const d = useDraft();
  const s = d.session;
  const result = d.result;
  const nextPick = s.my_next_pick;
  const pickAfter = s.my_picks.find((k) => nextPick !== null && k > nextPick);
  if (d.solving) return <p className="muted">Solving…</p>;
  if (!result) return <p className="muted">Appears after the first solve.</p>;
  return (
    <>
      <div className="row">
        <span className="k">{result.candidates.length - 1} alternatives to {result.candidates[0]?.name}</span>
        <span className="muted" style={{ fontSize: 11 }}>
          cost = plan value lost
        </span>
      </div>
      <table>
        <thead>
          <tr>
            <th>Player</th>
            <th className="num">Value</th>
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
                {c.punted && <span className="dim" style={{ marginLeft: 6, fontSize: 11 }}>{c.punted}</span>}
              </td>
              <td className="num">{c.objective.toFixed(2)}</td>
              <td className="num">−{c.cost_vs_best.toFixed(2)}</td>
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
      <label className="inline muted" style={{ fontSize: 12 }}>
        candidates priced
        <input type="number" min={3} max={20} value={d.settings.n} onChange={(e) => d.setSettings({ n: Number(e.target.value) })} />
        <button className="small" onClick={d.solve}>re-solve</button>
      </label>
    </>
  );
}
