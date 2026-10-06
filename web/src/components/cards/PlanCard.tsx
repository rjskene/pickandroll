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
  // My roster in draft order: the picks logged at my slots (real and kept), then my keepers
  // still to come. Pair them with their overalls, so a keeper shows at the pick he costs.
  const kept = new Map(s.keepers.filter((k) => k.mine).map((k) => [k.player_id, k]));
  const overalls = [...s.my_slots.filter((k) => k < s.next_overall), ...s.keepers.filter((k) => k.mine && !k.applied).map((k) => k.overall)].sort((a, b) => a - b);
  const overallOf = new Map(s.my_roster.map((pid, i) => [pid, overalls[i]]));
  const mine = result.best_roster.roster
    .filter((r) => s.my_roster.includes(r.player))
    .map((r) => ({ ...r, pick: overallOf.get(r.player) ?? 0 }));
  const planned = result.plan.length
    ? result.plan
    : result.best_roster.roster.filter((r) => !s.my_roster.includes(r.player)).map((r) => ({ pick: 0, player: r.player, name: r.name, availability: 1 }));
  // One table in pick order: a keeper still to come sits between the planned picks.
  const order = (pick: number) => pick || Number.MAX_SAFE_INTEGER;
  const rows = [...mine.map((r) => ({ kind: "mine" as const, ...r })), ...planned.map((p) => ({ kind: "plan" as const, ...p }))].sort((a, b) => order(a.pick) - order(b.pick));
  const nowPlayer = s.on_the_clock && result.plan.length > 0 ? result.plan[0].player : null;
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
          {rows.map((p) => {
            if (p.kind === "mine") {
              const k = kept.get(p.player);
              return (
                <tr key={p.player} className="mine">
                  <td className="num dim">{p.pick ? `#${p.pick}` : ""}</td>
                  <td>
                    {k && (
                      <span className="kmark" title={`keeper: costs round ${k.round}`}>
                        K
                      </span>
                    )}
                    {p.name}
                  </td>
                  <td className="muted">{p.slot}</td>
                  <td className="good">{k ? `kept · R${k.round}` : "drafted"}</td>
                </tr>
              );
            }
            const now = p.player === nowPlayer;
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
