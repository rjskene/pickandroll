import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Objective, type SessionSummary } from "../api";
import Info from "./Info";

interface Props {
  onCreated: (session: SessionSummary) => void;
  onSelect: (id: string) => void;
}

export default function SessionSetup({ onCreated, onSelect }: Props) {
  const queryClient = useQueryClient();
  const projections = useQuery({ queryKey: ["projections"], queryFn: api.projections });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  const survivalFiles = useQuery({ queryKey: ["files", "survival"], queryFn: () => api.files("survival") });
  const curveFiles = useQuery({ queryKey: ["files", "curve"], queryFn: () => api.files("curve") });
  const adpFiles = useQuery({ queryKey: ["files", "adp"], queryFn: () => api.files("adp") });
  const [file, setFile] = useState("");
  const [positionsFile, setPositionsFile] = useState("");
  const [adpFile, setAdpFile] = useState("");
  const [numTeams, setNumTeams] = useState(12);
  const [position, setPosition] = useState(1);
  const [myTeam, setMyTeam] = useState("me");
  const [bench, setBench] = useState(3);
  const [objective, setObjective] = useState<Objective>("win");
  const [sigmaScale, setSigmaScale] = useState(1);
  const [curveFile, setCurveFile] = useState("");
  const [survival, setSurvival] = useState<"none" | "simulate" | "file">("none");
  const [survivalSims, setSurvivalSims] = useState(300);
  const [survivalFile, setSurvivalFile] = useState("");
  const [solveAhead, setSolveAhead] = useState(true);
  const [timeLimit, setTimeLimit] = useState(20);

  const create = useMutation({
    mutationFn: () =>
      api.createSession({
        projection_file: file || projections.data?.[0]?.file || "",
        num_teams: numTeams,
        my_position: position,
        my_team: myTeam,
        bench,
        positions_file: positionsFile || null,
        adp_file: adpFile || null,
        objective,
        sigma_scale: sigmaScale,
        curve_file: curveFile || null,
        survival,
        survival_sims: survivalSims,
        survival_file: survival === "file" ? survivalFile || survivalFiles.data?.[0]?.file || null : null,
        solve_ahead: solveAhead,
        time_limit: timeLimit,
      }),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      onCreated(session);
    },
  });
  const files = projections.data ?? [];
  const hasDefaultAdp = (adpFiles.data ?? []).some((f) => f.file === "adp.csv");
  const perDraft = 1.2;
  const workers = 8;
  const simMinutes = (survivalSims * perDraft) / workers / 60;

  return (
    <section className="panel setup">
      <h2>NEW DRAFT</h2>
      <label>
        <span className="k">Projections</span>
        <select value={file || files[0]?.file || ""} onChange={(e) => setFile(e.target.value)}>
          {files.map((p) => (
            <option key={p.file} value={p.file}>
              {p.file}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span className="k">Positions from <span className="muted">(optional)</span></span>
        <select value={positionsFile} onChange={(e) => setPositionsFile(e.target.value)}>
          <option value="">none, use data/positions.csv if present</option>
          {files.map((p) => (
            <option key={p.file} value={p.file}>
              {p.file}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span className="k">ADP from <span className="muted">(optional, Yahoo replaces it)</span></span>
        <select value={adpFile} onChange={(e) => setAdpFile(e.target.value)}>
          <option value="">{hasDefaultAdp ? "data/adp.csv" : "none: rank by projected value"}</option>
          {(adpFiles.data ?? [])
            .filter((f) => f.file !== "adp.csv")
            .map((f) => (
              <option key={f.file} value={f.file}>
                {f.file}
              </option>
            ))}
          {files.map((p) => (
            <option key={p.file} value={p.file}>
              {p.file}
            </option>
          ))}
        </select>
      </label>
      {!adpFile && !hasDefaultAdp && (
        <p className="warn">
          No ADP file in data/. The board's ADP will be Basketball Monster's value rank, which puts specialists far later than real drafts do.
          Save one as data/adp.csv with columns player,adp (a FantasyPros export works too).
        </p>
      )}
      <div className="row">
        <label>
          <span className="k">Teams</span>
          <input type="number" min={2} max={20} value={numTeams} onChange={(e) => setNumTeams(+e.target.value)} />
        </label>
        <label>
          <span className="k">My pick</span>
          <input type="number" min={1} max={numTeams} value={position} onChange={(e) => setPosition(+e.target.value)} />
        </label>
        <label>
          <span className="k">Bench</span>
          <input type="number" min={0} max={6} value={bench} onChange={(e) => setBench(+e.target.value)} />
        </label>
        <label style={{ flexGrow: 1 }}>
          <span className="k">My team name</span>
          <input value={myTeam} onChange={(e) => setMyTeam(e.target.value)} />
        </label>
      </div>

      <span className="k">Strategy</span>
      <div className="row">
        <label style={{ flexGrow: 1 }}>
          <span className="k">Objective</span>
          <select value={objective} onChange={(e) => setObjective(e.target.value as Objective)}>
            <option value="win">expected categories won (recommended)</option>
            <option value="sum">sum of z (the old planner, no punts)</option>
          </select>
        </label>
        {objective === "win" && (
          <label>
            <span className="k">
              Spread ×
              <Info title="spread multiplier" align="right">
                <b>Multiplies each category's spread (σ) in the win curve.</b>
                <span>1 = the league as simulated, no adjustment. Above 1 flattens the curve: win odds move less per z, a hedge for noisy weeks. Below 1 steepens it.</span>
                <span>Sane range 0.75 to 2. In the study ×2 cost 0.2 matchups of 11 and ×0.5 cost 0.65.</span>
              </Info>
            </span>
            <input type="number" min={0.25} max={5} step={0.25} value={sigmaScale} onChange={(e) => setSigmaScale(+e.target.value)} />
          </label>
        )}
      </div>
      {objective === "win" && (
        <label>
          <span className="k">
            League curve <span className="muted">(μ and σ per category)</span>
            <Info title="league curve">
              <b>Per category: where the league's final totals land (μ) and how spread out they are (σ), in z.</b>
              <span>A category counts for Φ((total − μ) / σ), the chance of beating a team drawn from the league. Expected categories won adds those up.</span>
              <span>Sources: the built-in fit from 3000 simulated drafts; a refit from this session's own league simulation (choose "simulate this league" below); or a JSON file in data/. Spread × is applied on top.</span>
            </Info>
          </span>
          <select value={curveFile} onChange={(e) => setCurveFile(e.target.value)}>
            <option value="">simulated league (3000 drafts, BBM 2026-09-21){survival === "simulate" ? ", refitted from the simulation below" : ""}</option>
            {(curveFiles.data ?? []).map((f) => (
              <option key={f.file} value={f.file}>
                {f.file}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        <span className="k">
          Survival odds
          <Info title="survival odds">
            <b>The chance a player is still on the board at each of your picks.</b>
            <span>The plan weights every future pick by them, so they decide who to take now and who can wait.</span>
            <span><b>ADP formula (instant):</b> a normal spread around each player's ADP. With no ADP file the ADP is a value rank, which puts specialists far later than real drafts do.</span>
            <span><b>Simulate this league:</b> runs full drafts with z-score, ADP and roster-model drafters (some punting) and counts how often each player survives to each pick. Catches specialists going early and position runs. About 1 s per draft per core. The curve's μ and σ are refitted from the same drafts.</span>
            <span><b>Saved table:</b> a CSV from an earlier simulation in data/.</span>
          </Info>
        </span>
        <select value={survival} onChange={(e) => setSurvival(e.target.value as "none" | "simulate" | "file")}>
          <option value="none">ADP formula (instant)</option>
          <option value="simulate">simulate this league before the draft (recommended)</option>
          <option value="file" disabled={!survivalFiles.data?.length}>saved survival table in data/</option>
        </select>
      </label>
      {survival === "simulate" && (
        <div className="row">
          <label>
            <span className="k">Drafts</span>
            <input type="number" min={10} max={5000} step={50} value={survivalSims} onChange={(e) => setSurvivalSims(+e.target.value)} />
          </label>
          <span className="muted" style={{ alignSelf: "end", paddingBottom: 6 }}>
            about {simMinutes < 1 ? `${Math.max(10, Math.round(simMinutes * 60))} s` : `${simMinutes.toFixed(0)} min`} on {workers} cores; the draft screen opens at once and the table lands in the background.
            {objective === "win" ? " The curve's μ and σ are refitted from the same run." : ""}
          </span>
        </div>
      )}
      {survival === "file" && (
        <label>
          <span className="k">Survival table</span>
          <select value={survivalFile || survivalFiles.data?.[0]?.file || ""} onChange={(e) => setSurvivalFile(e.target.value)}>
            {(survivalFiles.data ?? []).map((f) => (
              <option key={f.file} value={f.file}>
                {f.file}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="row">
        <label className="inline" style={{ alignSelf: "end" }}>
          <input type="checkbox" checked={solveAhead} onChange={(e) => setSolveAhead(e.target.checked)} /> solve ahead of the clock (re-plan after every pick)
        </label>
        <label title="seconds per plan solve; the incumbent is kept when the limit is hit">
          <span className="k">Time limit (s)</span>
          <input type="number" min={1} max={600} value={timeLimit} onChange={(e) => setTimeLimit(+e.target.value)} />
        </label>
      </div>

      <button className="primary" onClick={() => create.mutate()} disabled={create.isPending || !files.length}>
        {create.isPending ? "Loading projections…" : "Start draft"}
      </button>
      {create.error && <p className="error">{String(create.error.message)}</p>}
      {files.length === 0 && <p className="muted">Drop a Basketball Monster export into data/.</p>}
      {(sessions.data?.length ?? 0) > 0 && (
        <>
          <span className="k">Open drafts</span>
          <ul className="sessions">
            {sessions.data!.map((s) => (
              <li key={s.id}>
                <button className="link" onClick={() => onSelect(s.id)}>
                  {s.id}
                </button>{" "}
                <span className="muted">
                  {s.num_teams} teams, pick {s.my_position}, {s.picks_made}/{s.num_teams * s.roster_size} made · {s.objective === "win" ? "categories won" : "sum of z"}
                  {s.survival.status === "building" ? " · simulating league" : s.availability_source === "survival" ? " · simulated odds" : ""}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
