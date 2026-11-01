// The draft track's figures (#284): React SVG, one per step after the export row; the last
// is the extension's three hops with one armed turn on the 30 s pick clock.
import { useMemo, useState } from "react";
import AnimFrame from "./AnimFrame";
import { RC_END, rcLanes, rcLeft, rcTicks } from "./roomclock";
import type { Act, Board, Row } from "./roomclock";
import { Arrow } from "./svg";

/** The pool's sorted bars: z totals, the top teams × roster kept, the rest rescored out. */
export function PoolBars() {
  const bars = Array.from({ length: 44 }, (_, i) => ({ x: 24 + i * 8.4, h: 120 * Math.exp(-i / 16) + 6, inPool: i < 25 }));
  return (
    <svg viewBox="0 0 420 200" role="img" aria-label="The pool is the top teams × roster by z total, chosen iteratively">
      <Arrow id="ex-ah-pool" accent />
      {bars.map((b, i) => (
        <rect key={i} className={`bar${b.inPool ? " in" : ""}`} x={b.x} y={150 - b.h} width="6" height={b.h} rx="1" />
      ))}
      <line className="axis" x1="20" y1="150" x2="400" y2="150" />
      <line className="ref" x1="232" y1="20" x2="232" y2="150" style={{ stroke: "var(--accent)" }} />
      <text className="ac sm" x="236" y="30">
        cut at teams × roster = 156
      </text>
      <text className="sm" x="250" y="166">
        players sorted by z total
      </text>
      <path className="arrow loop" d="M380 160C380 185 60 185 60 160" markerEnd="url(#ex-ah-pool)" />
      <text className="sm" x="220" y="196" textAnchor="middle">
        recompute mean and spread, score again, repeat until the pool settles
      </text>
    </svg>
  );
}

/** Survival curves for three players, read conditionally from the current pick. */
export function Survival() {
  return (
    <svg viewBox="0 0 420 262" role="img" aria-label="Survival curves for three players, read from the current pick">
      <line className="grid" x1="40" y1="65" x2="400" y2="65" />
      <line className="grid" x1="40" y1="110" x2="400" y2="110" />
      <line className="grid" x1="40" y1="155" x2="400" y2="155" />
      <line className="axis" x1="40" y1="20" x2="40" y2="200" />
      <line className="axis" x1="40" y1="200" x2="400" y2="200" />
      <text x="36" y="24" textAnchor="end">
        1
      </text>
      <text x="36" y="114" textAnchor="end">
        .5
      </text>
      <text x="36" y="204" textAnchor="end">
        0
      </text>
      <text x="40" y="218">pick 1</text>
      <text x="177" y="218" textAnchor="middle">
        60
      </text>
      <text x="293" y="218" textAnchor="middle">
        110
      </text>
      <text x="400" y="218" textAnchor="end">
        156
      </text>
      <line className="ref" x1="130" y1="20" x2="130" y2="200" />
      <text className="ac sm" x="134" y="32">
        now: pick 40
      </text>
      <line className="ref" x1="200" y1="105" x2="400" y2="105" />
      <text className="sm" x="398" y="99" textAnchor="end">
        never drafted
      </text>
      <path className="line a" d="M40 20L48 20C60 20 66 198 86 200L400 200" />
      <path className="line b" d="M40 20L120 21C150 22 160 195 240 199L400 200" />
      <path className="line c" d="M40 20L190 22C250 30 290 100 400 105" />
      <text className="sm" x="68" y="46">
        ADP 10: gone
      </text>
      <text className="sm them" x="186" y="112">
        ADP 60: a coin flip by my next pick
      </text>
      <text className="sm" x="255" y="70" style={{ fill: "var(--good)" }}>
        ADP 110
      </text>
      <text className="sm" x="40" y="240">
        read from "now": S(k) / S(now); the league's own table carries the
      </text>
      <text className="sm" x="40" y="252">
        never-drafted share the normal model lacks
      </text>
    </svg>
  );
}

