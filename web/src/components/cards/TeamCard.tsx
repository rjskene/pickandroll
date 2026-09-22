import { useQuery } from "@tanstack/react-query";
import { api, CAT_LABEL, CATS } from "../../api";
import { useDraft } from "../../draft";
import { oddsClass, pct } from "../../format";

function signed(x: number): string {
  return `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(2)}`;
}

/** The plan value frozen at my first pick against the best value still reachable, and at the end the final score. */
function ScoreBlock() {
  const d = useDraft();
  const s = d.session;
  const score = useQuery({ queryKey: ["score", s.id], queryFn: () => api.score(s.id) });
  const sc = score.data;
  if (!sc) return null;
  const bench = sc.benchmark;
  const current = sc.final ?? sc.latest?.value ?? null;
  const delta = bench && current !== null ? current - bench.value : null;
  return (
    <div className="block score">
      <div className="row">
        <span className="k">Score</span>
        <span className="muted" style={{ fontSize: 11 }}>
          plan value: z above replacement, {sc.punted.length ? `punting ${sc.punted.map((c) => CAT_LABEL[c]).join(", ")}` : "no punt"}
        </span>
      </div>
      <div className="stats">
        <div className="stat">
          <span className="k">{bench ? `Benchmark · pick ${bench.next_overall}` : "Benchmark"}</span>
          <span className="v">{bench ? bench.value.toFixed(2) : "—"}</span>
        </div>
        <div className="stat">
          <span className="k">{sc.final !== null ? "Final" : sc.latest ? `Best now · pick ${sc.latest.next_overall}` : "Best now"}</span>
          <span className={`v ${delta === null ? "" : delta < -0.005 ? "bad" : "good"}`}>{current === null ? "—" : current.toFixed(2)}</span>
        </div>
        <div className="stat">
          <span className="k">vs benchmark</span>
          <span className={`v ${delta === null ? "" : delta < -0.005 ? "bad" : "good"}`}>{delta === null ? "—" : signed(delta)}</span>
        </div>
        <div className="stat">
          <span className="k">Drafted so far</span>
          <span className="v">{sc.drafted_value.toFixed(2)}</span>
        </div>
      </div>
      {!bench && <p className="muted" style={{ fontSize: 11 }}>Frozen when you are on the clock at your first pick.</p>}
      {sc.history.length > 1 && (
        <table className="history">
          <tbody>
            {sc.history.map((h) => (
              <tr key={h.version}>
                <td className="dim">#{h.next_overall}</td>
                <td>{h.top ?? ""}</td>
                <td className="num">{h.value.toFixed(2)}</td>
                <td className={`num ${bench ? (h.value - bench.value < -0.005 ? "bad" : "good") : ""}`}>{bench ? signed(h.value - bench.value) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function TeamCard() {
  const d = useDraft();
  const s = d.session;
  const result = d.result;
  const drafted = s.my_roster.length;
  if (!result) {
    return (
      <>
        <ScoreBlock />
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
      <ScoreBlock />
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
