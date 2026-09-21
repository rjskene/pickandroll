import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type SessionSummary } from "../api";

interface Props {
  onCreated: (session: SessionSummary) => void;
  onSelect: (id: string) => void;
}

export default function SessionSetup({ onCreated, onSelect }: Props) {
  const queryClient = useQueryClient();
  const projections = useQuery({ queryKey: ["projections"], queryFn: api.projections });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  const [file, setFile] = useState("");
  const [positionsFile, setPositionsFile] = useState("");
  const [adpFile, setAdpFile] = useState("");
  const [numTeams, setNumTeams] = useState(12);
  const [position, setPosition] = useState(1);
  const [myTeam, setMyTeam] = useState("me");
  const [bench, setBench] = useState(3);

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
      }),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      onCreated(session);
    },
  });
  const files = projections.data ?? [];

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
          <option value="">none, use data/adp.csv or rank by z</option>
          {files.map((p) => (
            <option key={p.file} value={p.file}>
              {p.file}
            </option>
          ))}
        </select>
      </label>
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
                  {s.num_teams} teams, pick {s.my_position}, {s.picks_made}/{s.num_teams * s.roster_size} made
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
