import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { blendLabel } from "../format";

/** The draft sessions on this server, each a link into its draft view. */
export default function OpenSessions({ onSelect }: { onSelect: (id: string) => void }) {
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: api.sessions });
  if (!sessions.data?.length) return <p className="muted">No draft session on this server.</p>;
  return (
    <ul className="sessions">
      {sessions.data.map((s) => (
        <li key={s.id}>
          <button className="link" onClick={() => onSelect(s.id)}>
            {s.id}
          </button>{" "}
          <span className="muted">
            {s.league ? `league ${s.league}, ` : ""}
            {s.num_teams} teams, pick {s.my_position}, {s.picks_made}/{s.num_teams * s.roster_size} made · {s.objective === "win" ? "categories won" : "sum of z"}
            {s.survival.status === "building" ? " · simulating league" : s.availability_source === "survival" ? " · simulated odds" : s.availability_source === "league" ? ` · league odds${s.survival.blend ? ` (${blendLabel(s.survival.blend.drafts)})` : ""}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
