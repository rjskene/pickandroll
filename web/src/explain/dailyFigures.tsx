// The daily track's figures (#286): the sign-in check, the daily chain, the host and its
// watchdog, one queue entry's day under its own clock, the executor modes with the live guard,
// the late pass, the evening build and the evening pass with its hard stop. The day line itself
// (step 1) is figures.tsx's DayLine on dayline.ts.
import { useState } from "react";
import { ENTRY_EVENTS, ENTRY_MAX, ENTRY_MIN, ENTRY_NODES, ENTRY_SECONDS, STRIKES, T, entryGates, entryHhmm, entryState, wrap } from "./entryday";
import type { Strike } from "./entryday";
import { Arrow } from "./svg";
import { useClock } from "./useClock";

/** Both sites' signed-in state, read the honest way; either out is an alert. */
export function SigninCheck() {
  return (
    <svg viewBox="0 0 420 150" role="img" aria-label="The sign-in check: both sites signed in, or an alert">
      <Arrow id="ex-ah-signin" bad />
      <rect className="win g" x="12" y="24" width="190" height="44" rx="22" />
      <text className="lbl" x="107" y="46" textAnchor="middle">
        Yahoo · signed in
      </text>
      <text className="sm" x="107" y="61" textAnchor="middle">
        the My Team page, not a toolbar link
      </text>
      <rect className="win g" x="218" y="24" width="190" height="44" rx="22" />
      <text className="lbl" x="313" y="46" textAnchor="middle">
        projections · signed in
      </text>
      <text className="sm" x="313" y="61" textAnchor="middle">
        the export link is present
      </text>
      <path className="arrow bad" d="M210 80v26" markerEnd="url(#ex-ah-signin)" />
      <rect className="stop" x="40" y="108" width="340" height="30" rx="6" />
      <text className="t bad" x="210" y="127" textAnchor="middle">
        either out → an alert naming the one command the user runs
      </text>
    </svg>
  );
}

const CHAIN: [string, string][] = [
  ["exports", "5 downloads"],
  ["private pages", "read-only"],
  ["refresh", "paced + retry"],
  ["solve", "decision log"],
  ["Start Active", "where due"],
  ["lineups", "today, tomorrow"],
  ["queue", "from the sets"],
  ["digest", "to the tracker"],
];

/** The daily chain's eight steps, two rows, the queue lit. */
export function DailyFlow() {
  const w = 88;
  const g = 10;
  const h = 44;
  const x4 = 10 + 3 * (w + g) + w / 2;
  return (
    <svg viewBox="0 0 420 230" role="img" aria-label="The daily routine's steps, in order">
      <Arrow id="ex-ah-daily" />
      {CHAIN.map((it, i) => {
        const row = i < 4 ? 0 : 1;
        const col = row === 0 ? i : 7 - i;
        const x = 10 + col * (w + g);
        const y = row === 0 ? 20 : 120;
        const hot = it[0] === "queue";
        return (
          <g key={it[0]}>
            <rect className={`node${hot ? " hot" : ""}`} x={x} y={y} width={w} height={h} rx="7" />
            <text className={`lbl xs${hot ? " ink" : ""}`} x={x + w / 2} y={y + 20} textAnchor="middle">
              {it[0]}
            </text>
            <text className={`sm${hot ? " ink" : ""}`} x={x + w / 2} y={y + 36} textAnchor="middle">
              {it[1]}
            </text>
            {row === 0 && i < 3 && <path className="arrow" d={`M${x + w} ${y + h / 2}h${g}`} markerEnd="url(#ex-ah-daily)" />}
            {row === 1 && i < 7 && <path className="arrow" d={`M${x} ${y + h / 2}h-${g}`} markerEnd="url(#ex-ah-daily)" />}
          </g>
        );
      })}
      <path className="arrow" d={`M${x4} ${20 + h}v${120 - 20 - h}`} markerEnd="url(#ex-ah-daily)" />
      <text className="sm" x="10" y="186">
        each step one line in today's marker; a failed step posts an alert
      </text>
      <text className="sm" x="10" y="200">
        a routine outside its window refuses to run
      </text>
      <text className="ac sm" x="10" y="218">
        Mondays, 06:00: the recorder follows (last week, the scorecard, the hill-climb)
      </text>
    </svg>
  );
}