const CATS: [string, number][] = [
  ["FG%", 0.82],
  ["FT%", 0.31],
  ["3PM", 0.66],
  ["PTS", 0.74],
  ["REB", 0.55],
  ["AST", 0.88],
  ["STL", 0.61],
  ["BLK", 0.12],
  ["TO", 0.52],
];

/** The S-curve of a category's win odds beside its piecewise version, and the nine odds
 * summed into the objective. */
export function Objective() {
  const sum = CATS.reduce((s, c) => s + c[1], 0);
  return (
    <svg viewBox="0 0 420 352" role="img" aria-label="The S-curve of a category's win odds, its piecewise version, and nine categories' odds summed">
      <rect className="band r" x="40" y="20" width="118" height="180" />
      <rect className="band g" x="282" y="20" width="118" height="180" />
      <text className="sm" x="44" y="34">
        conceded (&lt; 15%)
      </text>
      <text className="sm" x="396" y="34" textAnchor="end">
        secured (&gt; 85%)
      </text>
      <line className="axis" x1="40" y1="20" x2="40" y2="200" />
      <line className="axis" x1="40" y1="200" x2="400" y2="200" />
      <line className="grid" x1="40" y1="110" x2="400" y2="110" />
      <text x="36" y="24" textAnchor="end">
        1
      </text>
      <text x="36" y="114" textAnchor="end">
        .5
      </text>
      <text x="36" y="204" textAnchor="end">
        0
      </text>
      {[-2.5, -1.5, -0.5, 0.5, 1.5, 2.5].map((v, i) => (
        <text key={v} x={70 + i * 60} y="218" textAnchor="middle">
          {v > 0 ? "+" : "−"}
          {Math.abs(v).toString().replace(/^0/, "")}σ
        </text>
      ))}
      <path className="line a" d="M40 199C110 199 150 185 190 144C210 122 230 98 250 76C270 54 300 32 370 21L400 20" />
      <path className="line pw" d="M40 200L70 199L130 188L190 144L250 76L310 32L370 21L400 20" />
      <line className="ref" x1="180" y1="150" x2="260" y2="70" style={{ stroke: "var(--accent)" }} />
      <circle className="dot" cx="220" cy="110" r="4" />
      <text className="ac sm" x="226" y="128">
        slope = marginal value
      </text>
      <text className="sm" x="40" y="238">
        x = (T − μ) / σ, the roster's lead in spreads; the dashed line is the
      </text>
      <text className="sm" x="40" y="250">
        piecewise version the solver sees
      </text>
      <text className="t" x="40" y="276">
        max Σ Φ((T − μ) / σ) over the categories: the odds of each, summed
      </text>
      {CATS.map(([c, p], i) => {
        const x = 40 + i * 40;
        const h = 28 * p;
        return (
          <g key={c}>
            <rect className={`bar${p > 0.5 ? " in" : ""}`} x={x + 6} y={318 - h} width="28" height={h} rx="2" />
            <text className="sm" x={x + 20} y={314 - h} textAnchor="middle">
              {p.toFixed(2).replace(/^0/, "")}
            </text>
            <text className="sm" x={x + 20} y="330" textAnchor="middle">
              {c}
            </text>
          </g>
        );
      })}
      <line className="axis" x1="40" y1="318" x2="400" y2="318" />
      <text className="ac" x="400" y="348" textAnchor="end">
        Σ = {sum.toFixed(2)} expected categories won
      </text>
    </svg>
  );
}

const SLOTS: [string, number, number][] = [
  ["j = 1", 1, 1],
  ["j = 2", 0.81, 0.92],
  ["j = 3", 0.62, 0.8],
  ["j = 4", 0.47, 0.66],
];

