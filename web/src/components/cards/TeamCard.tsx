import { useQuery } from "@tanstack/react-query";
import { api, CAT_LABEL, type ScoreEntry } from "../../api";
import { useDraft } from "../../draft";
import { labelClass, oddsClass, pct, signed } from "../../format";

/** Expected categories won before my first pick against the best plan seen and the latest,
 * and at the end the final roster's odds and its head-to-head tally. */
function ScoreBlock() {
  const d = useDraft();
  const s = d.session;
  const score = useQuery({ queryKey: ["score", s.id], queryFn: () => api.score(s.id) });
  const sc = score.data;
  if (!sc) return null;
  const bench = sc.benchmark;
  const current = sc.current_wins;
  const delta = sc.vs_benchmark;
  const opponents = s.num_teams - 1;
  const cls = (x: number | null) => (x === null ? "" : x < -0.005 ? "bad" : "good");
  const when = (h: ScoreEntry | null) => (h ? ` · pick ${h.next_overall}` : "");
  return (
    <div className="block score">
      <div className="row">
        <span className="k">Score</span>
        <span className="muted" style={{ fontSize: 11 }}>
          expected categories won of {s.cats.length}
        </span>
      </div>
      <div className="stats">
        <div className="stat" title={bench ? `${bench.value.toFixed(1)} z above replacement · ${bench.matchups} of ${opponents} matchups` : ""}>
          <span className="k">Before pick 1{when(bench)}</span>
          <span className="v">{bench ? bench.wins.toFixed(2) : "—"}</span>
        </div>
        <div className="stat" title={sc.best ? `${sc.best.value.toFixed(1)} z · ${sc.best.matchups} of ${opponents} matchups` : ""}>
          <span className="k">Best during draft{when(sc.best)}</span>
          <span className="v">{sc.best ? sc.best.wins.toFixed(2) : "—"}</span>
        </div>
        <div className="stat" title={sc.final ? `${sc.final.value.toFixed(1)} z · ${sc.final.matchups} of ${opponents} matchups won on projected finals` : sc.latest ? `${sc.latest.value.toFixed(1)} z · ${sc.latest.matchups} of ${opponents} matchups` : ""}>
          <span className="k">{sc.final ? "Final" : `Now · pick ${s.next_overall}`}</span>
          <span className={`v ${cls(delta)}`}>{current === null ? "—" : current.toFixed(2)}</span>
        </div>
        <div className="stat">
          <span className="k">vs before pick 1</span>
          <span className={`v ${cls(delta)}`}>{delta === null ? "—" : signed(delta)}</span>
        </div>
        {sc.final && (
          <div className="stat" title="opponents beaten in a majority of categories, on every team's drafted roster plus replacement fill">
            <span className="k">Matchups</span>
            <span className="v">{sc.final.matchups} of {opponents}</span>
          </div>
        )}
      </div>
      {!bench && <p className="muted" style={{ fontSize: 11 }}>Frozen at the last solve before your first pick.</p>}
      {sc.history.length > 1 && (
        <table className="history">
          <tbody>
            {sc.history.filter((h) => h.on_the_clock || h === sc.history[sc.history.length - 1]).map((h) => (
              <tr key={h.version}>
                <td className="dim">#{h.next_overall}</td>
                <td>{h.top ?? ""}</td>
                <td className="num">{h.wins.toFixed(2)}</td>
                <td className={`num ${bench ? cls(h.wins - bench.wins) : ""}`}>{bench ? signed(h.wins - bench.wins) : ""}</td>
                <td className="dim num" style={{ fontSize: 11 }}>{h.matchups}/{opponents} · {h.value.toFixed(0)} z</td>
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
            final z totals if the plan holds · conceded rows dimmed
          </span>
        </div>
        <div className="profile">
          {result.categories.map((r) => {
            const width = Math.min(100, Math.max(2, (r.expected + 20) * 2));
            return (
              <div key={r.cat} className={`row ${r.label === "conceded" ? "punted" : ""}`} title={`${pct(r.odds)} to win · beats ${r.beaten_expected} of ${s.num_teams - 1} projected`}>
                <span className="lbl">{CAT_LABEL[r.cat]}</span>
                <div className="bar" style={{ flexGrow: 1 }}>
                  <span className={r.expected < 0 ? "bad" : ""} style={{ width: `${width}%` }} />
                </div>
                <span className="val">{r.expected.toFixed(1)}</span>
                <span className={`val ${labelClass(r.label)}`}>{pct(r.odds)}</span>
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
