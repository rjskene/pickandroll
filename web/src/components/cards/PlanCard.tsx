import { useDraft } from "../../draft";
import { fmtObjective, oddsClass, pct } from "../../format";
import Skeleton from "../Skeleton";

/** The whole roster as one table, one player per row: the picks already made, then the plan
 * for every remaining pick with the odds the player is still there when it comes. */
export default function PlanCard() {
  const d = useDraft();
  const s = d.session;
  const result = d.result;
  if (!result) return <p className="muted">{d.solving ? "Solving…" : "Appears after the first solve."}</p>;
  if (d.busy) return <Skeleton rows={s.roster_size} note={`Re-planning for pick ${s.next_overall}…`} />;
  const slotOf = new Map(result.best_roster.roster.map((r) => [r.player, r.slot]));
  const mine = result.best_roster.roster.filter((r) => s.my_roster.includes(r.player)).sort((a, b) => s.my_roster.indexOf(a.player) - s.my_roster.indexOf(b.player));
  const pastPicks = s.my_picks.filter((k) => k < s.next_overall);
  const planned = result.plan.length
    ? result.plan
    : result.best_roster.roster.filter((r) => !s.my_roster.includes(r.player)).map((r) => ({ pick: 0, player: r.player, name: r.name, availability: 1 }));
  return (
    <>
      <div className="row">
        <span className="k">{result.plan.length ? `Plan for your ${result.plan.length} remaining picks` : "Best roster from here"}</span>
        <span className="muted" style={{ fontSize: 11 }}>
          {fmtObjective(result.wins, "wins")} expected · {result.value.toFixed(1)} z above replacement
          {result.best_roster.time_limited ? " · time limit hit" : ""}
        </span>
      </div>
      <table className="plan">
        <thead>
          <tr>
            <th className="num">Pick</th>
            <th>Player</th>
            <th>Slot</th>
            <th title="chance he is still on the board when that pick comes">Survives</th>
          </tr>
        </thead>
        <tbody>
          {mine.map((r, i) => (
            <tr key={r.player} className="mine">
              <td className="num dim">{pastPicks[i] ? `#${pastPicks[i]}` : ""}</td>
              <td>{r.name}</td>
              <td className="muted">{r.slot}</td>
              <td className="good">drafted</td>
            </tr>
          ))}
          {planned.map((p, i) => {
            const now = i === 0 && s.on_the_clock && result.plan.length > 0;
            return (
              <tr key={p.player} className={now ? "now" : ""}>
                <td className="num">{p.pick ? `#${p.pick}` : ""}</td>
                <td className={now ? "strong" : ""}>
                  {now ? (
                    <button className="link" onClick={() => d.draftPlayer(p.player)} title="draft this player (d)" disabled={s.complete}>
                      {p.name}
                    </button>
                  ) : (
                    p.name
                  )}
                </td>
                <td className="muted">{slotOf.get(p.player) ?? ""}</td>
                <td>
                  {now ? (
                    <span className="accent">now</span>
                  ) : (
                    <span className="survival">
                      <span className="bar">
                        <span className={oddsClass(p.availability)} style={{ width: pct(p.availability) }} />
                      </span>
                      <span className="muted">{pct(p.availability)}</span>
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <span className="muted" style={{ fontSize: 11 }}>
        Re-solved after every pick. Later picks are the plan's best guess, not a commitment.
      </span>
    </>
  );
}
