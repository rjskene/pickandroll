import { useDraft } from "../../draft";
import { fmtObjective, oddsClass, pct, shortName } from "../../format";

export default function PlanCard() {
  const d = useDraft();
  const s = d.session;
  const result = d.result;
  if (!result) return <p className="muted">{d.solving ? "Solving…" : "Appears after the first solve."}</p>;
  return (
    <>
      {d.stale && <p className="accent" style={{ fontSize: 12 }}>Board moved since this solve · re-planning…</p>}
      {result.plan.length > 0 && (
        <div className="block">
          <div className="row">
            <span className="k">Plan for your {result.plan.length} remaining picks</span>
            <span className="muted" style={{ fontSize: 11 }}>
              chance each is still there
            </span>
          </div>
          <div className="plan">
            {result.plan.map((p, i) => {
              const now = i === 0 && s.on_the_clock;
              return (
                <div key={p.pick} className={`pick ${now ? "now" : ""}`} title={p.name}>
                  <div className="n">#{p.pick}</div>
                  <div className="who">{shortName(p.name)}</div>
                  <div className={now ? "" : oddsClass(p.availability)}>{now ? "now" : pct(p.availability)}</div>
                </div>
              );
            })}
          </div>
          <span className="muted" style={{ fontSize: 11 }}>
            Re-solved after every pick. Later picks are the plan's best guess, not a commitment.
          </span>
        </div>
      )}
      <div className="block">
        <div className="row">
          <span className="k">{result.mode === "horizon" ? "Expected roster if the plan holds" : "Best roster from here"}</span>
          <span className="muted" style={{ fontSize: 11 }}>
            {fmtObjective(result.wins, "wins")} expected · {result.value.toFixed(1)} z above replacement
            {result.best_roster.time_limited ? " · time limit hit" : ""}
          </span>
        </div>
        <ul className="roster" style={{ columns: 2, columnGap: 16 }}>
          {result.best_roster.roster.map((r) => (
            <li key={`${r.slot}-${r.slot_index}`} className={s.my_roster.includes(r.player) ? "mine" : ""} style={{ breakInside: "avoid" }}>
              <span className="slot">{r.slot}</span> {r.name}
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