/** The host's pieces and the three things the watchdog checks. */
export function HostWatchdog() {
  return (
    <svg viewBox="0 0 420 232" role="img" aria-label="The host's pieces and what the watchdog checks">
      <Arrow id="ex-ah-host" />
      <rect className="node" x="20" y="20" width="120" height="44" rx="7" />
      <text className="lbl" x="80" y="39" textAnchor="middle">
        user timers
      </text>
      <text className="sm" x="80" y="55" textAnchor="middle">
        Central time
      </text>
      <rect className="win a" x="150" y="20" width="120" height="44" rx="7" />
      <text className="lbl" x="210" y="39" textAnchor="middle">
        today's marker
      </text>
      <text className="sm" x="210" y="55" textAnchor="middle">
        no failed step ✓
      </text>
      <rect className="win b" x="280" y="20" width="120" height="44" rx="7" />
      <text className="lbl" x="340" y="39" textAnchor="middle">
        headed browser
      </text>
      <text className="sm" x="340" y="55" textAnchor="middle">
        extension, user's profile
      </text>
      <rect className="win a" x="20" y="100" width="120" height="44" rx="7" />
      <text className="lbl" x="80" y="119" textAnchor="middle">
        data folder
      </text>
      <text className="sm" x="80" y="135" textAnchor="middle">
        copy stamp fresh ✓
      </text>
      <rect className="win a" x="150" y="100" width="120" height="44" rx="7" />
      <text className="lbl" x="210" y="119" textAnchor="middle">
        the API
      </text>
      <text className="sm" x="210" y="135" textAnchor="middle">
        answering ✓ · restarts itself
      </text>
      <rect className="node" x="280" y="100" width="120" height="44" rx="7" />
      <text className="lbl" x="340" y="119" textAnchor="middle">
        Yahoo · exports
      </text>
      <text className="sm" x="340" y="135" textAnchor="middle">
        pages, downloads
      </text>
      <rect className="win g" x="150" y="166" width="120" height="40" rx="7" />
      <text className="lbl" x="210" y="191" textAnchor="middle">
        the dashboard
      </text>
      <path className="arrow" d="M140 42h10M270 42h10M210 64v36M340 64v36M150 122h-10M210 144v22" markerEnd="url(#ex-ah-host)" />
      <text className="sm" x="280" y="200">
        private network only;
      </text>
      <text className="sm" x="280" y="212">
        nothing on a public port
      </text>
      <text className="ac sm" x="20" y="226">
        06:45: marker, API, copy stamp; anything else is an alert and a line on the ops issue
      </text>
    </svg>
  );
}

const X0 = 30;
const X1 = 400;
const xm = (t: number) => X0 + ((t - ENTRY_MIN) * (X1 - X0)) / (ENTRY_MAX - ENTRY_MIN);

