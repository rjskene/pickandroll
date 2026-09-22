import { CAT_LABEL, CATS } from "../../api";
import { useDraft } from "../../draft";
import { oddsClass, pct } from "../../format";

export default function TeamCard() {
  const d = useDraft();
  const s = d.session;
  const result = d.result;
  const drafted = s.my_roster.length;
  if (!result) {
    return (
      <>
        <div className="row">
          <span className="k">
            {drafted} of {s.roster_size} drafted
          </span>
        </div>
        <p className="muted">{d.solving ? "Solving…" : "Profile and planned roster appear after the first solve."}</p>
      </>
    );
  }
  const totals = result.best_roster.cat_totals;
  const punted = result.best_roster.punted;
  const availability = new Map(result.plan.map((p) => [p.player, p.availability]));
  const planPick = new Map(result.plan.map((p) => [p.player, p.pick]));
  const roster = [...result.best_roster.roster].sort((a, b) => a.slot_index - b.slot_index);
  return (
    <>
      <div className="block">
        <div className="row">
          <span className="k">Expected profile</span>
          <span className="muted" style={{ fontSize: 11 }}>
            z totals if the plan holds · punted rows dimmed
          </span>
        </div>
        <div className="profile">
          {CATS.map((c) => {
            const v = totals[c] ?? 0;
            const isPunted = punted.includes(c);
            const width = Math.min(100, Math.max(2, (v + 20) * 2));
            return (
              <div key={c} className={`row ${isPunted ? "punted" : ""}`}>
                <span className="lbl">{CAT_LABEL[c]}</span>
                <div className="bar" style={{ flexGrow: 1 }}>
                  <span className={v < 0 ? "bad" : ""} style={{ width: `${width}%` }} />
                </div>
                <span className="val">{v.toFixed(1)}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="block">
        <div className="row">
          <span className="k">
            Roster · {drafted} of {s.roster_size} drafted
          </span>
          <span className="muted" style={{ fontSize: 11 }}>
            italic = planned · odds still there
          </span>
        </div>
        <ul className="roster slots">
          {roster.map((r) => {
            const mine = s.my_roster.includes(r.player);
            const pick = planPick.get(r.player);
            const p = availability.get(r.player);
            const now = !mine && pick === s.next_overall && s.on_the_clock;
            return (
              <li key={`${r.slot}-${r.slot_index}`} className={mine ? "mine" : "planned"}>
                <span className="slot">{r.slot}</span>
                <span className="who">{r.name}</span>
                {!mine && pick && <span className="muted">#{pick}</span>}
                {mine ? <span className="good">drafted</span> : now ? <span className="accent">now</span> : <span className={oddsClass(p)}>{pct(p)}</span>}
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}
