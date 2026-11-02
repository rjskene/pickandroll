// The moves and trades track's figures (#285): React SVG, one per step after the weekly odds,
// and the overview's loop and day (#282).
import { M } from "./lane";
import { WIN } from "./dayline";
import { Arrow } from "./svg";

/** The user's execute time on a weekday: the day line's (#286). */
const EXEC = M(9);

/** The season at once (#282): the loop every day goes round (build, rank, queue, act), and one
 * weekday on the VM with the routines' windows from the day line, the execute time marked. */
export function MovesIntro() {
  const t0 = M(4);
  const x = (m: number) => 40 + ((m - t0) * 360) / (M(23) - t0);
  const steps: [string, string][] = [
    ["build", "refresh and solve"],
    ["rank", "two horizons, guard"],
    ["queue", "veto, then execute"],
    ["act", "claims, lineups"],
  ];
  const block = (w: [number, number], cls: string) => <rect className={cls} x={x(w[0])} y="126" width={Math.max(3, x(w[1]) - x(w[0]))} height="16" />;
  return (
    <svg viewBox="0 0 420 218" role="img" aria-label="The day's loop, build to rank to queue to act, and one weekday on the VM: the daily at 05:00, the execute time, the three passes and the evening build">
      <Arrow id="ex-ah-mintro" />
      <Arrow id="ex-ah-mintro-loop" accent />
      <text className="ac sm" x="211" y="10" textAnchor="middle">
        every day, and again at the 21:00 build
      </text>
      <path className="arrow loop" d="M364 26V15H58V23" markerEnd="url(#ex-ah-mintro-loop)" />
      {steps.map(([label, sub], k) => (
        <g key={label}>
          <rect className={`node${k === 1 ? " hot" : ""}`} x={16 + k * 102} y="26" width="84" height="36" rx="7" />
          <text className={`lbl${k === 1 ? " ink" : ""}`} x={58 + k * 102} y="49" textAnchor="middle">
            {label}
          </text>
          <text className="sm" x={58 + k * 102} y="78" textAnchor="middle">
            {sub}
          </text>
          {k < 3 && <path className="arrow" d={`M${100 + k * 102} 44h15`} markerEnd="url(#ex-ah-mintro)" />}
        </g>
      ))}
      <text className="lbl xs" x="16" y="104">
        one weekday on the VM, Central time
      </text>
      <rect className="bar" x={x(t0)} y="126" width={x(M(23)) - x(t0)} height="16" rx="3" />
      {block(WIN.daily, "bar in")}
      {block(WIN.morning, "fill a")}
      {block(WIN.late, "fill a")}
      {block(WIN.build, "bar in")}
      {block(WIN.evening, "fill a")}
      <text className="sm" x={x(WIN.daily[0])} y="119" textAnchor="middle">
        daily
      </text>
      <text className="sm" x={x((WIN.morning[0] + WIN.morning[1]) / 2)} y="119" textAnchor="middle">
        morning pass
      </text>
      <text className="sm" x={x((WIN.late[0] + WIN.late[1]) / 2)} y="119" textAnchor="middle">
        late pass
      </text>
      <text className="sm" x={x(WIN.build[0])} y="119" textAnchor="middle">
        build
      </text>
      <line className="ref ac" x1={x(EXEC)} y1="121" x2={x(EXEC)} y2="147" />
      <line className="ref bad" x1={x(WIN.evening[1])} y1="121" x2={x(WIN.evening[1])} y2="147" />
      <text className="sm" x={x(WIN.daily[0])} y="160" textAnchor="middle">
        05:00
      </text>
      <text className="ac sm" x={x(EXEC)} y="160">
        09:00 execute time
      </text>
      <text className="sm" x={x(WIN.late[0])} y="160">
        15:00 lineups
      </text>
      <text className="sm" x={x(WIN.build[0])} y="160" textAnchor="middle">
        21:00
      </text>
      <text className="sm" x="16" y="174">
        04:50 sign-in
      </text>
      <text className="bad sm" x={x(M(23))} y="174" textAnchor="end">
        22:40 pass, 22:58 stop
      </text>
      <text className="sm" x="16" y="196">
        each league off, dry run or live, by the user's own switch
      </text>
      <text className="ac sm" x="16" y="210">
        the pinned private league (31822): suggestions only, made by hand
      </text>
    </svg>
  );
}

/** This week against the opponent, three weeks against the field, the rest of the season beside. */
export function Horizons() {
  return (
    <svg viewBox="0 0 420 182" role="img" aria-label="This week, three weeks, rest of season">
      <rect className="win a" x="20" y="30" width="90" height="40" rx="6" />
      <text className="lbl" x="65" y="48" textAnchor="middle">
        this week
      </text>
      <text className="sm" x="65" y="63" textAnchor="middle">
        vs my opponent
      </text>
      <rect className="win b" x="118" y="30" width="200" height="40" rx="6" />
      <text className="lbl" x="218" y="48" textAnchor="middle">
        three weeks (2–4)
      </text>
      <text className="sm" x="218" y="63" textAnchor="middle">
        vs the field, mean of per-opponent odds
      </text>
      <rect className="win" x="326" y="30" width="74" height="40" rx="6" />
      <text className="lbl" x="363" y="48" textAnchor="middle">
        rest
      </text>
      <text className="sm" x="363" y="63" textAnchor="middle">
        to the last day
      </text>
      <line className="axis" x1="20" y1="86" x2="400" y2="86" />
      <text className="sm" x="20" y="100">
        today
      </text>
      <text className="sm" x="110" y="100" textAnchor="middle">
        Mon
      </text>
      <text className="sm" x="318" y="100" textAnchor="middle">
        Mon
      </text>
      <text className="sm" x="400" y="100" textAnchor="end">
        season end
      </text>
      <text className="ac" x="20" y="130">
        gain shown on both ranking horizons, whichever chose the move
      </text>
      <text x="20" y="148">rest of season in value units; the season guard holds a set to zero or</text>
      <text x="20" y="160">more on it</text>
    </svg>
  );
}