/** A plan: one player per remaining pick, each weighted by his chance of lasting to it. */
export function Plan() {
  return (
    <svg viewBox="0 0 420 162" role="img" aria-label="A plan: one player per remaining pick, weighted by survival; only the first is acted on">
      <text className="lbl" x="20" y="20">
        my remaining picks
      </text>
      {SLOTS.map(([l, a, o], i) => (
        <g key={l}>
          <rect className={i === 0 ? "win a" : "win"} x={20 + i * 68} y="32" width="56" height="60" rx="6" style={i === 0 ? undefined : { opacity: o }} />
          <text className="lbl" x={48 + i * 68} y="56" textAnchor="middle">
            {l}
          </text>
          <text className="t" x={48 + i * 68} y="76" textAnchor="middle">
            A = {a === 1 ? "1.00" : a.toFixed(2).replace(/^0/, "")}
          </text>
        </g>
      ))}
      <rect className="win" x="292" y="32" width="56" height="60" rx="6" style={{ opacity: 0.5 }} />
      <text className="lbl" x="320" y="56" textAnchor="middle">
        …
      </text>
      <rect className="win" x="360" y="32" width="40" height="60" rx="6" style={{ opacity: 0.4 }} />
      <text className="lbl" x="380" y="56" textAnchor="middle">
        13
      </text>
      <text className="sm" x="20" y="114">
        value = z × A[player, pick] · every slot filled once · every player at most once
      </text>
      <text className="ac sm" x="20" y="148">
        only j = 1 is acted on; after the next real pick the whole plan is solved again
      </text>
    </svg>
  );
}

const CANDS: [string, number, string, boolean][] = [
  ["A", 300, "5.21 · best", true],
  ["C", 296, "5.19 · price 0.02 → a tie", true],
  ["B", 270, "5.04 · price 0.17", false],
  ["D", 210, "4.63 · price 0.58", false],
];

/** The price of taking each candidate now, and the tie band. */
export function Price() {
  return (
    <svg viewBox="0 0 420 170" role="img" aria-label="The objective if each candidate is the next pick: the best, its ties, the priced rest">
      <text className="lbl" x="20" y="20">
        objective if he is my next pick
      </text>
      {CANDS.map(([n, w, l, tie], i) => (
        <g key={n}>
          <rect className={`bar${tie ? " in" : ""}`} x="90" y={34 + i * 24} width={w} height="18" rx="3" />
          <text className="t" x="84" y={47 + i * 24} textAnchor="end">
            {n}
          </text>
          <text className={tie ? "lbl ink" : "t"} x="98" y={48 + i * 24} style={{ fontSize: 12 }}>
            {l}
          </text>
        </g>
      ))}
      <line className="ref" x1="383" y1="30" x2="383" y2="128" style={{ stroke: "var(--accent)" }} />
      <text className="ac sm" x="380" y="140" textAnchor="end">
        tie band: 0.05 categories
      </text>
      <text className="sm" x="20" y="162">
        shown in ADP order within the band; the user picks, the model recommends
      </text>
    </svg>
  );
}

/** The background solver's round, and the loop back when the board moves. */
export function SolveAhead() {
  const node = (x: number, y: number, label: string, hot = false) => (
    <g>
      <rect className={`node${hot ? " hot" : ""}`} x={x} y={y} width="110" height="36" rx="7" />
      <text className={`lbl${hot ? " ink" : ""}`} x={x + 55} y={y + 23} textAnchor="middle">
        {label}
      </text>
    </g>
  );
  return (
    <svg viewBox="0 0 420 214" role="img" aria-label="The background solver's round: snapshot, plan, price, scenarios, publish; back to the top when the board moves">
      <Arrow id="ex-ah-solve" />
      <Arrow id="ex-ah-solve-loop" accent />
      {node(20, 20, "1 snapshot")}
      {node(155, 20, "2 plan")}
      {node(290, 20, "3 price")}
      {node(290, 92, "4 scenarios")}
      {node(155, 92, "5 publish", true)}
      {node(20, 92, "board moved?")}
      <path className="arrow" d="M130 38h22" markerEnd="url(#ex-ah-solve)" />
      <path className="arrow" d="M265 38h22" markerEnd="url(#ex-ah-solve)" />
      <path className="arrow" d="M345 56v33" markerEnd="url(#ex-ah-solve)" />
      <path className="arrow" d="M290 110h-22" markerEnd="url(#ex-ah-solve)" />
      <path className="arrow" d="M155 110h-22" markerEnd="url(#ex-ah-solve)" />
      <path className="arrow loop" d="M75 92V58" markerEnd="url(#ex-ah-solve-loop)" />
      <text className="sm" x="20" y="150">
        a full round on a 234-player export: about 20 s · changes mid-solve coalesce
      </text>
      <text className="sm" x="20" y="162">
        into one more
      </text>
      <text className="ac sm" x="20" y="182">
        a room's solves: three candidates, no scenarios, 5 s, inside Yahoo's 30 s pick
      </text>
      <text className="ac sm" x="20" y="194">
        clock
      </text>
    </svg>
  );
}