/** One queue entry's day under its own clock, with the user's strike as a toggle. */
export function EntryDay() {
  const [strike, setStrike] = useState<Strike>(0);
  const clock = useClock({ min: ENTRY_MIN, max: ENTRY_MAX, speed: (ENTRY_MAX - ENTRY_MIN) / ENTRY_SECONDS, events: ENTRY_EVENTS });
  const t = clock.t;
  const st = entryState(t, strike);
  const gates = entryGates(t, strike);
  const nw = 50;
  const ng = 6;
  const ny = 16;
  const nh = 30;
  const yc = 92;
  const lines = gates.map((g) => wrap(g.text, 64));
  let yg = 140;
  const rows = lines.map((ls) => {
    const at = yg;
    yg += ls.length * 11 + 5;
    return at;
  });
  const H = yg + 2;
  const ticks: number[] = [];
  for (let m = 360; m <= ENTRY_MAX; m += 180) ticks.push(m);
  const dots: [number, string, number][] = [
    [T.pass, "09:15", 9],
    [T.late, "15:00", 9],
    [T.build, "21:00", 9],
    [T.evening, "22:40", 19],
  ];
  return (
    <div className="ex-anim ex-entry">
      <div className="ex-ctl">
        <button className={`ex-play${clock.playing ? " on" : ""}`} onClick={clock.toggle} disabled={clock.reduced} aria-pressed={clock.playing}>
          {clock.playing ? "❚❚ pause" : "▶ play"}
        </button>
        <button onClick={clock.prev} title="previous event">
          ⇤ event
        </button>
        <button onClick={clock.next} title="next event">
          event ⇥
        </button>
        <span className="ex-now" aria-live="off">
          {entryHhmm(t)}
        </span>
        <span className="seg small" role="group" aria-label="the strike">
          {STRIKES.map((s) => (
            <button key={s.id} className={strike === s.id ? "on" : ""} aria-pressed={strike === s.id} onClick={() => setStrike(s.id)}>
              {s.label}
            </button>
          ))}
        </span>
        <span className="ex-hint">
          {clock.reduced
            ? "reduced motion: the final frame is shown; drag the slider, or step from event to event"
            : `play runs the day in ${ENTRY_SECONDS} s; drag the slider, step from event to event, or strike the entry and watch the gates change`}
        </span>
      </div>
      <svg viewBox={`0 0 420 ${H}`} role="img" aria-label="One queued entry's day: the gates it passes, and when">
        <Arrow id="ex-ah-entry" />
        {ENTRY_NODES.map((n, i) => {
          const x = X0 - 10 + i * (nw + ng);
          const cls = st.dead && i === 1 ? "bad" : i < st.cur ? "done" : i === st.cur ? "hot" : "";
          const words = n.name.split(" ");
          const cx = x + nw / 2;
          return (
            <g key={n.name}>
              <rect className={`node ${cls}`} x={x} y={ny} width={nw} height={nh} rx="6" />
              <text className={`lbl xs${cls === "hot" ? " ink" : ""}`} x={cx} y={words.length > 1 ? ny + 13 : ny + 19} textAnchor="middle">
                {words.map((w, j) => (
                  <tspan key={w} x={cx} dy={j ? 12 : 0}>
                    {w}
                  </tspan>
                ))}
              </text>
              <text className="sm xs" x={cx} y={ny + nh + 12} textAnchor="middle">
                {n.at}
              </text>
              {n.note && (
                <text className="sm xs dim" x={cx} y={ny + nh + 22} textAnchor="middle">
                  {n.note}
                </text>
              )}
              {i < ENTRY_NODES.length - 1 && <path className="arrow" d={`M${x + nw} ${ny + nh / 2}h${ng}`} />}
            </g>
          );
        })}
        <line className="axis" x1={X0} y1={yc} x2={X1} y2={yc} />
        {ticks.map((m) => (
          <g key={m}>
            <line className="grid" x1={xm(m)} y1={yc - 6} x2={xm(m)} y2={yc + 6} />
            <text className="sm xs" x={xm(m)} y={yc + 18} textAnchor="middle">
              {String(Math.floor(m / 60) % 24).padStart(2, "0")}
            </text>
          </g>
        ))}
        <rect className="band a" x={xm(T.queued)} y={yc - 5} width={xm(T.exec) - xm(T.queued)} height="10" rx="2" />
        <text className="ac sm xs" x={xm(T.queued)} y={yc - 19}>
          veto window
        </text>
        <line className="ref ac" x1={xm(T.exec)} y1={yc - 14} x2={xm(T.exec)} y2={yc + 8} />
        {dots.map(([m, l, dy]) => (
          <g key={l}>
            <circle className="dot m" cx={xm(m)} cy={yc} r="3" />
            <text className="sm xs" x={xm(m)} y={yc - dy} textAnchor="middle">
              {l}
            </text>
          </g>
        ))}
        <line className="stopline" x1={xm(T.stop)} y1={yc - 8} x2={xm(T.stop)} y2={yc + 8} />
        <circle className="dot g" cx={xm(T.run)} cy={yc} r="3.5" />
        <text className="sm xs" x={xm(T.run)} y={yc - 9} textAnchor="middle">
          Yahoo's run
        </text>
        <line className="grid" x1={xm(1440)} y1={yc - 14} x2={xm(1440)} y2={yc + 10} />
        <text className="sm xs dim" x={xm(1440) + 2} y={yc + 30}>
          next day
        </text>
        {strike !== 0 && <line className="ref bad" x1={xm(T.strike)} y1={yc - 14} x2={xm(T.strike)} y2={yc + 8} />}
        <line className="marker" x1={xm(t)} y1={yc - 16} x2={xm(t)} y2={yc + 10} />
        <path className="marker-head" d={`M${xm(t) - 5} ${yc - 22}h10l-5 7z`} />
        {gates.map((g, i) => (
          <g key={i}>
            <circle className={`gate ${g.k}`} cx={X0 + 4} cy={rows[i] - 3} r="3.5" />
            {lines[i].map((ln, j) => (
              <text key={j} className={g.k === "off" ? "sm dim" : "sm t"} x={X0 + 14} y={rows[i] + j * 11}>
                {ln}
              </text>
            ))}
          </g>
        ))}
      </svg>
      <input type="range" min={ENTRY_MIN} max={ENTRY_MAX} step={5} value={t} onChange={(e) => clock.set(Number(e.target.value))} aria-label="time, from 05:00 to 06:00 the next day" />
      <p className="ex-cap">
        One entry of the morning's queue (add W, drop D, bid $3) from the build at 05:40 to the daily that reads its outcome the next morning. The chain is its state; the list is each gate at the marker's time, green when passed, red when it blocks, grey when not yet asked. The times of the example are a weekday's; the rules are the code's. Reduced motion shows the final frame.
      </p>
    </div>
  );
}

