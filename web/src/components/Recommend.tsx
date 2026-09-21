import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  api,
  CAT_LABEL,
  CATS,
  pickOwner,
  teamLabel,
  type Candidate,
  type Cat,
  type Recommendation,
  type SessionSummary,
  type SolveEvent,
} from "../api";

interface Props {
  session: SessionSummary;
  solveEvents: SolveEvent[];
  onResult: (r: Recommendation) => void;
}

function parsePunt(label: string): Cat[] {
  return label === "-" ? [] : (label.split("/") as Cat[]);
}
function puntLabel(label: string): string {
  return label === "-" ? "no punt" : label.split("/").map((c) => CAT_LABEL[c as Cat]).join(" + ");
}
function fmtMs(ms: number | undefined): string {
  if (ms === undefined) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}
function pct(x: number | undefined): string {
  return `${Math.round((x ?? 0) * 100)}%`;
}
function shortName(name: string): string {
  const parts = name.split(" ");
  return parts.length > 1 ? `${parts[0][0]}. ${parts.slice(1).join(" ")}` : name;
}

export default function Recommend({ session, solveEvents, onResult }: Props) {
  const queryClient = useQueryClient();
  const [auto, setAuto] = useState(true);
  const [punt, setPunt] = useState<Cat[]>([]);
  const [maxPunts, setMaxPunts] = useState(2);
  const [balance, setBalance] = useState(0);
  const [n, setN] = useState(8);
  const [refreshOnPick, setRefreshOnPick] = useState(true);
  const [horizon, setHorizon] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [showRoster, setShowRoster] = useState<string | null>(null);

  const params = { n, punt: auto ? null : punt, max_punts: maxPunts, balance, horizon };
  const recommend = useMutation({
    mutationFn: () => api.recommend(session.id, params),
    onSuccess: (r) => onResult(r),
  });
  const { mutate } = recommend;
  const owner = pickOwner(session.num_teams, session.next_overall);
  const onClockTeam = teamLabel(session, owner.position);

  const draft = useMutation({
    mutationFn: (playerId: string) => api.addPick(session.id, { team: onClockTeam, player_id: playerId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["session", session.id] });
      queryClient.invalidateQueries({ queryKey: ["board", session.id] });
      queryClient.invalidateQueries({ queryKey: ["picks", session.id] });
    },
  });

  const solvedFor = useRef<string>("");
  useEffect(() => {
    const key = `${session.id}:${session.version}`;
    if (refreshOnPick && !session.complete && solvedFor.current !== key) {
      solvedFor.current = key;
      mutate();
    }
  }, [session.id, session.version, session.complete, refreshOnPick, mutate]);

  const togglePunt = (c: Cat) => setPunt((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]));
  const pinPunt = (label: string) => {
    setAuto(false);
    setPunt(parsePunt(label));
    setTimeout(() => mutate(), 0);
  };
  const result = recommend.data;
  const top: Candidate | undefined = result?.candidates[0];
  const nextPick = session.my_next_pick;
  const pickAfter = session.my_picks.find((k) => nextPick !== null && k > nextPick);

  const live = useMemo(() => {
    const scan = solveEvents.filter((e) => e.stage === "punt_scan");
    const plan = solveEvents.find((e) => e.stage === "plan");
    const cands = solveEvents.filter((e) => e.stage === "candidates");
    const last = solveEvents[solveEvents.length - 1];
    const rows = new Map<string, Candidate>();
    for (const e of cands) if (e.candidate && !e.candidate.failed) rows.set(e.candidate.player, e.candidate);
    return {
      scanDone: scan.length ? scan[scan.length - 1].done : 0,
      scanTotal: scan.length ? scan[scan.length - 1].total : 0,
      best: scan.length ? scan[scan.length - 1] : undefined,
      plan,
      candDone: cands.length ? cands[cands.length - 1].done : 0,
      candTotal: cands.length ? cands[cands.length - 1].total : 0,
      rows: [...rows.values()].sort((x, y) => y.objective - x.objective),
      elapsed: last?.elapsed_ms ?? 0,
      autoPunt: solveEvents[0]?.auto_punt ?? true,
      error: solveEvents.find((e) => e.stage === "error")?.message,
    };
  }, [solveEvents]);

  const strategy = result ? puntLabel(result.punted.join("/") || "-") : auto ? "auto" : puntLabel(punt.join("/") || "-");

  return (
    <>
      <section className="hero">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="k">{session.on_the_clock ? "Recommended pick" : nextPick ? `Recommended for your pick ${nextPick}` : "Draft complete"}</span>
          <span style={{ flexGrow: 1 }} />
          <button className="small" onClick={() => mutate()} disabled={recommend.isPending}>
            {recommend.isPending ? "Solving…" : "Re-solve"}
          </button>
          <button className="small" onClick={() => setShowSettings((v) => !v)}>
            {showSettings ? "Hide settings" : "Settings"}
          </button>
        </div>
        {top && !recommend.isPending ? (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap" }}>
              <div className="name">{top.name}</div>
              <div className="muted">
                {result?.mode === "horizon" ? "rolling-horizon plan" : "single roster"} · ADP from {result?.adp_source}
              </div>
            </div>
            <div className="stats">
              <div className="stat">
                <span className="k">Plan value</span>
                <span className="v accent">{top.objective.toFixed(2)}</span>
              </div>
              {!session.on_the_clock && (
                <div className="stat">
                  <span className="k">Still there at #{nextPick}</span>
                  <span className={`v ${(top.p_available_first ?? 0) < 0.5 ? "bad" : "good"}`}>{pct(top.p_available_first)}</span>
                </div>
              )}
              {pickAfter && (
                <div className="stat">
                  <span className="k">Lasts to #{pickAfter}</span>
                  <span className={`v ${(top.p_available_next ?? 0) < 0.5 ? "bad" : "good"}`}>{pct(top.p_available_next)}</span>
                </div>
              )}
              <div className="stat">
                <span className="k">Strategy</span>
                <span className="v">{strategy}</span>
              </div>
              <div className="grow" />
              {!session.complete && (
                <button className="primary" style={{ fontSize: 15, padding: "9px 18px" }} onClick={() => draft.mutate(top.player)} disabled={draft.isPending}>
                  Draft {shortName(top.name)} {session.on_the_clock ? "" : `to ${onClockTeam}`}
                </button>
              )}
            </div>
          </>
        ) : (
          <div className="solver">
            <div className="stage">
              <span className={`dot ${live.autoPunt ? (live.scanTotal && live.scanDone === live.scanTotal ? "ok" : "run") : "skip"}`} />
              <span className="name">Punt strategy</span>
              {live.autoPunt ? (
                <>
                  <div className="bar"><span style={{ width: `${live.scanTotal ? (100 * live.scanDone) / live.scanTotal : 0}%` }} /></div>
                  <span className="note">
                    {live.scanDone}/{live.scanTotal || "…"} sets{live.best ? ` · best ${puntLabel(live.best.best_punt ?? "-")} ${live.best.best_objective?.toFixed(2)}` : ""}
                  </span>
                </>
              ) : (
                <>
                  <span />
                  <span className="note">fixed: {puntLabel(punt.join("/") || "-")}</span>
                </>
              )}
            </div>
            <div className="stage">
              <span className={`dot ${live.plan ? "ok" : !live.autoPunt || live.scanDone === live.scanTotal ? "run" : "skip"}`} />
              <span className="name">Plan remaining picks</span>
              <div className="bar"><span style={{ width: live.plan ? "100%" : "0%" }} /></div>
              <span className="note">{live.plan ? `first ${live.plan.first_pick_name ?? live.plan.first_pick}, ${live.plan.objective?.toFixed(2)}` : "waiting"}</span>
            </div>
            <div className="stage">
              <span className={`dot ${live.candTotal && live.candDone === live.candTotal ? "ok" : live.plan ? "run" : "skip"}`} />
              <span className="name">Price candidates</span>
              <div className="bar"><span style={{ width: `${live.candTotal ? (100 * live.candDone) / live.candTotal : 0}%` }} /></div>
              <span className="note">
                {live.candDone}/{live.candTotal || "…"} · {fmtMs(live.elapsed)}
              </span>
            </div>
            {live.rows.length > 0 && (
              <table className="live-rows">
                <tbody>
                  {live.rows.slice(0, 5).map((c) => (
                    <tr key={c.player}>
                      <td>{c.name}</td>
                      <td className="num">{c.objective.toFixed(2)}</td>
                      <td className="num muted">{pct(c.p_available_next)} next</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {live.error && <p className="error">{live.error}</p>}
            {recommend.error && <p className="error">{recommend.error.message}</p>}
          </div>
        )}
        {showSettings && (
          <div className="controls">
            <label>
              <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> choose punts automatically
            </label>
            {auto ? (
              <label>
                max punts <input type="number" min={0} max={4} value={maxPunts} onChange={(e) => setMaxPunts(+e.target.value)} />
              </label>
            ) : (
              <div className="punts">
                {CATS.map((c) => (
                  <label key={c} className={`chip ${punt.includes(c) ? "on" : ""}`}>
                    <input type="checkbox" checked={punt.includes(c)} onChange={() => togglePunt(c)} />
                    punt {CAT_LABEL[c]}
                  </label>
                ))}
              </div>
            )}
            <label>
              balance {balance.toFixed(2)} <input type="range" min={0} max={1} step={0.05} value={balance} onChange={(e) => setBalance(+e.target.value)} />
            </label>
            <label>
              candidates <input type="number" min={3} max={20} value={n} onChange={(e) => setN(+e.target.value)} />
            </label>
            <label>
              <input type="checkbox" checked={refreshOnPick} onChange={(e) => setRefreshOnPick(e.target.checked)} /> re-solve on every pick
            </label>
            <label>
              <input type="checkbox" checked={horizon} onChange={(e) => setHorizon(e.target.checked)} /> plan all remaining picks
            </label>
          </div>
        )}
      </section>

      {result && !recommend.isPending && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 12 }}>
            <section className="panel">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
                <span className="k">Alternatives</span>
                <span className="muted" style={{ fontSize: 11 }}>
                  cost = plan value lost{pickAfter ? ` · odds he lasts to #${pickAfter}` : ""}
                </span>
              </div>
              <table>
                <thead>
                  <tr>
                    <th>Player</th>
                    <th className="num">Value</th>
                    <th className="num">Cost</th>
                    {!session.on_the_clock && nextPick && <th className="num">At #{nextPick}</th>}
                    {pickAfter && <th style={{ width: 120 }}>Lasts to #{pickAfter}</th>}
                  </tr>
                </thead>
                <tbody>
                  {result.candidates.slice(1).map((c) => (
                    <tr key={c.player}>
                      <td>
                        <button className="link" onClick={() => !session.complete && draft.mutate(c.player)} title="draft this player">
                          {c.name}
                        </button>
                      </td>
                      <td className="num">{c.objective.toFixed(2)}</td>
                      <td className="num">{c.cost_vs_best.toFixed(2)}</td>
                      {!session.on_the_clock && nextPick && <td className="num">{pct(c.p_available_first)}</td>}
                      {pickAfter && (
                        <td>
                          <div className="bar">
                            <span className={(c.p_available_next ?? 0) < 0.4 ? "bad" : ""} style={{ width: pct(c.p_available_next) }} />
                          </div>
                          <span className="muted" style={{ fontSize: 11 }}>
                            {pct(c.p_available_next)}
                          </span>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section className="panel" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <span className="k">Solver</span>
                <span className="muted" style={{ fontSize: 11 }}>
                  {fmtMs(result.timings.total_ms)} · {result.timings.solver_players ?? "?"} players modelled
                </span>
              </div>
              <div className="solver">
                <div className="stage">
                  <span className={`dot ${result.punt_scan.length ? "ok" : "skip"}`} />
                  <span className="name">Punt strategy</span>
                  <div className="bar"><span className="good" style={{ width: "100%" }} /></div>
                  <span className="note">{result.punt_scan.length ? `46 sets · ${fmtMs(result.timings.punt_scan_ms)}` : "fixed"}</span>
                </div>
                <div className="stage">
                  <span className="dot ok" />
                  <span className="name">Plan {result.plan.length || ""} picks</span>
                  <div className="bar"><span className="good" style={{ width: "100%" }} /></div>
                  <span className="note">{fmtMs(result.timings.plan_ms ?? result.timings.total_ms)}</span>
                </div>
                <div className="stage">
                  <span className="dot ok" />
                  <span className="name">Price candidates</span>
                  <div className="bar"><span className="good" style={{ width: "100%" }} /></div>
                  <span className="note">
                    {result.candidates.length} · {fmtMs(result.timings.candidates_ms)}
                  </span>
                </div>
              </div>
              {result.punt_scan.length > 0 && (
                <>
                  <span className="k" style={{ marginTop: 4 }}>
                    Punt strategies <span className="muted" style={{ textTransform: "none", letterSpacing: 0, fontFamily: "var(--body)", fontWeight: 400 }}>click to pin</span>
                  </span>
                  <div className="punts">
                    {result.punt_scan.slice(0, 6).map((row, i) => (
                      <button
                        key={row.punt}
                        className={`pill clickable ${i === 0 ? "hot" : ""}`}
                        onClick={() => pinPunt(row.punt)}
                        onMouseEnter={() => setShowRoster(row.punt)}
                        onMouseLeave={() => setShowRoster(null)}
                        title={row.roster.join(", ")}
                      >
                        {puntLabel(row.punt)} · {i === 0 ? row.objective.toFixed(2) : `−${row.gap_to_best.toFixed(2)}`}
                      </button>
                    ))}
                  </div>
                  {showRoster && (
                    <span className="muted" style={{ fontSize: 11 }}>
                      {result.punt_scan.find((r) => r.punt === showRoster)?.roster.join(", ")}
                    </span>
                  )}
                </>
              )}
            </section>
          </div>

          {result.plan.length > 0 && (
            <section className="panel">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
                <span className="k">Plan for your {result.plan.length} remaining picks</span>
                <span className="muted" style={{ fontSize: 11 }}>
                  re-solved after every pick · chance each is still there
                </span>
              </div>
              <div className="plan">
                {result.plan.map((p, i) => (
                  <div key={p.pick} className={`pick ${i === 0 && session.on_the_clock ? "now" : ""}`} title={p.name}>
                    <div className="n">#{p.pick}</div>
                    <div className="who">{shortName(p.name)}</div>
                    <div className={i === 0 && session.on_the_clock ? "" : p.availability < 0.5 ? "bad" : p.availability < 0.8 ? "accent" : "good"}>
                      {i === 0 && session.on_the_clock ? "now" : pct(p.availability)}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <section className="panel">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
              <span className="k">{result.mode === "horizon" ? "Expected roster if the plan holds" : "Best roster from here"}</span>
              <span className="muted" style={{ fontSize: 11 }}>
                obj {result.best_roster.objective.toFixed(2)} · punting {result.best_roster.punted.map((c) => CAT_LABEL[c]).join(", ") || "nothing"}
              </span>
            </div>
            <ul className="roster" style={{ columns: 2, columnGap: 16 }}>
              {result.best_roster.roster.map((r) => (
                <li key={r.slot} className={session.my_roster.includes(r.player) ? "mine" : ""} style={{ breakInside: "avoid" }}>
                  <span className="slot">{r.slot}</span> {r.name}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </>
  );
}