/** The keep rule as a decision flow. */
export function KeepRule() {
  return (
    <svg viewBox="0 0 420 250" role="img" aria-label="The keep rule as a decision flow: net positive, not beaten by the floor, back this season: protected">
      <Arrow id="ex-ah-keep" />
      <rect className="node" x="20" y="16" width="230" height="38" rx="7" />
      <text className="lbl" x="135" y="40" textAnchor="middle">
        net positive on his season line?
      </text>
      <rect className="node" x="20" y="82" width="230" height="38" rx="7" />
      <text className="lbl" x="135" y="106" textAnchor="middle">
        best add beats him by the floor?
      </text>
      <rect className="node" x="20" y="148" width="230" height="38" rx="7" />
      <text className="lbl" x="135" y="172" textAnchor="middle">
        back this season?
      </text>
      <rect className="win g" x="20" y="212" width="230" height="30" rx="7" />
      <text className="lbl" x="135" y="232" textAnchor="middle">
        protected: never a drop
      </text>
      <rect className="win" x="290" y="82" width="110" height="104" rx="7" />
      <text className="lbl" x="345" y="120" textAnchor="middle">
        droppable
      </text>
      <text className="sm" x="345" y="140" textAnchor="middle">
        or benched if back
      </text>
      <text className="sm" x="345" y="154" textAnchor="middle">
        within seven days
      </text>
      <path className="arrow" d="M135 54v22" markerEnd="url(#ex-ah-keep)" />
      <path className="arrow" d="M135 120v22" markerEnd="url(#ex-ah-keep)" />
      <path className="arrow" d="M135 186v20" markerEnd="url(#ex-ah-keep)" />
      <text className="sm" x="142" y="70">
        yes
      </text>
      <text className="sm" x="142" y="136">
        no
      </text>
      <text className="sm" x="142" y="202">
        yes
      </text>
      <path className="arrow" d="M250 35H330V82" markerEnd="url(#ex-ah-keep)" />
      <text className="sm" x="262" y="30">
        no
      </text>
      <path className="arrow" d="M250 101h32" markerEnd="url(#ex-ah-keep)" />
      <text className="sm" x="256" y="96">
        yes
      </text>
      <path className="arrow" d="M250 167h40" markerEnd="url(#ex-ah-keep)" />
      <text className="sm" x="256" y="162">
        no
      </text>
    </svg>
  );
}

const PUBLIC = ["continuous waivers, 2 days", "every available player is W", "claims land at the overnight run", "cleared free agent: $0, at once", "4 adds a week", "bid queued with its reason", "struck bid: a $0 claim", "an armed league claims it live"];
const PRIVATE = ["free agents, not waivers", "an add plays the same night", "1-day waivers by priority", "no FAAB, so no bid", "odds at an assumed rival rate", "5 adds a week", "suggestions only", "every move is the user's own"];

/** How a bid is sized, the two kinds of league apart, and what a trade score reports. */
export function BidsTrades() {
  const col = (x: number, lines: string[]) => lines.map((l, i) => <text key={l} className="sm" x={x} y={126 + i * 14}>{l}</text>);
  return (
    <svg viewBox="0 0 420 332" role="img" aria-label="How a bid is sized, the public FAAB leagues beside the pinned private league, and the trade score">
      <Arrow id="ex-ah-bid" />
      <rect className="node" x="20" y="20" width="110" height="40" rx="7" />
      <text className="lbl" x="75" y="38" textAnchor="middle">
        gain in typicals
      </text>
      <text className="sm" x="75" y="53" textAnchor="middle">
        rounded, at least 1
      </text>
      <rect className="node" x="155" y="20" width="110" height="40" rx="7" />
      <text className="lbl" x="210" y="38" textAnchor="middle">
        times the flag
      </text>
      <text className="sm" x="210" y="53" textAnchor="middle">
        doubled or tripled
      </text>
      <rect className="node hot" x="290" y="20" width="110" height="40" rx="7" />
      <text className="lbl ink" x="345" y="38" textAnchor="middle">
        bid
      </text>
      <text className="sm ink" x="345" y="53" textAnchor="middle">
        clamped to budget left
      </text>
      <path className="arrow" d="M130 40h22" markerEnd="url(#ex-ah-bid)" />
      <path className="arrow" d="M265 40h22" markerEnd="url(#ex-ah-bid)" />
      <rect className="win b" x="20" y="84" width="185" height="156" rx="7" />
      <text className="lbl" x="32" y="106">
        public leagues: FAAB
      </text>
      {col(32, PUBLIC)}
      <rect className="win a" x="215" y="84" width="185" height="156" rx="7" />
      <text className="lbl" x="227" y="106">
        private league (31822)
      </text>
      {col(227, PRIVATE)}
      <rect className="win" x="20" y="254" width="380" height="52" rx="6" />
      <text className="lbl" x="32" y="272">
        a proposed trade
      </text>
      <text className="sm" x="32" y="287">
        scored on both horizons, the season beside · least costly drop and best fill named
      </text>
      <text className="sm" x="32" y="299">
        the margin that makes it neutral reported · nothing sends or accepts a trade
      </text>
      <text className="sm" x="20" y="326">
        the hill-climb may tune the bid sizing within bounds
      </text>
    </svg>
  );
}