const TEAMS = 12;
const ROUNDS = 13;
const MINE = 4;
const KEEPER_ROUNDS = [7, 13];

/** Keeper slots in a snake draft: my column, the keeper rounds lit, no names. */
export function KeeperSnake() {
  const cw = 28;
  const ch = 11;
  const x0 = 44;
  const y0 = 24;
  const cells = [];
  for (let r = 0; r < ROUNDS; r++)
    for (let t = 0; t < TEAMS; t++) {
      const mine = t + 1 === MINE;
      const keeper = mine && KEEPER_ROUNDS.includes(r + 1);
      cells.push(<rect key={`${r}-${t}`} className={`cell${keeper ? " keeper" : mine ? " mine" : ""}`} x={x0 + t * cw} y={y0 + r * ch} width={cw - 2} height={ch - 2} rx="2" />);
    }
  return (
    <svg viewBox="0 0 420 212" role="img" aria-label="Keeper slots in a 12-team, 13-round snake: rounds 7 and 13 from position 4 are overall 76 and 148">
      {cells}
      {Array.from({ length: ROUNDS }, (_, r) => (
        <g key={r}>
          <text className="sm" x={x0 - 6} y={y0 + r * ch + 8} textAnchor="end">
            R{r + 1}
          </text>
          <text className="sm" x={x0 + TEAMS * cw + 4} y={y0 + r * ch + 8}>
            {r % 2 === 0 ? "→" : "←"}
          </text>
        </g>
      ))}
      {Array.from({ length: TEAMS }, (_, t) => (
        <text key={t} className={`sm${t + 1 === MINE ? " ac" : ""}`} x={x0 + t * cw + cw / 2 - 1} y={y0 - 6} textAnchor="middle">
          {t + 1}
        </text>
      ))}
      <text className="sm" x="20" y="186">
        rounds 7 and 13 hold my keepers (overall 76 and 148 from position 4): decided
      </text>
      <text className="sm" x="20" y="198">
        slots, not picks to plan
      </text>
    </svg>
  );
}

const BOARDS: { id: Board; label: string }[] = [
  { id: "hit", label: "board solved ahead" },
  { id: "cold", label: "cold board" },
];
const ACTS: { id: Act; label: string }[] = [
  { id: 0, label: "act at once" },
  { id: 15, label: "act at 15 s left" },
];
const ROWS: { id: Row; label: string }[] = [
  { id: "found", label: "row found" },
  { id: "top4", label: "top four missing" },
  { id: "none", label: "no row at all" },
];