/** The executor modes, the live guard between them, the STOP file over all, the page check. */
export function ExecutorModes() {
  return (
    <svg viewBox="0 0 420 222" role="img" aria-label="Executor modes, the live guard, and the page check">
      <Arrow id="ex-ah-modes" />
      <rect className="stop" x="20" y="14" width="380" height="30" rx="6" />
      <text className="t bad" x="210" y="33" textAnchor="middle">
        STOP file: every executor halts, every run says so
      </text>
      <rect className="win" x="20" y="64" width="110" height="40" rx="20" />
      <text className="lbl" x="75" y="89" textAnchor="middle">
        off
      </text>
      <rect className="win b" x="155" y="64" width="110" height="40" rx="20" />
      <text className="lbl" x="210" y="89" textAnchor="middle">
        dry run
      </text>
      <rect className="win a" x="290" y="64" width="110" height="40" rx="20" />
      <text className="lbl" x="345" y="89" textAnchor="middle">
        live
      </text>
      <path className="arrow" d="M130 84h22M265 84h22" markerEnd="url(#ex-ah-modes)" />
      <text className="sm" x="142" y="120" textAnchor="middle">
        the user's click
      </text>
      <text className="ac sm" x="277" y="120" textAnchor="middle">
        the live guard
      </text>
      <rect className="win g" x="20" y="136" width="380" height="30" rx="6" />
      <text className="t sm" x="210" y="155" textAnchor="middle">
        the page check: available · drop on the roster · under the cap · not struck
      </text>
      <text className="sm" x="20" y="190">
        a page that does not match is logged and skipped, never forced · one live run
      </text>
      <text className="sm" x="20" y="202">
        per league per pass
      </text>
      <text className="sm" x="20" y="216">
        the private league is always off and refuses the switch
      </text>
    </svg>
  );
}

