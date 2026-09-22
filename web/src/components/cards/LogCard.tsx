import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import { useDraft } from "../../draft";

export default function LogCard() {
  const d = useDraft();
  const s = d.session;
  const picks = useQuery({ queryKey: ["picks", s.id], queryFn: () => api.picks(s.id) });
  const rows = [...(picks.data ?? [])].reverse();
  return (
    <>
      <div className="row">
        <span className="k">
          {rows.length} of {s.num_teams * s.roster_size} picks
        </span>
        <span className="grow" />
        <button className="small" onClick={d.undo} disabled={!rows.length} title="Undo the last pick (z)">
          Undo last <kbd>z</kbd>
        </button>
      </div>
      {rows.length === 0 && <p className="muted" style={{ margin: 0 }}>No picks yet.</p>}
      <ol className="picklog" reversed>
        {rows.map((p) => (
          <li key={p.overall} className={p.team === s.my_team ? "mine" : ""}>
            <span className="slot">
              {p.round}.{String(p.position).padStart(2, "0")}
            </span>
            <span>{p.name}</span>
            <span className="muted" style={{ marginLeft: "auto" }}>{p.team}</span>
          </li>
        ))}
      </ol>
    </>
  );
}