/** One armed turn on the 30 s pick clock. */
function RoomClock() {
  const [board, setBoard] = useState<Board>("hit");
  const [act, setAct] = useState<Act>(0);
  const [row, setRow] = useState<Row>("found");
  const lanes = useMemo(() => rcLanes(board, act, row), [board, act, row]);
  return (
    <AnimFrame
      id="ex-rc"
      min={0}
      max={RC_END}
      step={0.1}
      speed={1}
      lanes={lanes}
      ticks={rcTicks}
      now={rcLeft}
      hint={`play runs the turn at real speed, ${RC_END} s; drag the slider, or step from event to event`}
      rangeLabel="seconds into the turn"
      label="One armed turn on the 30 s pick clock: the solve, the wait, the hold, the click, the backstop and Yahoo's autopick at zero"
      caption="The 30 s clock is the design point. The plan budget (the clock less 13 s of margin and 12 s of pricing, 5 s at least) is the API's; the wait's 12 s line, the act-at range of 12 to 30 s, the re-click at 1.8 s and 2.5 s, the 6 s backstop and the last look at 2 s are the extension's; the landing times are the mocks' typical ones. A trusted click by the user on any Draft control ends the turn at once. Reduced motion shows the final frame."
    >
      <span className="seg small" role="group" aria-label="the board">
        {BOARDS.map((b) => (
          <button key={b.id} className={board === b.id ? "on" : ""} aria-pressed={board === b.id} onClick={() => setBoard(b.id)}>
            {b.label}
          </button>
        ))}
      </span>
      <span className="seg small" role="group" aria-label="act-at">
        {ACTS.map((a) => (
          <button key={a.id} className={act === a.id ? "on" : ""} aria-pressed={act === a.id} onClick={() => setAct(a.id)}>
            {a.label}
          </button>
        ))}
      </span>
      <span className="seg small" role="group" aria-label="the row">
        {ROWS.map((r) => (
          <button key={r.id} className={row === r.id ? "on" : ""} aria-pressed={row === r.id} onClick={() => setRow(r.id)}>
            {r.label}
          </button>
        ))}
      </span>
    </AnimFrame>
  );
}

/** The extension's three hops, then one armed turn on the clock. */
export function YahooRoom() {
  return (
    <>
      <svg viewBox="0 0 420 274" role="img" aria-label="The extension's three hops: the draft page, the side panel's scripts, the API">
        <Arrow id="ex-ah-hops" />
        <rect className="win b" x="20" y="20" width="380" height="60" rx="8" />
        <text className="lbl" x="32" y="42">
          Yahoo draft page
        </text>
        <text className="sm" x="32" y="62">
          frames 0| pick · P| history · D| on the clock · C| clock · X| then 5| autopick
        </text>
        <rect className="node" x="20" y="100" width="115" height="44" rx="7" />
        <text className="lbl" x="77" y="119" textAnchor="middle">
          page.js
        </text>
        <text className="sm" x="77" y="135" textAnchor="middle">
          wraps the WebSocket
        </text>
        <rect className="node" x="152" y="100" width="115" height="44" rx="7" />
        <text className="lbl" x="209" y="119" textAnchor="middle">
          content.js
        </text>
        <text className="sm" x="209" y="135" textAnchor="middle">
          tracks the room
        </text>
        <rect className="node" x="284" y="100" width="116" height="44" rx="7" />
        <text className="lbl" x="342" y="119" textAnchor="middle">
          worker.js
        </text>
        <text className="sm" x="342" y="135" textAnchor="middle">
          the only API caller
        </text>
        <path className="arrow" d="M77 80v18" markerEnd="url(#ex-ah-hops)" />
        <path className="arrow" d="M135 122h15" markerEnd="url(#ex-ah-hops)" />
        <path className="arrow" d="M267 122h15" markerEnd="url(#ex-ah-hops)" />
        <path className="arrow" d="M342 144v20" markerEnd="url(#ex-ah-hops)" />
        <rect className="win a" x="20" y="166" width="380" height="60" rx="8" />
        <text className="lbl" x="32" y="188">
          the API: rooms keyed by draft id
        </text>
        <text x="32" y="208">picks idempotent by overall · a restart rebuilds the room from its</text>
        <text x="32" y="220">log · the room is the truth</text>
        <text className="sm" x="20" y="256">
          page.js listens only: one reader for the seat. A hidden tab's timers run in a
        </text>
        <text className="sm" x="20" y="268">
          Web Worker.
        </text>
      </svg>
      <RoomClock />
    </>
  );
}
