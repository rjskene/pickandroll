import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type ScorecardMove, type ScorecardPayload } from "../api";
import {
  dayLabel,
  MATCH_WORDS,
  movesSummaryLine,
  moveWhat,
  realizedLabel,
  realizedTitle,
  scorecardToDateLine,
  scorecardWeekLine,
  unitsLabel,
  weekDates,
} from "../season";

/** The Scorecard card (#126): a recorded week against the decision log's projection of it, the
 * season to date, and the week's moves with their projected and realized values in the scorer's
 * units. The last recorded week by default; the arrows step through the others. */
export default function Scorecard({ league }: { league: string }) {
  const q = useQuery({ queryKey: ["scorecard", league], queryFn: () => api.scorecard(league), refetchInterval: 300_000 });
  const [shown, setShown] = useState<number | null>(null);
  const d = q.data;
  if (q.error) return <p className="error small">{q.error.message}</p>;
  if (!d) return <p className="dim small">Reading the scorecard…</p>;
  if (d.status === "no_team") return <p className="dim small">My team is not known in this league.</p>;
  if (!d.weeks.length) return <p className="dim small">No week recorded yet: each week is scored the Monday after it ends.</p>;
  const i = shown == null ? d.weeks.length - 1 : Math.min(shown, d.weeks.length - 1);
  const w = d.weeks[i];
  const name = (id: number) => d.players?.[String(id)] ?? `player ${id}`;
  return (
    <>
      <div className="block">
        <div className="row">
          <span className="k">
            Week {w.week} · {weekDates(w)}
          </span>
          {d.weeks.length > 1 && (
            <span>
              <button className="small" disabled={i === 0} onClick={() => setShown(i - 1)} title="the week before" aria-label="the week before">
                ‹
              </button>{" "}
              <button className="small" disabled={i === d.weeks.length - 1} onClick={() => setShown(i + 1)} title="the week after" aria-label="the week after">
                ›
              </button>
            </span>
          )}
        </div>
        <p className="small" title={w.projected ? `the solve of ${dayLabel(w.projected.at.slice(0, 10))}, the last before the week's first game` : "no solve logged saw the whole week"}>
          {scorecardWeekLine(w)}
        </p>
        <Moves moves={w.moves} scoring={w.scoring} name={name} />
      </div>
      {d.to_date && (
        <div className="block">
          <span className="k">Season to date</span>
          <p className="small">{scorecardToDateLine(d.to_date, d.calibration?.brier)}</p>
          <p className="small muted" title="scored: projected by its own solve and realized; realized only: no projection of its own, or valued with the nearest solve's scorer">
            {movesSummaryLine(d.to_date.moves, w.scoring)}
          </p>
        </div>
      )}
    </>
  );
}

function Moves({ moves, scoring, name }: { moves: ScorecardMove[]; scoring: ScorecardPayload["weeks"][number]["scoring"]; name: (id: number) => string }) {
  if (!moves.length) return <p className="dim small">No move made this week.</p>;
  const units = scoring === "points" ? "fantasy points" : "the scorer's z-sum, net of an empty line";
  return (
    <table className="season-table">
      <thead>
        <tr>
          <th title="the move, its day, and how it compares with the solve logged before it">Move</th>
          <th className="num" title={`its projected value over its week, as its solve logged it, in ${units}`}>
            Proj
          </th>
          <th className="num" title={`its realized value over its week, from the box scores of the games the two played, in ${units}`}>
            Real
          </th>
          <th className="num" title="its realized value over the three weeks after its week, as far as they are read">
            +3wk
          </th>
        </tr>
      </thead>
      <tbody>
        {moves.map((m, k) => {
          const proj = m.projected?.value.horizons.week?.value;
          const tone = m.group === "scored" ? undefined : "dim";
          return (
            <tr key={k} title={realizedTitle(m, scoring)}>
              <td>
                {moveWhat(m, name)}
                <div className="dim small" title={m.match.near ? "within an hour of a solve: a time zone off by an hour could change the match" : undefined}>
                  {[dayLabel(m.day), MATCH_WORDS[m.match.kind], m.judged === "three" ? "judged on the three weeks" : null].filter(Boolean).join(" · ")}
                  {m.match.near ? " *" : ""}
                </div>
              </td>
              <td className="num">{proj != null ? unitsLabel(proj, scoring) : ""}</td>
              <td className={["num", tone].filter(Boolean).join(" ")}>{realizedLabel(m, "week", scoring)}</td>
              <td className={["num", tone].filter(Boolean).join(" ")}>{realizedLabel(m, "three", scoring)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
