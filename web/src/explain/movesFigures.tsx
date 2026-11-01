// The moves and trades track's figures (#285): React SVG, one per step after the weekly odds.
import { Arrow } from "./svg";

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
const PRIVATE = ["free agents, not waivers", "an add plays the same night", "1-day waivers by priority", "no FAAB, so no bid", "odds (1 − q)^(p − 1), assumed", "5 adds a week", "suggestions only", "every move is the user's own"];

/** How a bid is sized, the two kinds of league apart, and what a trade score reports. */
export function BidsTrades() {
  const col = (x: number, lines: string[]) => lines.map((l, i) => <text key={l} className="sm" x={x} y={126 + i * 14}>{l}</text>);
  return (
    <svg viewBox="0 0 420 332" role="img" aria-label="How a bid is sized, the public FAAB leagues beside the pinned private league, and the trade score">
      <Arrow id="ex-ah-bid" />
      <rect className="node" x="20" y="20" width="110" height="40" rx="7" />
      <text className="lbl" x="75" y="38" textAnchor="middle">
        gain / typical
      </text>
      <text className="sm" x="75" y="53" textAnchor="middle">
        rounded, at least 1
      </text>
      <rect className="node" x="155" y="20" width="110" height="40" rx="7" />
      <text className="lbl" x="210" y="38" textAnchor="middle">
        × flag
      </text>
      <text className="sm" x="210" y="53" textAnchor="middle">
        breakout ×2, strong ×3
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
