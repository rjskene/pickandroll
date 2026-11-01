// The figures (#283): React SVG, one per name in the data; the day line is the shared clock.
import { useMemo, useState } from "react";
import type { ReactElement } from "react";
import AnimFrame from "./AnimFrame";
import { DAY_END, DAY_SECONDS, dayLanes, dayNow, dayTicks } from "./dayline";
import type { Day } from "./dayline";
import type { FigureId } from "./types";

function Arrow({ id }: { id: string }) {
  return (
    <defs>
      <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
        <path d="M0 0L10 5L0 10z" className="ex-arrowhead" />
      </marker>
    </defs>
  );
}

/** An export row parsed into fields (the draft's first step). */
function ExportRow() {
  return (
    <svg viewBox="0 0 420 192" role="img" aria-label="An export row parsed into fields">
      <Arrow id="ex-ah-export" />
      <rect className="win b" x="20" y="18" width="380" height="30" rx="6" />
      <text className="lbl" x="32" y="38">
        one export row, one player
      </text>
      <path className="arrow" d="M210 48v18" markerEnd="url(#ex-ah-export)" />
      <rect className="node" x="20" y="72" width="88" height="34" rx="6" />
      <text className="t" x="64" y="93" textAnchor="middle">
        games · min
      </text>
      <rect className="node" x="117" y="72" width="140" height="34" rx="6" />
      <text className="t" x="187" y="93" textAnchor="middle">
        pts 3s reb ast stl blk tov
      </text>
      <rect className="node" x="266" y="72" width="134" height="34" rx="6" />
      <text className="t" x="333" y="93" textAnchor="middle">
        fgm fga · ftm fta
      </text>
      <text className="sm" x="20" y="130">
        totals over the horizon, never per game; a 20-game horizon is a smaller export,
      </text>
      <text className="sm" x="20" y="142">
        not a rescaled one
      </text>
      <text className="sm" x="20" y="158">
        matched to Yahoo ids by normalized name, an alias table for the mismatches
      </text>
      <text className="ac sm" x="20" y="182">
        the model never sees a rank or a dollar value; only the stat line
      </text>
    </svg>
  );
}

/** Two distributions of a weekly total (the moves track's first step). */
function WeeklyOdds() {
  return (
    <svg viewBox="0 0 420 200" role="img" aria-label="Two distributions of a weekly total, mine and theirs, and the odds of the lead">
      <Arrow id="ex-ah-odds" />
      <path className="fill b" d="M50 170C110 170 125 50 170 50S230 170 290 170Z" />
      <path className="line b" d="M50 170C110 170 125 50 170 50S230 170 290 170" />
      <path className="fill a" d="M130 170C190 170 205 50 250 50S310 170 370 170Z" />
      <path className="line a" d="M130 170C190 170 205 50 250 50S310 170 370 170" />
      <line className="ref" x1="170" y1="50" x2="170" y2="170" />
      <line className="ref" x1="250" y1="50" x2="250" y2="170" />
      <path className="arrow" d="M174 36H246" markerEnd="url(#ex-ah-odds)" />
      <text className="t" x="210" y="30" textAnchor="middle">
        Δ
      </text>
      <text className="sm them" x="170" y="186" textAnchor="middle">
        their total
      </text>
      <text className="ac sm" x="250" y="186" textAnchor="middle">
        my total
      </text>
      <text className="t" x="400" y="60" textAnchor="end">
        P(win) = Φ(Δ / √(σ₁² + σ₂²))
      </text>
      <text className="sm" x="400" y="78" textAnchor="end">
        σ from per-game spread × games
      </text>
      <line className="axis" x1="30" y1="170" x2="400" y2="170" />
    </svg>
  );
}

const DAYS: { id: Day; label: string }[] = [
  { id: "week", label: "weekday" },
  { id: "sun", label: "Sunday" },
  { id: "mon", label: "Monday" },
];

/** The shared day line: the day's actions under one sweeping clock. */
function DayLine() {
  const [day, setDay] = useState<Day>("week");
  const [room, setRoom] = useState(false);
  const lanes = useMemo(() => dayLanes(day, room), [day, room]);
  return (
    <AnimFrame
      id="ex-dl"
      min={0}
      max={DAY_END}
      step={5}
      speed={DAY_END / DAY_SECONDS}
      lanes={lanes}
      ticks={dayTicks}
      now={(t) => dayNow(t, day)}
      hint={`play runs the day in ${DAY_SECONDS} s; drag the slider, or step from event to event`}
      rangeLabel="time of day, in minutes"
      label="The day's actions on one 24-hour line, each lit while it may run and hatched while it may not, under a sweeping clock"
      caption="One lane per action, Central time. The windows, the execute time and the veto rule, the tip-off lock, the hard stop and the Sunday turn are the routines' and the docs'; the run lengths, the 05:40 entry and the 18:00 tip-off are an example day. The last lane is the sessions' working agreement, not a gate in the code: no pull, checkout, source edit or API restart while a routine window is open or a draft room is on the server. Reduced motion shows the final frame."
    >
      <span className="seg small" role="group" aria-label="which day">
        {DAYS.map((d) => (
          <button key={d.id} className={day === d.id ? "on" : ""} aria-pressed={day === d.id} onClick={() => setDay(d.id)}>
            {d.label}
          </button>
        ))}
      </span>
      <label className="ex-chk">
        <input type="checkbox" checked={room} onChange={(e) => setRoom(e.target.checked)} /> a draft room is on the server
      </label>
    </AnimFrame>
  );
}

export const FIGURES: Record<FigureId, () => ReactElement> = {
  "export-row": ExportRow,
  "weekly-odds": WeeklyOdds,
  "day-line": DayLine,
};
