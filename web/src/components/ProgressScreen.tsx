import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type KnobChange, type KnobName, type ProgressLeague, type ProgressPayload, type ProgressSentence, type Scoring } from "../api";
import { pct } from "../format";
import {
  DEFAULT_PROGRESS_VIEWS,
  DRAWER_WIDTH,
  isShown,
  parseViewsOf,
  PROGRESS_CARDS,
  PROGRESS_SHEET,
  PROGRESS_VIEWS,
  progressKeys,
  type DrawerState,
  type ProgressCardId,
  type ProgressViewId,
  type Views,
} from "../keys";
import {
  CHANGE_RULE,
  changeWhat,
  judgedAfter,
  KNOB_SHORT,
  KNOB_TITLE,
  knobValue,
  LINEUP_LOST_TITLE,
  METRICS,
  POOLED,
  publicLeagues,
  rangeSum,
  recordedRange,
  recordLabel,
  scopeSentences,
  scopeWeeks,
  stepChange,
  stepRange,
  trend,
  UNITS,
  UNITS_SHORT,
  verdictLabel,
  whyTried,
  type Metric,
  type MovesSum,
  type RangeSum,
  type ScopeWeek,
} from "../progress";
import { gainLabel, ordinal, unitsLabel } from "../season";
import { useDrawer, useHotkeys, useViewsOf } from "../useKeys";
import Halves, { type Face } from "./Halves";
import KeySheet from "./KeySheet";
import ProgressChart, { type Marker, type Series } from "./ProgressChart";
import Rail from "./Rail";
import ViewDrawer from "./ViewDrawer";
import { Close, PROGRESS_ICONS, PROGRESS_VIEW_ICONS } from "./icons";

const PANEL_KEY = "pickandroll.progress.drawer";
const VIEW_KEY = "pickandroll.progress.view";
const isPanelCard = (v: unknown): v is ProgressCardId => typeof v === "string" && PROGRESS_CARDS.some((c) => c.id === v);
const DEFAULT_PANEL: DrawerState<ProgressCardId> = {
  top: "note",
  bottom: "knobs",
  collapsed: false,
  split: 0.6,
  last: { top: "note", bottom: "knobs" },
  width: DRAWER_WIDTH,
};
const parseViews = (raw: string | null): Views<ProgressViewId> => parseViewsOf(raw, PROGRESS_VIEWS, DEFAULT_PROGRESS_VIEWS);