const LATE: [string, string][] = [
  ["lineups", "today's news"],
  ["moves", "still due"],
  ["IL", "stash or return"],
  ["Start Active", "after a change"],
];

/** The late pass's four jobs, and the tip-off they run before. */
export function LatePass() {
  return (
    <svg viewBox="0 0 420 162" role="img" aria-label="The late pass's four jobs, before the first tip-off">
      {LATE.map((j, i) => {
        const x = 20 + i * 98;
        const w = i === 3 ? 86 : 88;
        return (
          <g key={j[0]}>
            <rect className="win g" x={x} y="24" width={w} height="50" rx="7" />
            <text className="lbl xs" x={x + w / 2} y="46" textAnchor="middle">
              {j[0]}
            </text>
            <text className="sm" x={x + w / 2} y="62" textAnchor="middle">
              {j[1]}
            </text>
          </g>
        );
      })}
      <line className="ref" x1="20" y1="100" x2="400" y2="100" />
      <circle className="dot" cx="92" cy="100" r="5" />
      <text className="ac sm" x="92" y="120" textAnchor="middle">
        15:00
      </text>
      <circle className="dot m" cx="300" cy="100" r="5" />
      <text className="sm" x="300" y="120" textAnchor="middle">
        first tip-off
      </text>
      <text className="sm" x="20" y="142">
        window to 20:30; lineups before the first tip-off, on the baseline Start Active
      </text>
      <text className="sm" x="20" y="154">
        Players set
      </text>
    </svg>
  );
}

const BUILD: [string, boolean][] = [
  ["export", false],
  ["re-read", false],
  ["re-solve", false],
  ["rebuild", true],
];

/** The evening build: the morning's chain again, shorter, the queue rebuilt. */
export function EveningBuild() {
  return (
    <svg viewBox="0 0 420 154" role="img" aria-label="The evening build">
      <Arrow id="ex-ah-build" />
      {BUILD.map(([name, hot], i) => {
        const x = 20 + i * 100;
        return (
          <g key={name}>
            <rect className={`node${hot ? " hot" : ""}`} x={x} y="24" width="80" height="40" rx="7" />
            <text className={`lbl${hot ? " ink" : ""}`} x={x + 40} y="48" textAnchor="middle">
              {name}
            </text>
            {i < 3 && <path className="arrow" d={`M${x + 80} 44h20`} markerEnd="url(#ex-ah-build)" />}
          </g>
        );
      })}
      <text className="sm" x="20" y="92">
        window 21:00 to 21:30: the same chain as the morning, shorter, on the day's
      </text>
      <text className="sm" x="20" y="104">
        information
      </text>
      <text className="sm" x="20" y="120">
        struck and executed entries kept by id; an entry no longer recommended is
      </text>
      <text className="sm" x="20" y="132">
        parked as superseded
      </text>
    </svg>
  );
}

/** The evening pass, Sunday's own execute time, and the hard stop. */
export function EveningPass() {
  return (
    <svg viewBox="0 0 420 152" role="img" aria-label="The evening pass and its hard stop">
      <line className="axis" x1="30" y1="70" x2="400" y2="70" />
      <rect className="band g" x="180" y="56" width="110" height="28" rx="4" />
      <circle className="dot g" cx="180" cy="70" r="6" />
      <text className="t" x="180" y="100" textAnchor="middle">
        22:40 pass
      </text>
      <circle className="dot" cx="130" cy="70" r="5" />
      <text className="ac sm" x="130" y="50" textAnchor="middle">
        Sunday 22:30
      </text>
      <line className="ref bad" x1="290" y1="40" x2="290" y2="100" />
      <text className="sm bad" x="294" y="48">
        22:58 hard stop
      </text>
      <text className="sm" x="30" y="128">
        a Sunday claim clears on Monday, so Sunday's entries wait for 22:30; a run
      </text>
      <text className="sm" x="30" y="140">
        past the stop ends where it is
      </text>
    </svg>
  );
}
