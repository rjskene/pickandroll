import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import { useDraft } from "../../draft";
import { GapMark, SessionKeepers } from "../Keepers";

export default function LogCard() {
  const d = useDraft();
  const s = d.session;
  const picks = useQuery({ queryKey: ["picks", s.id], queryFn: () => api.picks(s.id) });
  const rows = [...(picks.data ?? [])].reverse();
  // A keeper's pick is never the undo target: it would be logged again at once.
  const realPicks = rows.filter((p) => !p.keeper).length;
  const gaps = new Map(d.gaps.map((g) => [g.overall, g]));
  return (
    <>
      <SessionKeepers />
      <div className="row">
        <span className="k">
          {rows.length} of {s.num_teams * s.roster_size} picks
        </span>
        <span className="grow" />
        <button className="small" onClick={d.undo} disabled={!realPicks} title="Undo the last pick (z); keeper picks behind it come off with it">
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
            {p.keeper && (
              <span className="kmark" title="keeper">
                K
              </span>
            )}
            {gaps.has(p.overall) && <GapMark gap={gaps.get(p.overall)!} />}
            <span>{p.name}</span>
            <span className="muted" style={{ marginLeft: "auto" }}>{p.team}</span>
          </li>
        ))}
      </ol>
    </>
  );
}