const signed1 = (x: number) => gainLabel(x, 1);
const weekDates = (w: { start: string; end: string }) => {
  const d = (s: string) => new Date(`${s}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" }).toLowerCase();
  return `${d(w.start)} – ${d(w.end)}`;
};

/** The Progress screen (#129; docs/AUTOPILOT.md section 6): the hill-climb over the season,
 * read-only. The league page's shell (#109, #116): views at the left (Trend), the cards at the
 * right (the Monday note, the knobs, the league chosen) and their rail and keys; a knob
 * change's sheet over the view. Nothing on it writes anything. */
export default function ProgressScreen({ onBack, onOpenLeague }: { onBack: () => void; onOpenLeague: (league: string) => void }) {
  const q = useQuery({ queryKey: ["progress"], queryFn: api.progress, refetchInterval: 600_000 });
  const p = q.data;
  const panel = useDrawer(PANEL_KEY, isPanelCard, DEFAULT_PANEL, DEFAULT_PANEL.last);
  const views = useViewsOf(VIEW_KEY, parseViews);
  const [scope, setScope] = useState(POOLED);
  const [metric, setMetric] = useState<Metric>("wins");
  const [range, setRange] = useState<[number, number] | null>(null);
  const [change, setChange] = useState<string | null>(null);
  const [noteAt, setNoteAt] = useState<number | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const changes = p?.knobs.changes ?? [];
  useHotkeys(
    progressKeys({
      setView: views.setView,
      toggleViews: views.toggleViews,
      openCard: panel.openCard,
      toggleDrawer: panel.toggleDrawer,
      swapHalves: panel.swapHalves,
      collapse: panel.collapseDrawer,
      sheetChange: change,
      closeChange: () => setChange(null),
      stepChange: (delta) => setChange((id) => (id ? stepChange(changes, id, delta) : id)),
      sheetOpen,
      setSheetOpen,
    }),
  );
  // A scope chosen from a row or a card shows in the League card.
  const choose = (league: string) => {
    setScope(league);
    if (league !== POOLED && !isShown(panel.drawer, "league")) panel.openCard("league", "bottom");
  };
  const face = (id: ProgressCardId): Face => {
    if (!p) return { body: null };
    switch (id) {
      case "note":
        return noteFace(p, noteAt, setNoteAt, setChange);
      case "knobs":
        return { note: "read-only", body: <KnobsCard p={p} onOpen={setChange} /> };
      case "league":
        return {
          note: scope === POOLED ? "all public · pooled" : p.leagues.find((l) => l.league === scope)?.public === false ? "private · suggestions only" : `league ${scope}`,
          body: <LeagueCard p={p} scope={scope} onScope={choose} onOpenLeague={onOpenLeague} />,
        };
      default:
        return { body: null };
    }
  };
  const open = changes.find((c) => c.id === change) ?? null;
  return (
    <main className="shell">
      <header className="topbar season-top">
        <div className="wordmark">
          PICK<span>&amp;</span>ROLL
        </div>
        <span className="muted title">Progress · the hill-climb</span>
        <span className="grow" />
        {p && <TopLine p={p} />}
        <button className="link" onClick={onBack}>
          all leagues
        </button>
      </header>
      {q.error && <p className="error" style={{ padding: "0 24px" }}>{q.error.message}</p>}
      {!p && !q.error && (
        <p className="muted" style={{ padding: 24 }}>
          Reading the season…
        </p>
      )}
      {p && (
        <>
          <div className="main season progress">
            <div className="season-body">
              <ViewDrawer views={PROGRESS_VIEWS} icons={PROGRESS_VIEW_ICONS} view={views.view} shown={views.shown} onView={views.setView} onToggle={views.toggleViews} />
              <div className="board-col view-col">
                <TrendView p={p} scope={scope} onScope={choose} metric={metric} setMetric={setMetric} range={range} setRange={setRange} onChange={setChange} onOpenLeague={onOpenLeague} />
              </div>
              <Halves d={panel} cards={PROGRESS_CARDS} face={face} />
            </div>
            <Rail
              cards={PROGRESS_CARDS}
              icons={PROGRESS_ICONS}
              on={(id) => isShown(panel.drawer, id)}
              onOpen={panel.openCard}
              onSheet={() => setSheetOpen(true)}
              open={panel.drawerOpen}
              onToggle={panel.toggleDrawer}
              noun="panel"
            />
          </div>
          <ProgressFooter p={p} />
        </>
      )}
      {p && open && <KnobSheet p={p} c={open} onClose={() => setChange(null)} onStep={(d) => setChange(stepChange(changes, open.id, d))} />}
      <KeySheet sheet={PROGRESS_SHEET} open={sheetOpen} onClose={() => setSheetOpen(false)} />
    </main>
  );
}

/** The top bar: the weeks scored, the leagues, this week, the pooled record against
 * expected, and the change pending. */
function TopLine({ p }: { p: ProgressPayload }) {
  const pub = p.leagues.filter((l) => l.public);
  const apart = p.leagues.filter((l) => !l.public).map((l) => l.league);
  const sum = rangeSum(scopeWeeks(p, POOLED));
  const pending = p.knobs.changes.find((c) => !c.verdict);
  const week = p.weeks.find((w) => w.week === p.week);
  return (
    <>
      <span className="muted">
        {p.last_recorded ? `${p.last_recorded} week${p.last_recorded === 1 ? "" : "s"} scored` : "no week scored yet"} · {pub.length} public league{pub.length === 1 ? "" : "s"}
        {apart.length > 0 && ` · ${apart.join(", ")} apart`}
      </span>
      {week && (
        <span className="k">
          week {week.week} · {weekDates(week)}
        </span>
      )}
      {sum.projected > 0 && (
        <span className="pill" title="the public leagues pooled: matchups won against the odds of winning them">
          {recordLabel(sum.record)} · {sum.expected.toFixed(1)} exp
        </span>
      )}
      {pending && (
        <span className="accent" title={changeWhat(pending, KNOB_TITLE)}>
          {pending.id} pending{judgedAfter(pending) != null ? ` · judged after wk ${judgedAfter(pending)}` : ""}
        </span>
      )}
    </>
  );
}

// ---------------------------------------------------------------- the Trend view
function TrendView({
  p,
  scope,
  onScope,
  metric,
  setMetric,
  range,
  setRange,
  onChange,
  onOpenLeague,
}: {
  p: ProgressPayload;
  scope: string;
  onScope: (scope: string) => void;
  metric: Metric;
  setMetric: (m: Metric) => void;
  range: [number, number] | null;
  setRange: (r: [number, number] | null) => void;
  onChange: (id: string) => void;
  onOpenLeague: (league: string) => void;
}) {
  const recorded = p.leagues.filter((l) => l.weeks.length > 0);
  const bounds = recordedRange(p, scope);
  const shown: [number, number] | null = bounds && (range ? [Math.max(range[0], bounds[0]), Math.min(range[1], bounds[1])] : bounds);
  const [from, to] = shown && shown[0] <= shown[1] ? shown : (bounds ?? [1, 0]);
  const weeks = bounds ? scopeWeeks(p, scope, from, to) : [];
  const sum = rangeSum(weeks);
  const points = trend(weeks, metric);
  const step = (end: 0 | 1, delta: number) => {
    if (bounds) setRange(stepRange([from, to], bounds, end, delta));
  };
  const markers: Marker[] = p.knobs.changes
    .filter((c) => c.week != null && c.week >= from && c.week <= to)
    .map((c) => ({ week: c.week!, id: c.id, title: `${c.id} · ${changeWhat(c, KNOB_TITLE)}`, onOpen: () => onChange(c.id) }));
  const series: Series[] =
    metric === "standing"
      ? [{ key: "place", label: scope === POOLED ? "mean place" : "place", tone: "actual", values: points.map((t) => t.actual) }]
      : [
          { key: "actual", label: "actual", tone: "actual", values: points.map((t) => t.actual) },
          { key: "expected", label: "expected at decision time", tone: "expected", values: points.map((t) => t.expected) },
        ];
  const say = scopeSentences(p.sentences, scope);
  const nowWeek = p.week != null && p.week > to && to === bounds?.[1] ? p.weeks.find((w) => w.week === p.week) : undefined;
  return (
    <div className="season-view progress-view">
      <div className="sv-head">
        <span className="k">Season to date</span>
        <span className="seg small" role="group" aria-label="Scope">
          <button className={scope === POOLED ? "on" : undefined} aria-pressed={scope === POOLED} onClick={() => onScope(POOLED)} title="the public leagues pooled; the private league stays apart">
            All public · pooled
          </button>
          {recorded.map((l) => (
            <button key={l.league} className={scope === l.league ? "on" : undefined} aria-pressed={scope === l.league} onClick={() => onScope(l.league)}>
              {l.league}
              {l.public ? "" : " · private"}
            </button>
          ))}
        </span>
        <span className="seg small" role="tablist" aria-label="Metric">
          {METRICS.map((m) => (
            <button key={m.id} role="tab" aria-selected={metric === m.id} className={metric === m.id ? "on" : undefined} title={m.title} onClick={() => setMetric(m.id)}>
              {m.label}
            </button>
          ))}
        </span>
        {bounds && (
          <span className="pg-range" aria-label="Weeks shown">
            <span className="dim">weeks</span>
            <button className="small" disabled={from <= bounds[0]} onClick={() => step(0, -1)} aria-label="Start a week earlier">
              ‹
            </button>
            <b>{from}</b>
            <button className="small" disabled={from >= to} onClick={() => step(0, 1)} aria-label="Start a week later">
              ›
            </button>
            <span className="dim">to</span>
            <button className="small" disabled={to <= from} onClick={() => step(1, -1)} aria-label="End a week earlier">
              ‹
            </button>
            <b>{to}</b>
            <button className="small" disabled={to >= bounds[1]} onClick={() => step(1, 1)} aria-label="End a week later">
              ›
            </button>
            {(from !== bounds[0] || to !== bounds[1]) && (
              <button className="link" onClick={() => setRange(null)}>
                all
              </button>
            )}
          </span>
        )}
      </div>
      {!bounds ? (
        <p className="muted pg-empty">
          {scope === POOLED ? "No public league" : `League ${scope}`} has a scored week yet. The Monday recorder scores each week once it ends, against the odds the decision log
          held for it; the weeks show here from the first one scored.
        </p>
      ) : (
        <>
          <Tiles sum={sum} metric={metric} scope={scope} from={from} to={to} />
          {say.length > 0 && <Sentences say={say} />}
          <ProgressChart
            weeks={points.map((t) => t.week)}
            series={series}
            markers={markers}
            markerKey="knob change · click for its sheet"
            invert={metric === "standing"}
            integer={metric === "standing" && scope !== POOLED}
            fmt={metric === "standing" ? (v) => (Number.isInteger(v) ? ordinal(v) : v.toFixed(1)) : (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1))}
            tickFmt={metric === "standing" && scope !== POOLED ? ordinal : String}
            label={`${METRICS.find((m) => m.id === metric)!.label}, weeks ${from} to ${to}`}
            tip={(i) => <TrendTip t={points[i]} metric={metric} p={p} scope={scope} />}
          />
          <WeekStrip weeks={weeks} scope={scope} changes={p.knobs.changes} now={nowWeek} onChange={onChange} />
          <LeagueTable p={p} from={from} to={to} scope={scope} onScope={onScope} onOpenLeague={onOpenLeague} />
        </>
      )}
    </div>
  );
}

function Tiles({ sum, metric, scope, from, to }: { sum: RangeSum; metric: Metric; scope: string; from: number; to: number }) {
  const results = sum.record[0] + sum.record[1] + sum.record[2];
  const gap = sum.won - sum.expected;
  const units = (Object.entries(sum.compared) as [Scoring, MovesSum][]).filter(([, c]) => c.moves > 0);
  const over = from === to ? `wk ${from}` : `wks ${from}–${to}`;
  return (
    <div className="pg-tiles">
      {metric === "wins" && (
        <Tile k="wins" v={recordLabel(sum.record)} title="matchups won, lost and tied; expected sums the odds of winning each, as the decision log held them">
          of {results} · {sum.expected.toFixed(1)} expected
          {sum.projected > 0 && <span className={Math.abs(gap) < 0.05 ? "dim" : gap > 0 ? "good" : "bad"}> · {signed1(gap)}</span>}
        </Tile>
      )}
      {metric === "categories" && (
        <Tile k="categories" v={sum.categories == null ? "—" : sum.categories.toFixed(1)} title="categories won, a tie as half, against those expected; categories leagues only">
          {sum.expectedCategories == null ? "no categories league scored" : `${sum.expectedCategories.toFixed(1)} expected`}
          {sum.categories != null && sum.expectedCategories != null && (
            <span className={sum.categories >= sum.expectedCategories ? "good" : "bad"}> · {signed1(sum.categories - sum.expectedCategories)}</span>
          )}
        </Tile>
      )}
      {metric === "standing" && (
        <Tile
          k={scope === POOLED ? "mean place" : "place"}
          v={sum.rankLast == null ? "—" : scope === POOLED ? sum.rankLast.toFixed(1) : ordinal(sum.rankLast)}
          title={scope === POOLED ? "the mean place of the public leagues after the last week shown" : "the place after the last week shown"}
        >
          {sum.rankFirst == null ? "no standing read" : `${scope === POOLED ? sum.rankFirst.toFixed(1) : ordinal(sum.rankFirst)} after wk ${from}`}
        </Tile>
      )}
      <Tile
        k="moves"
        v={units.length ? units.map(([s, c]) => (c.share == null ? "—" : `${pct(c.share)}${units.length > 1 ? ` ${UNITS_SHORT[s]}` : ""}`)).join(" · ") : "—"}
        title="the scored moves over a complete week: their realized value against their projected, by the units of their leagues (fantasy points and category value never sum together)"
      >
        {units.length === 0
          ? `${sum.made} made · none scored over a complete week yet`
          : units.map(([s, c]) => (
              <span key={s} className="pg-unit">
                {gainLabel(c.realized, s === "points" ? 0 : 1)} of {gainLabel(c.projected, s === "points" ? 0 : 1)} {UNITS[s]} · {c.moves} move{c.moves === 1 ? "" : "s"}
              </span>
            ))}
        {units.length > 0 && <span className="pg-unit dim">realized of projected · {sum.made} made</span>}
      </Tile>
      <Tile k="brier" v={sum.brierLast == null ? "—" : sum.brierLast.toFixed(2)} title="the matchup odds' Brier score: 0.25 is a coin flip, lower is better">
        {sum.brier == null ? "no odds scored" : `last week · ${sum.brier.toFixed(2)} over ${over}`}
      </Tile>
    </div>
  );
}

function Tile({ k, v, title, children }: { k: string; v: string; title: string; children: ReactNode }) {
  return (
    <div className="pg-tile" title={title}>
      <span className="k">{k}</span>
      <span className="v">{v}</span>
      <span className="muted">{children}</span>
    </div>
  );
}

const TONE_MARK: Record<ProgressSentence["tone"], string> = { good: "▲", bad: "▼", neutral: "·" };

function Sentences({ say }: { say: ProgressSentence[] }) {
  return (
    <ul className="pg-say" aria-label="What the numbers say">
      {say.map((s, i) => (
        <li key={i}>
          <span className={`mark ${s.tone}`} aria-label={s.tone === "neutral" ? undefined : s.tone === "good" ? "better" : "worse"}>
            {TONE_MARK[s.tone]}
          </span>
          {s.text}
        </li>
      ))}
    </ul>
  );
}

function TrendTip({ t, metric, p, scope }: { t: ReturnType<typeof trend>[number]; metric: Metric; p: ProgressPayload; scope: string }) {
  const w = t.w;
  const started = p.knobs.changes.filter((c) => c.week === w.week);
  const head =
    metric === "standing"
      ? t.actual == null
        ? "no standing"
        : scope === POOLED
          ? `${t.actual.toFixed(1)} mean place`
          : `${ordinal(t.actual)} of ${w.teams ?? "?"}`
      : t.actual == null
        ? "nothing scored"
        : `${t.actual.toFixed(1)} ${metric === "wins" ? "wins" : "categories"}`;
  return (
    <>
      <div className="muted">
        week {w.week} · {weekDates(w)}
      </div>
      <div className="v">{head}</div>
      {metric !== "standing" && t.expected != null && <div className="muted">{t.expected.toFixed(1)} expected to it</div>}
      <div>
        {recordLabel(w.record)} on the week · {w.expected.toFixed(1)} expected{w.brier != null ? ` · Brier ${w.brier.toFixed(2)}` : ""}
      </div>
      {scope === POOLED &&
        w.lines.map((l) => (
          <div key={l.league} className="dim">
            {l.league} · {l.outcome ?? "—"}
            {l.expected != null ? ` at ${pct(l.expected)}` : ""}
            {l.rank != null ? ` · ${ordinal(l.rank)}` : ""}
          </div>
        ))}
      {started.map((c) => (
        <div key={c.id} className="accent">
          {c.id} started · {changeWhat(c)}
        </div>
      ))}
    </>
  );
}

/** Each week's result against its expected, and the knob changes that started in it. */
function WeekStrip({ weeks, scope, changes, now, onChange }: { weeks: ScopeWeek[]; scope: string; changes: KnobChange[]; now?: { week: number }; onChange: (id: string) => void }) {
  return (
    <div className="sv-strip pg-strip" aria-label="Weeks">
      {weeks.map((w) => {
        const started = changes.filter((c) => c.week === w.week);
        const gap = w.won - w.expected;
        const tone = w.projected === 0 ? "unread" : Math.abs(gap) < 0.05 ? "" : gap > 0 ? "good" : "bad";
        const single = scope !== POOLED;
        return (
          <div key={w.week} className={`sv-chip ${tone}`} title={`week ${w.week} · ${weekDates(w)}: ${w.won} won against ${w.expected.toFixed(2)} expected`}>
            <span className="wk">
              WK {w.week}{" "}
              {started.map((c) => (
                <button key={c.id} className="link pg-k" onClick={() => onChange(c.id)} title={`${c.id} · ${changeWhat(c, KNOB_TITLE)}: open its sheet`}>
                  {c.id}
                </button>
              ))}
            </span>
            <span className="odds">{single ? (w.lines[0]?.outcome ?? "—") : recordLabel(w.record)}</span>
            <span className="dim">{single ? (w.lines[0]?.expected != null ? `${pct(w.lines[0].expected)} to win` : "no odds") : `${w.expected.toFixed(1)} exp`}</span>
          </div>
        );
      })}
      {now && (
        <div className="sv-chip unread" title="this week: in play, scored once it ends">
          <span className="wk">
            WK {now.week} <em>now</em>
          </span>
          <span className="odds">—</span>
          <span className="dim">in play</span>
        </div>
      )}
    </div>
  );
}

function LeagueTable({
  p,
  from,
  to,
  scope,
  onScope,
  onOpenLeague,
}: {
  p: ProgressPayload;
  from: number;
  to: number;
  scope: string;
  onScope: (scope: string) => void;
  onOpenLeague: (league: string) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const leagues = [...p.leagues.filter((l) => l.public), ...p.leagues.filter((l) => !l.public)].filter((l) => l.weeks.length > 0);
  if (!leagues.length) return null;
  return (
    <div className="pg-scroll">
      <table className="season-table pg-leagues">
        <thead>
          <tr>
            <th>League</th>
            <th className="num" title="matchups won and lost over the weeks shown">
              W-L
            </th>
            <th className="num" title="the odds of winning, summed over the weeks shown">
              Exp
            </th>
            <th className="num" title="wins above expected">
              Δ
            </th>
            <th className="num" title="moves made">
              Moves
            </th>
            <th className="num" title="the moves' realized value over their week, in the league's units: fantasy points, or category value">
              Realized
            </th>
            <th className="num" title={LINEUP_LOST_TITLE}>
              Lineup lost
            </th>
            <th className="num" title="the place after the last week shown">
              Stand
            </th>
            <th aria-label="Open" />
          </tr>
        </thead>
        <tbody>
          {leagues.map((l) => {
            const weeks = scopeWeeks(p, l.league, from, to);
            const s = rangeSum(weeks);
            const gap = s.won - s.expected;
            const scoring = l.scoring ?? "categories";
            const realized = s.realized[scoring];
            const expanded = open === l.league;
            return (
              <Fragment key={l.league}>
                <tr className={scope === l.league ? "mine" : undefined}>
                  <td>
                    <button className="link" onClick={() => onScope(l.league)} title="show this league in the chart and the League card">
                      {l.league}
                    </button>
                    {!l.public && <div className="dim small">private · suggestions only</div>}
                  </td>
                  <td className="num">{recordLabel(s.record)}</td>
                  <td className="num">{s.expected.toFixed(1)}</td>
                  <td className={`num ${Math.abs(gap) < 0.05 ? "" : gap > 0 ? "good" : "bad"}`}>{signed1(gap)}</td>
                  <td className="num">{s.made}</td>
                  <td className="num" title={UNITS[scoring]}>
                    {realized == null ? "" : unitsLabel(realized, scoring)}
                  </td>
                  <td className="num dim" title={LINEUP_LOST_TITLE}>
                    —
                  </td>
                  <td className="num">{s.rankLast == null ? "" : ordinal(s.rankLast)}</td>
                  <td>
                    <button className="link" aria-expanded={expanded} aria-label={`${expanded ? "Fold" : "Open"} league ${l.league}'s weeks`} onClick={() => setOpen(expanded ? null : l.league)}>
                      {expanded ? "▾" : "▸"}
                    </button>
                  </td>
                </tr>
                {expanded && (
                  <tr className="pg-open">
                    <td colSpan={9}>
                      <LeagueWeeks league={l} weeks={weeks} />
                      {scopeSentences(p.sentences, l.league).length > 0 && <Sentences say={scopeSentences(p.sentences, l.league)} />}
                      <button className="link" onClick={() => onOpenLeague(l.league)}>
                        open its league page
                      </button>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** A league's weeks in a few columns: the result against its odds, the categories, the moves, the place. */
function LeagueWeeks({ league, weeks }: { league: ProgressLeague; weeks: ScopeWeek[] }) {
  const scoring = league.scoring ?? "categories";
  return (
    <table className="season-table pg-weeks">
      <thead>
        <tr>
          <th>Wk</th>
          <th>Result</th>
          <th className="num">Odds</th>
          {scoring === "categories" && <th className="num">Cats</th>}
          <th className="num">Moves</th>
          <th className="num" title={UNITS[scoring]}>
            Realized
          </th>
          <th className="num">Stand</th>
        </tr>
      </thead>
      <tbody>
        {weeks.map((w) => {
          const line = w.lines[0];
          return (
            <tr key={w.week}>
              <td>{w.week}</td>
              <td>{line?.outcome ?? "—"}</td>
              <td className="num">{line?.expected != null ? pct(line.expected) : ""}</td>
              {scoring === "categories" && (
                <td className="num" title="categories won against expected">
                  {w.categories != null && w.expectedCategories != null ? `${w.categories} / ${w.expectedCategories.toFixed(1)}` : ""}
                </td>
              )}
              <td className="num">{w.made}</td>
              <td className="num">{w.realized[scoring] != null ? unitsLabel(w.realized[scoring], scoring) : ""}</td>
              <td className="num">{w.rank != null ? `${ordinal(w.rank)}${w.teams ? ` of ${w.teams}` : ""}` : ""}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------- the cards
function noteFace(p: ProgressPayload, at: number | null, setAt: (i: number) => void, onChange: (id: string) => void): Face {
  const notes = p.notes;
  if (!notes.length) {
    return {
      body: (
        <p className="muted small">
          No Monday note yet. The master writes one each Monday in <code>data/autopilot/notes</code>: what is working, what is not, the decision and the action items.
        </p>
      ),
    };
  }
  const i = at == null ? notes.length - 1 : Math.min(at, notes.length - 1);
  const n = notes[i];
  return {
    note: `Monday ${n.monday}${n.week != null ? ` · week ${n.week}` : ""}`,
    action: (
      <span className="pg-steps">
        <button className="small" disabled={i === 0} onClick={() => setAt(i - 1)} aria-label="The note before" title="the note before">
          ‹
        </button>
        <button className="small" disabled={i === notes.length - 1} onClick={() => setAt(i + 1)} aria-label="The note after" title="the note after">
          ›
        </button>
      </span>
    ),
    body: <NoteCard p={p} i={i} onChange={onChange} />,
  };
}

function NoteCard({ p, i, onChange }: { p: ProgressPayload; i: number; onChange: (id: string) => void }) {
  const n = p.notes[i];
  const started = p.knobs.changes.filter((c) => c.monday === n.monday);
  return (
    <div className="pg-note">
      <section>
        <div className="row">
          <span className="k">Action items</span>
          <span className="dim small">handled in the session</span>
        </div>
        {n.actions.length ? (
          <ol>
            {n.actions.map((a, k) => (
              <li key={k}>{a}</li>
            ))}
          </ol>
        ) : (
          <p className="dim small">None.</p>
        )}
      </section>
      {(
        [
          ["What is working", n.working],
          ["What is not", n.not_working],
          ["Decision", n.decision],
        ] as const
      ).map(([title, text]) => (
        <section key={title}>
          <span className="k">{title}</span>
          <p className={text ? undefined : "dim small"}>{text ?? "Not written."}</p>
        </section>
      ))}
      <p className="dim small">
        {started.map((c) => (
          <Fragment key={c.id}>
            <button className="link" onClick={() => onChange(c.id)}>
              {c.id}'s sheet
            </button>
            {" · "}
          </Fragment>
        ))}
        {n.posted ? `posted on the tracker ${n.posted}` : "not posted on the tracker yet"}
        {n.scored_week != null ? ` · looks back on week ${n.scored_week}` : ""}
      </p>
    </div>
  );
}

function KnobsCard({ p, onOpen }: { p: ProgressPayload; onOpen: (id: string) => void }) {
  const k = p.knobs;
  const pub = publicLeagues(p).length;
  const inForce = Object.entries(k.in_force) as [KnobName, unknown][];
  return (
    <div className="pg-knobs">
      {k.changes.length ? (
        <table className="season-table">
          <thead>
            <tr>
              <th>Mon</th>
              <th>Knob</th>
              <th title="the leagues that took the change (A), of the public leagues; the rest kept the setting (B)">Half</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {k.changes.map((c) => {
              const v = verdictLabel(c);
              return (
                <tr key={c.id} className="pick" onClick={() => onOpen(c.id)} title={`${c.monday}: open its sheet`}>
                  <td>{c.week != null ? `wk ${c.week}` : c.monday}</td>
                  <td>
                    <b>{c.id}</b> {changeWhat(c)}
                  </td>
                  <td>
                    A · {c.leagues.length}
                    {pub ? ` of ${pub}` : ""}
                  </td>
                  <td>
                    <span className={v.tone}>{v.text}</span>
                    {v.figure && <div className="dim small">{v.figure}</div>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p className="muted small">No knob change yet.</p>
      )}
      <p className="small">
        <span className="k">In force</span>{" "}
        {inForce.length ? inForce.map(([name, v]) => `${KNOB_SHORT[name] ?? name} ${knobValue(v)}`).join(" · ") : <span className="dim">{p.sources.knob_file ? "none set" : "no knob file yet: the defaults of docs/AUTOPILOT.md"}</span>}
      </p>
      {Object.entries(k.leagues).map(([league, set]) => (
        <p key={league} className="small dim">
          league {league}: {(Object.entries(set) as [KnobName, unknown][]).map(([name, v]) => `${KNOB_SHORT[name] ?? name} ${knobValue(v)}`).join(" · ")}
          {k.frozen[league]?.length ? ` · frozen by the user: ${k.frozen[league].map((x) => KNOB_SHORT[x] ?? x).join(", ")}` : ""}
        </p>
      ))}
      {Object.entries(k.frozen)
        .filter(([league, names]) => !k.leagues[league] && names.length)
        .map(([league, names]) => (
          <p key={league} className="small dim">
            league {league}: frozen by the user: {names.map((x) => KNOB_SHORT[x] ?? x).join(", ")}
          </p>
        ))}
      <p className="dim small">A row opens its sheet. The knobs are changed by the master in the session; the user can override any of them.</p>
      {p.problems.length > 0 && (
        <details className="small">
          <summary className="bad">
            {p.problems.length} problem{p.problems.length === 1 ? "" : "s"} reading the files
          </summary>
          <ul>
            {p.problems.map((x, i) => (
              <li key={i} className="dim">
                {x}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function LeagueCard({ p, scope, onScope, onOpenLeague }: { p: ProgressPayload; scope: string; onScope: (s: string) => void; onOpenLeague: (league: string) => void }) {
  const l = p.leagues.find((x) => x.league === scope);
  if (scope === POOLED || !l) {
    const rows = p.leagues.filter((x) => x.weeks.length > 0);
    return (
      <div className="pg-league">
        <p className="muted small">Pick a league, here or in the scope chips, for its weeks against expectation and its sentences.</p>
        <div className="chips">
          {rows.map((x) => {
            const s = rangeSum(scopeWeeks(p, x.league));
            const gap = s.won - s.expected;
            return (
              <button key={x.league} className="chip" onClick={() => onScope(x.league)}>
                <span>
                  {x.league}
                  {x.public ? "" : " · private"}
                </span>
                <span className={Math.abs(gap) < 0.05 ? "dim" : gap > 0 ? "good" : "bad"}>
                  {recordLabel(s.record)} · {signed1(gap)}
                </span>
              </button>
            );
          })}
        </div>
        {p.leagues.length > rows.length && (
          <p className="dim small">
            {p.leagues.length - rows.length} league{p.leagues.length - rows.length === 1 ? "" : "s"} not scored yet.
          </p>
        )}
      </div>
    );
  }
  const t = l.to_date;
  const s = rangeSum(scopeWeeks(p, l.league));
  const say = scopeSentences(p.sentences, l.league);
  return (
    <div className="pg-league">
      <div className="pg-tiles">
        <Tile k="record" v={t?.record ?? recordLabel(s.record)} title="the season's record, a tie as half">
          {s.expected.toFixed(1)} expected over {s.projected} projected week{s.projected === 1 ? "" : "s"}
        </Tile>
        <Tile k="place" v={s.rankLast == null ? "—" : ordinal(s.rankLast)} title="the place after the last week scored">
          {s.rankLast == null ? "no standing read" : t?.standing ? `of ${t.standing.teams}${t.standing.record ? ` · ${t.standing.record}` : ""}` : `after week ${p.last_recorded ?? "?"}`}
        </Tile>
      </div>
      {t && (
        <p className="small">
          {t.moves.made} move{t.moves.made === 1 ? "" : "s"}: {t.moves.as_recommended} as recommended, {t.moves.differently} differently, {t.moves.not_recommended} not recommended
          {t.moves.no_entry ? `, ${t.moves.no_entry} with no solve logged` : ""}.
        </p>
      )}
      {say.length > 0 ? <Sentences say={say} /> : <p className="dim small">Nothing to say beyond the numbers: within a game of its expectation.</p>}
      <button className="link" onClick={() => onOpenLeague(l.league)}>
        open its league page
      </button>
    </div>
  );
}

// ---------------------------------------------------------------- the knob change sheet
function KnobSheet({ p, c, onClose, onStep }: { p: ProgressPayload; c: KnobChange; onClose: () => void; onStep: (delta: number) => void }) {
  const ab = c.ab;
  const why = whyTried(p, c);
  const pub = publicLeagues(p);
  const b = pub.filter((x) => !c.leagues.includes(x));
  const v = verdictLabel(c);
  const series = ab?.series ?? [];
  const units = (["categories", "points"] as Scoring[]).filter((s) => ab && (ab.a.moves[s] || ab.b.moves[s]));
  const share = (half: "a" | "b", s: Scoring) => {
    const m = ab?.[half].moves[s];
    return m ? `${gainLabel(m.realized, 1)} of ${gainLabel(m.projected, 1)}${m.share != null ? ` · ${pct(m.share)}` : ""}` : "—";
  };
  const fig = (x: number | null | undefined, digits = 1) => (x == null ? "—" : gainLabel(x, digits));
  // The sheet takes the focus, so its arrows step the changes rather than a chart behind it.
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.focus(), [c.id]);
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div ref={box} tabIndex={-1} className="sheet pg-sheet" role="dialog" aria-label={`Knob change ${c.id}`} onClick={(e) => e.stopPropagation()}>
        <header>
          <h2>
            {c.id} · {KNOB_TITLE[c.knob] ?? c.knob}, {knobValue(c.from)} → {knobValue(c.to)}
          </h2>
          <span className="grow" />
          <button className="icon" aria-label="Close" onClick={onClose}>
            <Close />
          </button>
        </header>
        <div className="pg-sheet-body">
          <p className="muted">
            started Monday {c.monday}
            {c.week != null ? `, week ${c.week},` : ""} in {c.leagues.length} league{c.leagues.length === 1 ? "" : "s"} (A); {b.length} kept the setting (B)
            {judgedAfter(c) != null ? ` · judged after week ${judgedAfter(c)}` : ""}
          </p>
          <p>
            <span className={v.tone}>{c.verdict ?? "pending"}</span>
            {c.judged_on ? ` · judged ${c.judged_on}` : ""}
            {c.rolled_out ? ` · rolled out to every league ${c.rolled_out}` : ""}
            {v.figure ? ` · ${v.figure}` : ""}
          </p>
          {series.some((x) => x.a != null || x.b != null) ? (
            <>
              <div className="k">Wins above expected, a week, per league · A against B</div>
              <ProgressChart
                weeks={series.map((x) => x.week)}
                series={[
                  { key: "a", label: "A · took the change", tone: "actual", values: series.map((x) => x.a) },
                  { key: "b", label: "B · kept the setting", tone: "other", values: series.map((x) => x.b) },
                ]}
                markers={c.week != null ? [{ week: c.week, id: `${c.id} starts`, title: `${c.id} starts, Monday ${c.monday}` }] : []}
                reference={{ value: 0, label: "expected" }}
                fmt={(x) => gainLabel(x, 1)}
                label={`Wins above expected a league, A against B, around ${c.id}`}
                width={560}
                height={190}
                tip={(i) => (
                  <>
                    <div className="muted">week {series[i].week}</div>
                    <div>A {fig(series[i].a, 2)}</div>
                    <div className="muted">B {fig(series[i].b, 2)}</div>
                  </>
                )}
              />
            </>
          ) : (
            <p className="dim small">No week scored around it yet: the chart draws once a week from two before it is scored.</p>
          )}
          {ab && (
            <table className="season-table pg-ab">
              <thead>
                <tr>
                  <th>{ab.window ? `wk ${ab.window[0]}${ab.window[1] !== ab.window[0] ? `–${ab.window[1]}` : ""}` : "not scored yet"}</th>
                  <th className="num">A</th>
                  <th className="num">B</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td title="over the weeks it is judged on, the mean over each half's leagues">Wins above expected a league</td>
                  <td className="num">{fig(ab.a.wins_above)}</td>
                  <td className="num">{fig(ab.b.wins_above)}</td>
                </tr>
                {units.map((s) => (
                  <tr key={s}>
                    <td title="the scored moves over a complete week, realized against projected">Moves' realized gain, {UNITS[s]}</td>
                    <td className="num">{share("a", s)}</td>
                    <td className="num">{share("b", s)}</td>
                  </tr>
                ))}
                <tr>
                  <td>Moves a league a week</td>
                  <td className="num">{ab.a.moves_a_week?.toFixed(1) ?? "—"}</td>
                  <td className="num">{ab.b.moves_a_week?.toFixed(1) ?? "—"}</td>
                </tr>
                <tr>
                  <td title="places climbed from the week before it, summed over the half's leagues">Standing moved</td>
                  <td className="num">{gainLabel(ab.a.standing_climbed, 0)}</td>
                  <td className="num">{gainLabel(ab.b.standing_climbed, 0)}</td>
                </tr>
                <tr>
                  <td title="the matchup odds' Brier score: 0.25 is a coin flip, lower is better">Brier</td>
                  <td className="num">{ab.a.brier?.toFixed(2) ?? "—"}</td>
                  <td className="num">{ab.b.brier?.toFixed(2) ?? "—"}</td>
                </tr>
              </tbody>
            </table>
          )}
          {why && (
            <>
              <div className="k">Why it was tried · from {why.from}</div>
              <blockquote className="pg-why">{why.text}</blockquote>
            </>
          )}
          <p className="small">
            <b>Rule:</b> {CHANGE_RULE} Leagues in A: {c.leagues.length ? c.leagues.join(", ") : "none"}.
          </p>
          <p className="dim small">
            decided by {c.source ?? "—"}
            {c.decided_at ? `, ${c.decided_at.slice(0, 16).replace("T", " ")}` : ""}
            {c.reason && why?.from !== "the knob file" ? ` · its reason: ${c.reason}` : ""}
          </p>
        </div>
        <footer className="row dim small">
          <span>
            <kbd>←</kbd> <kbd>→</kbd> other changes
            {p.knobs.changes.length > 1 && (
              <>
                {" "}
                <button className="small" onClick={() => onStep(-1)} aria-label="The change before">
                  ‹
                </button>{" "}
                <button className="small" onClick={() => onStep(1)} aria-label="The change after">
                  ›
                </button>
              </>
            )}
          </span>
          <span>
            <kbd>Esc</kbd> close
          </span>
        </footer>
      </div>
    </div>
  );
}

function ProgressFooter({ p }: { p: ProgressPayload }) {
  const m = p.sources.moves;
  return (
    <footer className="footer season-foot pg-foot">
      <span title="the moves made and how each compares with the solve logged before it">
        decision log · {m.made} move{m.made === 1 ? "" : "s"}, {m.as_recommended} as recommended, {m.differently} differently, {m.not_recommended} not recommended
      </span>
      <span>
        {p.sources.recorded} of {p.sources.leagues} leagues scored
      </span>
      <span>{p.sources.knob_file ? "knob file read" : "no knob file"}</span>
      <span>
        {p.sources.notes} note{p.sources.notes === 1 ? "" : "s"}
      </span>
      {p.skipped.length > 0 && <span className="bad" title={p.skipped.map((x) => `${x.league}: ${x.reason}`).join("\n")}>{p.skipped.length} not read</span>}
      <span className="grow" />
      <span>
        <kbd>?</kbd> keys · <kbd>t</kbd> view · <kbd>[</kbd> view drawer · <kbd>1</kbd>–<kbd>{PROGRESS_CARDS.length}</kbd> cards · <kbd>]</kbd> panel
      </span>
      <span>as of {p.today}</span>
      <span className="accent">reads only · nothing here writes</span>
    </footer>
  );
}
