import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { flushSync } from "react-dom";
import {
  api,
  CAT_LABEL,
  type AvailableRow,
  type Cat,
  type HeldMove,
  type HeldRef,
  type MoveCategory,
  type MoveHorizon,
  type MoveRef,
  type MovesPayload,
  type ProjectionSystem,
  type ProjectionSystemInfo,
  type RecordedWeek,
  type RosterRow,
  type SeasonMatchup,
  type SeasonPlayer,
  type SeasonView,
  type WeekPlan,
  type WeekProjection,
} from "../api";
import {
  addsNote,
  ageLabel,
  availabilityLabel,
  bestMove,
  catValue,
  changeLabel,
  comebackText,
  dayLabel,
  DEFAULT_AVAILABLE_SORT,
  filterAvailable,
  FLAG_SIGNAL_NAME,
  flagCounts,
  addBasis,
  basisPhrase,
  flagged,
  flagInputsNote,
  flagLevels,
  flagOf,
  flagSignals,
  flagTag,
  flagTitle,
  forText,
  gainLabel,
  gainTone,
  guardSteps,
  HORIZON_LABEL,
  horizonGames,
  isRefreshing,
  isStale,
  keepLine,
  keepPhrase,
  keepRuleNote,
  keptPlayers,
  keptWhy,
  MOVE_HORIZON,
  NO_FILTER,
  oddsLabel,
  oddsTone,
  openingDrop,
  roomNote,
  pctLabel,
  planNote,
  planRosText,
  planShortLine,
  planStepRosTitle,
  playersById,
  projectedTotals,
  POSITIONS,
  readWatch,
  recordLabel,
  refreshNote,
  rosHeadTitle,
  rosLabel,
  rosTitle,
  rosTone,
  scoreLabel,
  seasonGuardLine,
  seasonGuardMoves,
  shownPlan,
  shownWeekPlans,
  weekPlansTitle,
  sortAvailable,
  stashText,
  statusTitle,
  statusTone,
  stepDay,
  TEXT_KEYS,
  waiversNote,
  weekBackLine,
  weekDates,
  weekLabel,
  weekPlanHead,
  weekResult,
  weekTone,
  writeWatch,
  type AvailableFilter,
  type AvailableSort,
  type AvailableSortKey,
  type Horizon,
  type PositionFilter,
} from "../season";
import { DRAWER_WIDTH, isShown, SEASON_CARDS, SEASON_SHEET, SEASON_VIEWS, seasonKeys, stepHighlight, type DrawerState, type Half, type SeasonCardId, type SeasonViewId } from "../keys";
import { useDrawer, useHotkeys, useViews } from "../useKeys";
import { FlagBreakdown, FlagInfo, FlagTag } from "./FlagExplain";
import { StatusDot, StatusSheet, useSeasonStatus } from "./StatusLight";
import Halves, { type Face } from "./Halves";
import KeySheet from "./KeySheet";
import LineupView from "./LineupView";
import MatchupView from "./MatchupView";
import OutlookView from "./OutlookView";
import Rail from "./Rail";
import QueueCard from "./QueueCard";
import Scorecard from "./Scorecard";
import { SEASON_ICONS, VIEW_ICONS } from "./icons";
import Strategy from "./Strategy";
import Trade from "./Trade";
import ViewDrawer from "./ViewDrawer";
import { useNow } from "./YahooSync";

const PANEL_KEY = "pickandroll.season.drawer";
const VIEW_KEY = "pickandroll.season.view";
/** Every card but the Waivers board can sit in a half of the panel. */
const isPanelCard = (v: unknown): v is SeasonCardId => typeof v === "string" && v !== "waivers" && SEASON_CARDS.some((c) => c.id === v);
const DEFAULT_PANEL: DrawerState<SeasonCardId> = {
  top: "moves",
  bottom: "flags",
  collapsed: false,
  split: 0.6,
  last: { top: "moves", bottom: "flags" },
  width: DRAWER_WIDTH,
};

const REFRESH_TITLE = "Read the league's public Yahoo pages again, about 20 s (r)";
const KEEP_RULE_TITLE = "the keep rule (#124): a net-positive player better than the best add over the rest of the season, who returns this season, is never a drop";

/** A league in season (#92), in the draft view's shape (#109): a view where the board stands
 * (the available players, or this week's matchup, #116) picked from a drawer at its left edge,
 * a two-half panel of cards (the moves, a trade, the flags, my roster, the league and the
 * strategy, #110) and the draft's rail and keys. Yahoo's own columns, the weekly projection's
 * (#93) and the moves' gains (#94). */
export default function SeasonScreen({
  league,
  view,
  onBack,
  onProgress,
}: {
  league: string;
  /** The view to open on (the landing table's Lineup, #191), set once on mount; else the saved one. */
  view?: SeasonViewId;
  onBack: () => void;
  onProgress: () => void;
}) {
  const queryClient = useQueryClient();
  const season = useQuery({
    queryKey: ["season", league],
    queryFn: () => api.season(league),
    refetchInterval: (q) => (isRefreshing(q.state.data) ? 1000 : 60_000),
  });
  const refresh = useMutation({
    mutationFn: () => api.refreshSeason(league),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["season", league] });
      void queryClient.invalidateQueries({ queryKey: ["seasons"] });
    },
  });
  const now = useNow(30_000);
  const [watch, setWatch] = useShowWatch();
  const s = season.data;
  const running = isRefreshing(s) || refresh.isPending;
  const [chosen, setSystem] = useState<ProjectionSystem | null>(null);
  const [horizon, setHorizon] = useState<Horizon>("next3");
  const [picked, setPicked] = useState<MoveKey | null>(null);
  // The panel's two halves, the rail and the keys (#109). Moves and Trade (#96) take each
  // other's half by t and m; a picked move shows in the Moves card.
  const panel = useDrawer(PANEL_KEY, isPanelCard, DEFAULT_PANEL, DEFAULT_PANEL.last);
  // The view where the board stands and the drawer that picks it (#116), kept like the panel.
  const views = useViews(VIEW_KEY);
  const { setView } = views;
  const askedView = useRef(view);
  useEffect(() => {
    if (askedView.current) setView(askedView.current);
  }, [setView]);
  const [leagueTab, setLeagueTab] = useState<LeagueTab>("standings");
  const [sheetOpen, setSheetOpen] = useState(false);
  // The freshness light's sheet (#153).
  const status = useSeasonStatus();
  const [statusOpen, setStatusOpen] = useState(false);
  const closeStatus = useCallback(() => setStatusOpen(false), []);
  const [highlight, setHighlight] = useState<number | null>(null);
  // One flag breakdown open at a time (#113), under a Flags card row or a Waivers row: opening
  // another closes the first.
  const [breakdown, setBreakdown] = useState<FlagOpen | null>(null);
  const toggleBreakdown = useCallback(
    (where: FlagOpen["where"], id: number) => setBreakdown((b) => (b && b.where === where && b.id === id ? null : { where, id })),
    [],
  );
  const visibleRows = useRef<number[]>([]);
  const setVisibleRows = useCallback((ids: number[]) => {
    visibleRows.current = ids;
  }, []);
  const moveHighlight = useCallback((delta: number) => setHighlight((h) => stepHighlight(visibleRows.current, h, delta)), []);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const boardRef = useRef<HTMLDivElement | null>(null);
  const { replaceCard } = panel;
  const show = (card: "moves" | "trade") => replaceCard(card === "trade" ? "moves" : "trade", card);
  const pick = (m: MoveKey | null) => {
    setPicked(m);
    if (m) {
      setHighlight(m.add);
      replaceCard("trade", "moves");
    }
  };
  // 1 Waivers shows the Waivers view; there it gives the board the full width, and brings the
  // panel back.
  const openCard = (id: SeasonCardId, half: Half) => {
    if (id !== "waivers") return panel.openCard(id, half);
    if (views.view !== "waivers") views.setView("waivers");
    else panel.toggleDrawer();
    boardRef.current?.scrollIntoView({ block: "nearest" });
  };
  const system = chosen ?? s?.week_projection.default ?? "bbm";
  const moves = useQuery({
    queryKey: ["moves", league, system, s?.updated_at],
    queryFn: () => api.moves(league, system),
    enabled: Boolean(s?.has_snapshot && s.my_team),
    // A new snapshot keeps the last gains up while its own are valued; another system's never
    // stand in for this one's.
    placeholderData: (prev, prevQuery) => (prevQuery?.queryKey[2] === system ? prev : undefined),
    refetchInterval: 60_000,
    retry: false,
  });
  const mh = MOVE_HORIZON[horizon];
  const openMove = (id: number) => pick({ add: id, drop: openingDrop(moves.data?.candidates[String(id)], mh) });
  // A new read or a new solve moves the light.
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: ["status"] });
  }, [queryClient, s?.updated_at, moves.dataUpdatedAt]);
  // The keep rule's count opens the Strategy card, where its kept players are (#153).
  const showStrategy = () => {
    if (!isShown(panel.drawer, "strategy")) openCard("strategy", "bottom");
  };
  useHotkeys(
    seasonKeys({
      view: views.view,
      setView: views.setView,
      toggleViews: views.toggleViews,
      openCard,
      toggleDrawer: panel.toggleDrawer,
      swapHalves: panel.swapHalves,
      collapse: panel.collapseDrawer,
      closeBreakdown: () => {
        if (!breakdown || (breakdown.where === "flags" && !isShown(panel.drawer, "flags"))) return false;
        setBreakdown(null);
        return true;
      },
      closeMove: () => {
        if (!picked || !isShown(panel.drawer, "moves")) return false;
        setPicked(null);
        return true;
      },
      show,
      focusSearch: () => {
        // The board is hidden in another view: show it before the focus.
        flushSync(() => views.setView("waivers"));
        searchRef.current?.focus();
        searchRef.current?.select();
      },
      moveHighlight,
      highlight,
      openMove,
      refresh: s?.public && !running ? () => refresh.mutate() : null,
      progress: onProgress,
      sheetOpen,
      setSheetOpen,
    }),
  );
  const face = (id: SeasonCardId): Face => {
    if (!s) return { body: null };
    switch (id) {
      case "moves":
        return {
          title: picked ? "MOVE" : "MOVES",
          note: movesNote(moves.data, s),
          action: picked ? (
            <button className="link" onClick={() => setPicked(null)} title="Back to the recommended moves (Esc)">
              recommended
            </button>
          ) : (
            <button className="link" onClick={() => show("trade")} title="Evaluate a trade with another team: both sides before and after (t)">
              trade
            </button>
          ),
          body: picked ? <MoveDrawer league={league} s={s} system={system} m={moves.data} picked={picked} onPick={pick} /> : <Moves q={moves} s={s} onPick={pick} />,
        };
      case "trade":
        return {
          note: moves.data?.system.label,
          action: (
            <button className="link" onClick={() => show("moves")} title="Back to the recommended moves (m)">
              moves
            </button>
          ),
          // Kept mounted while off show (Halves' keep), so a proposal survives a look at the moves.
          body: <Trade league={league} s={s} system={system} />,
        };
      case "flags":
        return {
          note: flagCount(s),
          action: <FlagInfo cfg={s.flag_config} inputs={s.flag_inputs} now={now} align="right" label="how flags work" />,
          body: (
            <Flags
              s={s}
              m={moves.data}
              mh={mh}
              now={now}
              onPick={pick}
              open={breakdown?.where === "flags" ? breakdown.id : null}
              onToggle={(id) => toggleBreakdown("flags", id)}
              watch={watch}
              setWatch={setWatch}
            />
          ),
        };
      case "roster":
        return { note: s.my_team?.name, body: <Roster rows={s.roster} w={s.week_projection} /> };
      case "league":
        return {
          action: (
            <span className="seg small" role="tablist" aria-label="The league">
              {LEAGUE_TABS.map(([tab, label]) => (
                <button key={tab} role="tab" aria-selected={leagueTab === tab} className={leagueTab === tab ? "on" : undefined} onClick={() => setLeagueTab(tab)}>
                  {label}
                </button>
              ))}
            </span>
          ),
          body: leagueTab === "matchups" ? <Pairings s={s} now={now} /> : <League s={s} />,
        };
      case "strategy":
        return { note: moves.data?.system.label, body: <Strategy league={league} s={s} system={system} onPick={pick} /> };
      case "scorecard":
        return { note: s.public ? undefined : "suggestions only", body: <Scorecard league={league} /> };
      case "queue":
        return { note: s.public ? undefined : "suggestions only", body: <QueueCard league={league} s={s} /> };
      default:
        return { body: null };
    }
  };
  return (
    <main className="shell">
      <header className="topbar season-top">
        <div className="wordmark">
          PICK<span>&amp;</span>ROLL
        </div>
        <span className="muted title">
          {s?.name ?? `League ${league}`}
          {s?.name && !s.name.includes(league) ? ` · ${league}` : ""}
          {s && ` · ${s.scoring === "points" ? "H2H points" : "H2H categories"} · ${s.num_teams} teams`}
        </span>
        <span className="grow" />
        {s?.has_snapshot && (
          <>
            <span className="k" title={s.calendar_estimated ? "the week's dates are estimated: Yahoo's calendar was not read" : undefined}>
              {weekLabel(s)}
              {s.current_week && ` · ${weekDates(s.current_week)}`}
            </span>
            {s.my_team && <span className="pill" title={`${s.my_team.name}, my team`}>{recordLabel(s.my_team)}</span>}
            {s.opponent && <span>vs {s.opponent.name}</span>}
          </>
        )}
        <StatusDot p={status.data} league={league} onOpen={() => setStatusOpen(true)} />
        {s && (
          <span className={running ? "accent" : isStale(s.updated_at, now) ? "bad" : "muted"} title={s.updated_at ?? undefined}>
            {refreshNote(s.refresh) || (s.has_snapshot ? `read ${ageLabel(s.updated_at, now)}` : "not read yet")}
          </span>
        )}
        {s?.public && (
          <button className="small" disabled={running} onClick={() => refresh.mutate()} title={REFRESH_TITLE}>
            {running ? "Refreshing…" : "Refresh"}
          </button>
        )}
        <button className="link" onClick={onProgress} title="the hill-climb over the season, every league (p)">
          progress
        </button>
        <button className="link" onClick={onBack}>
          all leagues
        </button>
      </header>
      {season.error && <p className="error" style={{ padding: "0 24px" }}>{season.error.message}</p>}
      {refresh.isError && <p className="error" style={{ padding: "0 24px" }}>{refresh.error.message}</p>}
      {s && !s.has_snapshot && (
        <p className="muted" style={{ padding: "12px 24px" }}>
          Nothing read for this league yet.{" "}
          {s.public ? "Refresh reads its public Yahoo pages." : "It is private: open its team, players and matchup pages in Chrome with the extension."}
        </p>
      )}
      {s?.has_snapshot && (
        <>
          <div className="main season">
            {/* One box on a wide window (display: contents), the scrolling column beside the rail on a narrow one. */}
            <div className="season-body">
              <ViewDrawer views={SEASON_VIEWS} icons={VIEW_ICONS} view={views.view} shown={views.shown} onView={views.setView} onToggle={views.toggleViews} />
              {views.view === "matchup" && (
                <div className="board-col view-col">
                  <MatchupView league={league} s={s} system={system} setSystem={setSystem} now={now} />
                </div>
              )}
              {views.view === "season" && (
                <div className="board-col view-col">
                  <OutlookView league={league} s={s} system={system} setSystem={setSystem} />
                </div>
              )}
              {views.view === "lineup" && (
                <div className="board-col view-col">
                  <LineupView league={league} s={s} system={system} setSystem={setSystem} />
                </div>
              )}
              {/* Kept mounted in another view, so its sort, filters and highlight stay. */}
              <div className="board-col" ref={boardRef} hidden={views.view !== "waivers"}>
                <Waivers
                  s={s}
                  system={system}
                  setSystem={setSystem}
                  horizon={horizon}
                  setHorizon={setHorizon}
                  moves={moves}
                  picked={picked}
                  onPick={pick}
                  highlight={highlight}
                  setVisibleRows={setVisibleRows}
                  searchRef={searchRef}
                  flagOpen={breakdown?.where === "waivers" ? breakdown.id : null}
                  onToggleFlag={(id) => toggleBreakdown("waivers", id)}
                  onKeep={showStrategy}
                  now={now}
                  watch={watch}
                />
              </div>
              <Halves d={panel} cards={SEASON_CARDS} face={face} keep={["trade"]} />
            </div>
            <Rail
              cards={SEASON_CARDS}
              icons={SEASON_ICONS}
              on={(id) => (id === "waivers" ? views.view === "waivers" && !panel.drawerOpen : isShown(panel.drawer, id))}
              onOpen={openCard}
              onSheet={() => setSheetOpen(true)}
              open={panel.drawerOpen}
              onToggle={panel.toggleDrawer}
              noun="panel"
            />
          </div>
          <SeasonFooter s={s} now={now} />
        </>
      )}
      <KeySheet sheet={SEASON_SHEET} open={sheetOpen} onClose={() => setSheetOpen(false)} />
      {statusOpen && status.data && (
        <StatusSheet
          p={status.data}
          league={league}
          onClose={closeStatus}
          refresh={s?.public ? { run: () => refresh.mutate(), running, title: REFRESH_TITLE } : undefined}
        />
      )}
    </main>
  );
}

/** The "show under watch" toggle (#186), kept per browser; it lasts the page when the browser
 * keeps nothing. */
function useShowWatch(): [boolean, (on: boolean) => void] {
  const store = () => {
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  };
  const [on, setOn] = useState(() => readWatch(store()));
  const set = useCallback((v: boolean) => {
    setOn(v);
    writeWatch(store(), v);
  }, []);
  return [on, set];
}

/** Where a flag breakdown is open: under the Flags card's row or the Waivers row of a player. */
interface FlagOpen {
  where: "flags" | "waivers";
  id: number;
}

function Status({ player }: { player: SeasonPlayer }) {
  const tone = statusTone(player);
  if (!tone) return null;
  return (
    <span className={`tag ${tone}`} title={statusTitle(player)}>
      {player.status}
    </span>
  );
}

// ---------------------------------------------------------------- waivers
const OWN_COLUMNS: { key: AvailableSortKey; label: string; num?: boolean; title?: string }[] = [
  { key: "name", label: "Player" },
  { key: "nba_team", label: "Team" },
  { key: "positions", label: "Pos" },
  { key: "availability", label: "Status", title: "a free agent, or on waivers until the day shown" },
  {
    key: "games",
    label: "G",
    num: true,
    title: "games he plays in the rest of this week, from today: ESPN's schedule less the out rule (O, INJ, OFS, SUSP, NA), or a Basketball Monster weekly export when one covers the week",
  },
  { key: "games_next3", label: "G 3wk", num: true, title: "games he plays in the three weeks after this one" },
];
const TREND_COLUMNS: { key: AvailableSortKey; label: string; title: string }[] = [
  { key: "pct_rostered", label: "% Ros", title: "percent of Yahoo leagues that roster him" },
  { key: "pct_rostered_change", label: "+/−", title: "the day's change in percent rostered" },
  { key: "pct_started", label: "% Start", title: "percent of Yahoo leagues that start him" },
  { key: "adds", label: "Adds", title: "adds across Yahoo today" },
  { key: "drops", label: "Drops", title: "drops across Yahoo today" },
];
const SYSTEM_SHORT: Record<ProjectionSystem, string> = { bbm: "BBM", yahoo: "Yahoo" };
/** A move horizon's column: the rest of this week, the three weeks after it. */
const GAIN_SHORT: Record<MoveHorizon, string> = { week: "+1wk", three: "+3wk" };
const GAIN_KEY: Record<MoveHorizon, AvailableSortKey> = { week: "gain_week", three: "gain_three" };

/** The move a drawer shows: an add and his drop (null: an open spot). */
type MoveKey = Pick<MoveRef, "add" | "drop">;

/** A move horizon as the payload names it: "the rest of week 1 against …", "weeks 2-4 against
 * the field". */
function horizonName(m: MovesPayload | undefined, h: MoveHorizon): string {
  const label = m?.horizons[h].label ?? (h === "week" ? "rest of this week" : "three weeks after this one");
  return h === "week" || !m ? `the ${label}` : label;
}

const cap = (x: string) => x.charAt(0).toUpperCase() + x.slice(1);

/** A player's name by Yahoo id; a drop of null is an open spot. */
type Namer = (id: number | null) => string;

function useNamer(s: SeasonView): Namer {
  const byId = useMemo(() => playersById(s), [s]);
  return (id) => (id == null ? "an open spot" : (byId.get(id)?.name ?? `player ${id}`));
}

function Waivers({
  s,
  system,
  setSystem,
  horizon,
  setHorizon,
  moves,
  picked,
  onPick,
  highlight,
  setVisibleRows,
  searchRef,
  flagOpen,
  onToggleFlag,
  onKeep,
  now,
  watch,
}: {
  s: SeasonView;
  system: ProjectionSystem;
  setSystem: (x: ProjectionSystem) => void;
  horizon: Horizon;
  setHorizon: (h: Horizon) => void;
  moves: UseQueryResult<MovesPayload>;
  picked: MoveKey | null;
  onPick: (m: MoveKey) => void;
  /** The keyboard's row (j, k, Enter). */
  highlight: number | null;
  setVisibleRows: (ids: number[]) => void;
  searchRef: RefObject<HTMLInputElement | null>;
  /** The player whose flag breakdown is open under his row (#113). */
  flagOpen: number | null;
  onToggleFlag: (id: number) => void;
  /** Opens the Strategy card, at the keep rule's players. */
  onKeep: () => void;
  now: number;
  /** The "show under watch" toggle (#186): the players under watch get their dimmed tag. */
  watch: boolean;
}) {
  const w = s.week_projection;
  const cats = s.settings.cats;
  const points = s.settings.points;
  const [filter, setFilter] = useState<AvailableFilter>(NO_FILTER);
  const [sort, setSort] = useState<AvailableSort>(DEFAULT_AVAILABLE_SORT);
  const other: ProjectionSystem = system === "bbm" ? "yahoo" : "bbm";
  const m = moves.data;
  const mh = MOVE_HORIZON[horizon];
  const minGain = m?.search.min_gain ?? 0;
  const name = useNamer(s);
  const keep = keepLine(m?.keep_rule, name);
  const kept = keepPhrase(m?.keep_rule);
  const rows = s.available;
  const games = (r: AvailableRow, h: Horizon) => rowGames(w, r, h);
  const totals = useMemo(() => {
    const out = new Map<number, { mine: Totals; theirs: Totals }>();
    for (const r of rows) {
      const p = w.players[String(r.player.yahoo_id)];
      const g = rowGames(w, r, horizon);
      out.set(r.player.yahoo_id, { mine: projectedTotals(p?.[system], g, cats, points), theirs: projectedTotals(p?.[other], g, cats, points) });
    }
    return out;
  }, [rows, w, system, other, horizon, cats, points]);
  const shown = useMemo(() => {
    const extra = (r: AvailableRow, key: AvailableSortKey): number | null | undefined => {
      if (key === "games") return rowGames(w, r, "week");
      if (key === "games_next3") return rowGames(w, r, "next3");
      const cand = m?.candidates[String(r.player.yahoo_id)];
      if (key === "gain_week") return bestMove(cand, "week")?.gain ?? null;
      if (key === "gain_three") return bestMove(cand, "three")?.gain ?? null;
      if (key === "next_price") return bestMove(cand, mh)?.next_price ?? null;
      if (key === "ros") return bestMove(cand, mh)?.ros?.value ?? null;
      if (key === "flag") return flagOf(s, r.player.yahoo_id)?.score ?? null;
      if ((cats as string[]).includes(key)) {
        // Fewer turnovers first when sorting high to low.
        const v = totals.get(r.player.yahoo_id)?.mine?.[key as Cat];
        return v == null ? null : key === "tov" ? -v : v;
      }
      return undefined;
    };
    return sortAvailable(filterAvailable(rows, filter, (r) => rowGames(w, r, "week")), sort, extra);
  }, [rows, filter, sort, totals, w, cats, m, mh, s]);
  useEffect(() => {
    setVisibleRows(shown.map((r) => r.player.yahoo_id));
  }, [shown, setVisibleRows]);
  useEffect(() => {
    if (highlight !== null) document.querySelector(".season-board tr.hl")?.scrollIntoView({ block: "nearest" });
  }, [highlight]);
  const teams = useMemo(() => [...new Set(rows.map((r) => r.player.nba_team).filter((t): t is string => Boolean(t)))].sort(), [rows]);
  const set = (patch: Partial<AvailableFilter>) => setFilter((f) => ({ ...f, ...patch }));
  const click = (key: AvailableSortKey) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: TEXT_KEYS.includes(key) ? "asc" : "desc" }));
  const th = (key: AvailableSortKey, label: string, title?: string, num = true, extra?: ReactNode) => (
    <th key={key} className={`sortable${num ? " num" : ""}${sort.key === key ? " sorted" : ""}`} title={title} onClick={() => click(key)}>
      {label}
      {sort.key === key && <span className="arrow">{sort.dir === "asc" ? "▲" : "▼"}</span>}
      {extra}
    </th>
  );
  const columns = OWN_COLUMNS.length + 1 + 2 + 1 + 2 + cats.length + TREND_COLUMNS.length;
  const info = w.systems[system];
  const week = w.weeks[0];
  const gainTitle = (h: MoveHorizon) =>
    `the expected categories his best move adds over ${horizonName(m, h)}` +
    `${h === "week" ? ", the week so far included" : ", each week's odds averaged over the other teams"}; the move drops the player in For (${HORIZON_LABEL[horizon]}) or the best for this horizon` +
    (s.scoring === "points" ? " (a points league: matchups won)" : "");
  const movesNote = m
    ? `+1wk and +3wk: what his best move adds in expected categories; click a row for the move${m.unprojected ? ` · ${m.unprojected} with no line to value` : ""}`
    : null;
  // One phrase in the header, the rest in its "?" (#153).
  const note = waiversNote({
    label: info.label,
    players: info.players,
    file: info.file,
    asOf: info.as_of,
    horizon,
    other: SYSTEM_SHORT[other],
    shown: shown.length,
    total: rows.length,
    moves: movesNote,
  });
  const horizonTitle =
    horizon === "week"
      ? `${week ? `from ${week.from} to ${week.end}` : "this week"}: his per-game line times the games he plays, every game counted (whom he would sit is the move's question, #94)`
      : "the three weeks after this one, every game counted";
  return (
    <section className="board season-board" aria-label="Waivers">
      <header className="board-head">
        <h2>WAIVERS</h2>
        <input ref={searchRef} type="search" placeholder="Player or team  /" value={filter.search} onChange={(e) => set({ search: e.target.value })} aria-label="Search players" />
        <select value={filter.position} onChange={(e) => set({ position: e.target.value as PositionFilter })} aria-label="Position">
          <option value="">all positions</option>
          {POSITIONS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select value={filter.availability} onChange={(e) => set({ availability: e.target.value as AvailableFilter["availability"] })} aria-label="Free agents or waivers">
          <option value="">free agents and waivers</option>
          <option value="FA">free agents</option>
          <option value="W">waivers</option>
        </select>
        <select value={filter.nbaTeam} onChange={(e) => set({ nbaTeam: e.target.value })} aria-label="NBA team">
          <option value="">all teams</option>
          {teams.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select value={filter.minGames} onChange={(e) => set({ minGames: Number(e.target.value) })} aria-label="Games this week" title="Games he plays in the rest of this week">
          <option value={0}>any games</option>
          {[1, 2, 3, 4].map((n) => (
            <option key={n} value={n}>
              {n}+ games
            </option>
          ))}
        </select>
        <select value={filter.minRostered} onChange={(e) => set({ minRostered: Number(e.target.value) })} aria-label="Percent rostered" title="Rostered in at least this share of Yahoo leagues">
          <option value={0}>any % rostered</option>
          {[5, 10, 25, 50].map((n) => (
            <option key={n} value={n}>
              {n}%+ rostered
            </option>
          ))}
        </select>
        <label className="inline muted" title="Hide players Yahoo lists as out (O, INJ, SUSP, NA, OFS)">
          <input type="checkbox" checked={filter.healthy} onChange={(e) => set({ healthy: e.target.checked })} /> hide out
        </label>
        <span className="grow" />
        <select value={system} onChange={(e) => setSystem(e.target.value as ProjectionSystem)} aria-label="Projection" title={systemTitle(w.systems.bbm, "bbm") + "\n" + systemTitle(w.systems.yahoo, "yahoo")}>
          {(["bbm", "yahoo"] as const).map((x) => (
            <option key={x} value={x}>
              {w.systems[x].label}
              {w.systems[x].players ? "" : " (none read)"}
            </option>
          ))}
        </select>
        <select value={horizon} onChange={(e) => setHorizon(e.target.value as Horizon)} aria-label="Horizon" title={horizonTitle}>
          {(["week", "next3"] as const).map((h) => (
            <option key={h} value={h}>
              {HORIZON_LABEL[h]}
            </option>
          ))}
        </select>
      </header>
      <p className="muted small board-note">
        {note.phrase}{" "}
        <span className="help" tabIndex={0} title={note.detail.join("\n")} aria-label={note.detail.join("; ")}>
          ?
        </span>
        {moves.error ? <span className="bad">{` · no moves: ${moves.error.message}`}</span> : !m && s.my_team ? " · valuing the moves…" : ""}
        {kept && keep && (
          <>
            {" · "}
            <span title={`${keep}\n${KEEP_RULE_TITLE}`}>
              {kept.lead}
              <button className="link" onClick={onKeep} title={`${keep}\nOpen the Strategy card, where the kept players are`}>
                {kept.count}
              </button>
              {kept.tail}
            </span>
          </>
        )}
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {OWN_COLUMNS.map((c) => th(c.key, c.label, c.title, Boolean(c.num)))}
              {th(
                "flag",
                "Flag",
                "the breakout flag: its level (watch, add, must-add) and score over a meter ticked at the level floors, from four signals (adds surge, minutes trend, value gap, opportunity); click a row's tag for the breakdown",
                false,
                <FlagInfo cfg={s.flag_config} inputs={s.flag_inputs} now={now} name="how flags work" />,
              )}
              {(["week", "three"] as const).map((h) => th(GAIN_KEY[h], GAIN_SHORT[h], gainTitle(h)))}
              {th("ros", "ROS", rosHeadTitle(s.scoring, `his best move over the ${HORIZON_LABEL[horizon]} (the For column's)`))}
              <th title={`the player his best move over the ${HORIZON_LABEL[horizon]} drops (the horizon at the right), or the held player it moves to make room; why there is no move`}>For</th>
              {th("next_price", "Next", `how much less the move over the ${HORIZON_LABEL[horizon]} adds with the next best drop`)}
              {cats.map((c) => th(c, CAT_LABEL[c], `${CAT_LABEL[c]} over the ${HORIZON_LABEL[horizon]} (${SYSTEM_SHORT[system]})`))}
              {TREND_COLUMNS.map((c) => th(c.key, c.label, c.title))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => {
              const t = totals.get(r.player.yahoo_id);
              const id = r.player.yahoo_id;
              const cand = m?.candidates[String(id)];
              const best = bestMove(cand, mh);
              const f = flagOf(s, id);
              const tag = flagTag(f, watch);
              const open = flagOpen === id && tag != null;
              return (
                <Fragment key={id}>
                  <tr
                    className={[id === highlight ? "hl" : "", picked?.add === id ? "picked" : ""].filter(Boolean).join(" ") || undefined}
                    onClick={() => onPick({ add: id, drop: openingDrop(cand, mh) })}
                  >
                    <td className="strong">
                      {r.player.name} <Status player={r.player} />
                    </td>
                    <td>{r.player.nba_team}</td>
                    <td>{r.player.positions.join(", ")}</td>
                    <td className={r.availability === "W" ? "accent" : undefined}>{availabilityLabel(r)}</td>
                    <td className="num">{games(r, "week") ?? ""}</td>
                    <td className="num dim">{games(r, "next3") ?? ""}</td>
                    <td>
                      {f && tag && (
                        <button
                          className="flag-btn"
                          aria-expanded={open}
                          aria-label={`${r.player.name}'s flag breakdown`}
                          title={`${flagTitle(f, s.flag_config)}\nclick for the breakdown`}
                          onClick={(e) => {
                            e.stopPropagation();
                            onToggleFlag(id);
                          }}
                        >
                          <FlagTag f={f} cfg={s.flag_config} watch={watch} />
                        </button>
                      )}
                    </td>
                    {(["week", "three"] as const).map((h) => (
                      <td key={h} className={`num ${gainTone(cand?.[h]?.gain, minGain)}`}>
                        {gainLabel(cand?.[h]?.gain)}
                      </td>
                    ))}
                    <td className={`num ${rosTone(best?.ros, s.scoring)}`} title={best ? rosTitle(best.ros, { add: id, drop: best.drop }, name, s.scoring) : undefined}>
                      {rosLabel(best?.ros, s.scoring)}
                    </td>
                    {best ? <BasisCell x={best} name={name} className="dim" /> : <td className="dim">{cand?.reason ?? ""}</td>}
                    <td className="num dim" title={best?.next_drop != null || best?.next_price != null ? `next best: ${name(best.next_drop)}` : undefined}>
                      {best?.next_price == null ? "" : best.next_price.toFixed(2)}
                    </td>
                    {cats.map((c) => (
                      <td
                        key={c}
                        className="num"
                        title={t?.theirs ? `${SYSTEM_SHORT[other]}: ${catValue(c, t.theirs[c])}` : `no ${SYSTEM_SHORT[other]} line`}
                      >
                        {catValue(c, t?.mine?.[c])}
                      </td>
                    ))}
                    <td className="num">{pctLabel(r.pct_rostered)}</td>
                    <td className={`num ${(r.pct_rostered_change ?? 0) > 0 ? "good" : (r.pct_rostered_change ?? 0) < 0 ? "bad" : ""}`}>{changeLabel(r.pct_rostered_change)}</td>
                    <td className="num">{pctLabel(r.pct_started)}</td>
                    <td className="num">{r.adds ?? ""}</td>
                    <td className="num">{r.drops ?? ""}</td>
                  </tr>
                  {open && f && (
                    <tr className="breakdown">
                      <td colSpan={columns}>
                        <FlagBreakdown f={f} cfg={s.flag_config} silent={s.flag_inputs?.silent} onEvaluate={() => onPick({ add: id, drop: openingDrop(cand, mh) })} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

type Totals = ReturnType<typeof projectedTotals>;

/** A player's games in a horizon from the week projection, else this week's schedule count. */
function rowGames(w: WeekProjection, r: AvailableRow, h: Horizon): number | null {
  return horizonGames(w.players[String(r.player.yahoo_id)]?.games, h) ?? (h === "week" ? r.games_left : null);
}

function systemTitle(info: ProjectionSystemInfo, system: ProjectionSystem): string {
  const what = system === "bbm" ? "per game from the rest-of-season export" : "per game from Yahoo's next 7 days (the players page's Next 7 Days view)";
  return `${info.label}: ${what}; ${info.players ? `${info.players} players` : "nothing read"}${info.as_of ? `, ${info.as_of}` : ""}`;
}

// ---------------------------------------------------------------- moves (#94)
const OTHER_HORIZON: Record<MoveHorizon, MoveHorizon> = { week: "three", three: "week" };

/** "adds Brooks for Grant, Vucevic for Ayton to IL", or "makes no move". */
function insteadText(moves: HeldRef[], name: Namer): string {
  return moves.length ? `adds ${moves.map((x) => `${name(x.add)} for ${forText(x, name)}`).join(", ")}` : "makes no move";
}

/** The Moves card's note: the system, then the room an add without a drop has (#187). */
function movesNote(m: MovesPayload | undefined, s: SeasonView): string | undefined {
  if (!m) return undefined;
  const byId = playersById(s);
  const room = m.room ? roomNote(m.room, (id) => byId.get(id)?.name ?? `player ${id}`) : null;
  return [m.system.label, room].filter(Boolean).join(" · ");
}

/** A For cell (#187): the drop's name, "after Hurt to IL" or "free: open spot", with the rule
 * that applied as its title. */
function BasisCell({ x, name, className, children }: { x: { drop: number | null; held?: HeldMove | null; held_drop?: HeldMove | null }; name: Namer; className?: string; children?: ReactNode }) {
  const b = addBasis(x, name);
  return (
    <td className={className} title={b.title}>
      {b.cell}
      {children}
    </td>
  );
}

/** The recommended sets, the three weeks first, then the rest of this week. */
function Moves({ q, s, onPick }: { q: UseQueryResult<MovesPayload>; s: SeasonView; onPick: (m: MoveKey) => void }) {
  const name = useNamer(s);
  if (!s.my_team) return <p className="muted">The moves need my team: none is set for this league.</p>;
  if (q.error) return <p className="error">{q.error.message}</p>;
  const m = q.data;
  if (!m) return <p className="muted">Valuing the moves…</p>;
  // Why some adds have no move at all: the week's adds used, or no legal drop (#124).
  const reasons = [...new Set(Object.values(m.candidates).flatMap((c) => (c.reason ? [c.reason] : [])))];
  return (
    <>
      <p className="muted small" title={m.adds.complete ? "my adds this week from the transactions page" : "the transactions page does not reach back to the week's start: more adds may have been used"}>
        {addsNote(m.adds)}
        {m.system.fallback ? ` · ${m.system.fallback}` : ""}
      </p>
      {(m.cleared ?? []).map((c) => (
        <p key={c.player} className="bad small">
          {name(c.player)}&apos;s status cleared ({c.status ?? "healthy"}): Yahoo takes no add until he leaves {c.slot}
          {c.drop == null ? "" : c.drop === c.player ? ", and he is the one to drop" : `; activating him drops ${name(c.drop)}`}.
        </p>
      ))}
      {reasons.map((r) => (
        <p key={r} className="accent small">
          {cap(r)}.
        </p>
      ))}
      {(["three", "week"] as const).map((h) => (
        <Recommended key={h} h={h} m={m} s={s} name={name} onPick={onPick} />
      ))}
      <PlanBlock m={m} s={s} name={name} />
      <WeekPlansBlock m={m} s={s} name={name} />
      <KeepRuleBlock m={m} name={name} />
      {(m.stash ?? []).length > 0 && (
        <div className="block">
          <span className="k" title="each of my players with an absence: the held slots his status allows, and what the keep rule says to do with him">
            Out
          </span>
          {(m.stash ?? []).map((a) => (
            <p key={a.player} className="muted small">
              {stashText(a, name, s.scoring)}
            </p>
          ))}
        </div>
      )}
      <p className="dim small">
        Recommended by a search over the {m.search.pool} candidates whose best single move adds most: a strong heuristic, not a proof. Each move&apos;s prices
        are re-solves: the set without his add, and the set keeping his drop.
      </p>
    </>
  );
}

/** Whom the keep rule keeps (#124): each with his rest-of-season value a game and why. */
function KeepRuleBlock({ m, name }: { m: MovesPayload; name: Namer }) {
  const rule = m.keep_rule;
  const kept = keptPlayers(rule);
  if (!rule || !kept.length) return null;
  return (
    <div className="block">
      <span className="k" title="each player's rest-of-season value a game, from the rest-of-season line whatever the system">
        Kept by the keep rule
      </span>
      <p className="dim small">{keepRuleNote(rule, name)}</p>
      <table className="season-table">
        <thead>
          <tr>
            <th>Player</th>
            <th className="num" title="rest-of-season value a game">
              a game
            </th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {kept.map((k) => (
            <tr key={k.player}>
              <td className="strong">{name(k.player)}</td>
              <td className="num">{k.value == null ? "" : k.value.toFixed(2)}</td>
              <td className="dim">{keptWhy(k)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Recommended({ h, m, s, name, onPick }: { h: MoveHorizon; m: MovesPayload; s: SeasonView; name: Namer; onPick: (m: MoveKey) => void }) {
  const set = m.recommended[h];
  const info = m.horizons[h];
  const o = OTHER_HORIZON[h];
  const returns = comebackText([set.comebacks?.week, set.comebacks?.three], name);
  return (
    <div className="block">
      <span className="k" title={`${info.base.toFixed(2)} expected categories without a move${info.from ? `, from ${dayLabel(info.from)}` : ""}`}>
        Recommended for {horizonName(m, h)}
        {set.moves.length > 0 && ` · ${gainLabel(set.gain[h])} (${GAIN_SHORT[o]} ${gainLabel(set.gain[o])}${set.ros ? ` · ROS ${rosLabel(set.ros, s.scoring)}` : ""})`}
      </span>
      {set.moves.length === 0 ? (
        <p className="muted small">No move adds more than {m.search.min_gain} expected categories.</p>
      ) : (
        <table className="season-table">
          <thead>
            <tr>
              <th>Add</th>
              <th>For</th>
              <th title="the day he plays from: a waiver claim's clear date, when its drop leaves too">From</th>
              <th className="num" title={`what the move adds to the set over ${horizonName(m, h)}`}>
                {GAIN_SHORT[h]}
              </th>
              <th className="num" title={`what the move adds to the set over ${horizonName(m, o)}`}>
                {GAIN_SHORT[o]}
              </th>
              <th className="num" title={rosHeadTitle(s.scoring)}>
                ROS
              </th>
              <th className="num" title="what the set gives up when the search runs again without this add">
                w/o
              </th>
              <th className="num" title="what the set gives up when the search runs again keeping this drop">
                keep
              </th>
            </tr>
          </thead>
          <tbody>
            {set.moves.map((x) => (
              <tr key={x.add} className="pick" onClick={() => onPick(x)}>
                <td className="strong">
                  {name(x.add)} <FlagTag f={flagOf(s, x.add)} cfg={s.flag_config} />
                </td>
                <BasisCell x={x} name={name} />
                <td className="dim">{dayLabel(x.from)}</td>
                <td className={`num ${gainTone(x.marginal[h], m.search.min_gain)}`}>{gainLabel(x.marginal[h])}</td>
                <td className="num dim">{gainLabel(x.marginal[o])}</td>
                <td className={`num ${rosTone(x.ros, s.scoring) || "dim"}`} title={rosTitle(x.ros, x, name, s.scoring)}>
                  {rosLabel(x.ros, s.scoring)}
                </td>
                <td className="num" title={`without ${name(x.add)} the search ${insteadText(x.instead_without, name)}`}>
                  {x.price_without.toFixed(2)}
                </td>
                <td
                  className="num"
                  title={
                    x.instead_keep
                      ? `keeping ${name(x.drop)} the search ${insteadText(x.instead_keep, name)}${x.decided_by === "season" ? ": a tie on this horizon, which the season decided" : ""}`
                      : "no drop to keep"
                  }
                >
                  {x.price_keep == null ? "" : x.price_keep.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {set.held.length > 0 && !set.moves.some((x) => x.held) && (
        <p className="muted small">It also moves {set.held.map((x) => `${name(x.player)} to ${x.slot}`).join(", ")}.</p>
      )}
      {returns && <p className="muted small">{returns}</p>}
      <SeasonGuardNote set={set} h={h} s={s} name={name} />
    </div>
  );
}

/** What the season guard held back from a set (#164): one muted line, the held set's moves on
 * hover, flagged season-costly; never shown as recommended. */
function SeasonGuardNote({ set, h, s, name }: { set: MovesPayload["recommended"][MoveHorizon]; h: MoveHorizon; s: SeasonView; name: Namer }) {
  const line = seasonGuardLine(set.season_guard, h, s.scoring);
  if (!line) return null;
  const held = seasonGuardMoves(set.season_guard, name, s.scoring);
  return (
    <p className="muted small" title={held ? `held back, not recommended: ${held}` : undefined}>
      {line}
    </p>
  );
}

/** The week's streaming plan (#136) under the week's set when it is recommended: its steps by
 * day, each with its own gain, and what it buys against the set. A plan under the floor is one
 * muted line saying what it would have bought. */
function PlanBlock({ m, s, name }: { m: MovesPayload; s: SeasonView; name: Namer }) {
  const plan = shownPlan(m.plan);
  const ros = plan && planRosText(plan, s.scoring);
  if (!plan) {
    const line = planShortLine(m.plan, name, s.scoring);
    const steps = guardSteps(m.plan, name);
    const refused = m.plan?.guard?.ros;
    const which = m.plan?.reason === "season" ? "season" : "three-week";
    return line ? (
      <p className="muted small" title={steps ? `the plan the ${which} guard refused: ${steps}${refused ? `; to the season's end ${rosLabel(refused, s.scoring)} on the set` : ""}` : undefined}>
        {line}
      </p>
    ) : null;
  }
  return (
    <div className="block">
      <span
        className="k"
        title={`a dated sequence of adds and drops that turns the weakest spots over inside the week; recommended when its week beats the set's by more than the floor, ${plan.floor} ${s.scoring === "points" ? "of the matchup's win odds" : "expected categories"}`}
      >
        Streaming plan for {horizonName(m, "week")} · {gainLabel(plan.gain.week)} on the set ({GAIN_SHORT.three} {gainLabel(plan.gain.three)})
        {ros && ` · ${ros}`}
      </span>
      <table className="season-table">
        <thead>
          <tr>
            <th>Day</th>
            <th>Add</th>
            <th title="the spot's holder before: one of mine, or an earlier step's add">Drop</th>
            <th className="num" title={`what the step adds to the plan before it over ${horizonName(m, "week")}`}>
              {GAIN_SHORT.week}
            </th>
            <th className="num" title={`what the step adds to the plan before it over ${horizonName(m, "three")}`}>
              {GAIN_SHORT.three}
            </th>
            <th className="num" title={`${rosHeadTitle(s.scoring, "the step")}; a streamer a later step drops is valued as kept there, and the plan's total nets the two`}>
              ROS
            </th>
          </tr>
        </thead>
        <tbody>
          {plan.steps.map((x) => (
            <tr key={`${x.from}-${x.add}`}>
              <td className="dim wrap">{stepDay(x.from)}</td>
              <td className="strong wrap">
                {name(x.add)} <FlagTag f={flagOf(s, x.add)} cfg={s.flag_config} />
              </td>
              <td className="wrap">{name(x.drop)}</td>
              <td className={`num ${gainTone(x.marginal.week, m.search.min_gain)}`}>{gainLabel(x.marginal.week)}</td>
              <td className="num dim">{gainLabel(x.marginal.three)}</td>
              <td className={`num ${rosTone(x.ros, s.scoring) || "dim"}`} title={planStepRosTitle(x, name, s.scoring)}>
                {rosLabel(x.ros, s.scoring)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">{planNote(plan, name)}</p>
    </div>
  );
}

/** The week plans (#221 part 2): a few dated sequences of moves over the rest of the week, each
 * step with what it adds to the plan before it, the roster's own changes on their day, and each
 * plan's total; the plan the queue takes is marked. Plan 1 opens; the others fold. */
function WeekPlansBlock({ m, s, name }: { m: MovesPayload; s: SeasonView; name: Namer }) {
  const wp = m.week_plans;
  const plans = shownWeekPlans(wp);
  if (!wp || !plans.length) return null;
  const units = s.scoring === "points" ? "of the matchup's win odds" : "expected categories";
  return (
    <div className="block">
      <span
        className="k"
        title={weekPlansTitle(wp, units)}
      >
        Week plans for {horizonName(m, "week")}
      </span>
      {plans.map((w, i) => {
        const body = <WeekPlanTable w={w} m={m} s={s} name={name} />;
        const head = weekPlanHead(w, wp.plans.indexOf(w), wp.queue === wp.plans.indexOf(w));
        const ros = w.ros ? ` · ${rosLabel(w.ros, s.scoring)} to the season's end` : "";
        return i === 0 ? (
          <Fragment key={i}>
            <p className="small">
              {head}
              {ros}
            </p>
            {body}
          </Fragment>
        ) : (
          <details key={i} className="small">
            <summary>
              {head}
              {ros}
            </summary>
            {body}
          </details>
        );
      })}
    </div>
  );
}

function WeekPlanTable({ w, m, s, name }: { w: WeekPlan; m: MovesPayload; s: SeasonView; name: Namer }) {
  return (
    <>
      {w.steps.length > 0 && (
        <table className="season-table">
          <thead>
            <tr>
              <th>Day</th>
              <th>Add</th>
              <th title="the drop, or the held-slot move that makes room; a churn drops a held player">For</th>
              <th className="num" title={`what the step adds to the plan before it over ${horizonName(m, "week")}`}>
                {GAIN_SHORT.week}
              </th>
              <th className="num" title={`what the step adds to the plan before it over ${horizonName(m, "three")}`}>
                {GAIN_SHORT.three}
              </th>
              <th className="num" title={rosHeadTitle(s.scoring, "the step")}>
                ROS
              </th>
            </tr>
          </thead>
          <tbody>
            {w.steps.map((x) => {
              const basis = addBasis(x, name);
              return (
                <tr key={`${x.from}-${x.add}`}>
                  <td className="dim wrap">{stepDay(x.from)}</td>
                  <td className="strong wrap">
                    {name(x.add)} <FlagTag f={flagOf(s, x.add)} cfg={s.flag_config} />
                  </td>
                  <td className="wrap" title={basis.title}>
                    {basis.cell}
                  </td>
                  <td className={`num ${gainTone(x.gain.week, m.search.min_gain)}`}>{gainLabel(x.gain.week)}</td>
                  <td className="num dim">{gainLabel(x.gain.three)}</td>
                  <td className={`num ${rosTone(x.ros, s.scoring) || "dim"}`}>{rosLabel(x.ros, s.scoring)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {w.backs.map((b) => (
        <p key={`${b.day}-${b.player}`} className="muted small" title="the roster's own change that day: no choice in it">
          {weekBackLine(b, name)}
        </p>
      ))}
    </>
  );
}

// ---------------------------------------------------------------- flags (#95)
/** The Flags card's note: the flagged players by level, "2 must-add · 3 add · 5 watch" (#185). */
function flagCount(s: SeasonView): string | undefined {
  if (s.flag_inputs?.error) return "not made";
  return flagged(s).length ? flagCounts(flagLevels(s)) : undefined;
}

/** The flagged available players, the highest first; a click opens his breakdown under the row,
 * which carries the move. */
function Flags({
  s,
  m,
  mh,
  now,
  onPick,
  open,
  onToggle,
  watch,
  setWatch,
}: {
  s: SeasonView;
  m: MovesPayload | undefined;
  mh: MoveHorizon;
  now: number;
  onPick: (m: MoveKey) => void;
  open: number | null;
  onToggle: (id: number) => void;
  watch: boolean;
  setWatch: (on: boolean) => void;
}) {
  const rows = flagged(s, { watch });
  const lowest = s.flag_config ? Math.min(...s.flag_config.levels.map((l) => l.floor)) : null;
  return (
    <>
      <label className="small muted flag-watch" title={`the players under the watch level${lowest != null ? ` (a score above 0, below ${lowest})` : ""}, dimmed, after the flagged ones; kept in this browser`}>
        <input type="checkbox" checked={watch} onChange={(e) => setWatch(e.target.checked)} /> show under watch
      </label>
      {rows.length === 0 ? (
        <p className="muted small">No available player is flagged.</p>
      ) : (
        <table className="season-table">
          <thead>
            <tr>
              <th>Flag</th>
              <th>Player</th>
              <th>Signals</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ row, flag }) => {
              const id = row.player.yahoo_id;
              const shown = open === id;
              return (
                <Fragment key={id}>
                  <tr
                    className={`pick${shown ? " picked" : ""}`}
                    aria-expanded={shown}
                    title={shown ? "Click to close the breakdown" : "Click for the breakdown"}
                    onClick={() => onToggle(id)}
                  >
                    <td>
                      <FlagTag f={flag} cfg={s.flag_config} watch={watch} />
                    </td>
                    <td className="strong">
                      {row.player.name} <span className="dim">{row.player.nba_team}</span>
                    </td>
                    <td className="sigs">
                      {flagSignals(flag).map((k) => (
                        <span key={k} className="sig-chip">
                          {FLAG_SIGNAL_NAME[k]}
                        </span>
                      ))}
                    </td>
                  </tr>
                  {shown && (
                    <tr className="breakdown">
                      <td colSpan={3}>
                        <FlagBreakdown f={flag} cfg={s.flag_config} silent={s.flag_inputs?.silent} onEvaluate={() => onPick({ add: id, drop: openingDrop(m?.candidates[String(id)], mh) })} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
      <p className={`small ${s.flag_inputs?.error ? "bad" : "dim"}`}>
        {flagInputsNote(s.flag_inputs, now)} · signs a pickup may outlast his projection, which lags a role change by days; nothing is added automatically;
        the levels are first guesses until two weeks of buzz-index history are kept
      </p>
    </>
  );
}

/** One add with one drop: each category before and after on both horizons, every other drop
 * and the best other adds for this drop. */
function MoveDrawer({
  league,
  s,
  system,
  m,
  picked,
  onPick,
}: {
  league: string;
  s: SeasonView;
  system: ProjectionSystem;
  m: MovesPayload | undefined;
  picked: MoveKey;
  onPick: (m: MoveKey) => void;
}) {
  const name = useNamer(s);
  const q = useQuery({
    queryKey: ["move", league, system, picked.add, picked.drop, s.updated_at],
    queryFn: () => api.move(league, picked.add, picked.drop, system),
    retry: false,
  });
  const d = q.data;
  const p = playersById(s).get(picked.add);
  const row = s.available.find((r) => r.player.yahoo_id === picked.add);
  const cats = s.settings.cats;
  const min = m?.search.min_gain ?? 0;
  const returns = d ? comebackText([d.horizons.week.comebacks, d.horizons.three.comebacks], name) : null;
  // An add with no drop has its basis once the move is read: an open spot or a held move.
  const basis = d || picked.drop != null ? addBasis({ drop: picked.drop, held: d?.held[0] }, name) : null;
  return (
    <>
      <div className="block">
        <span className="k">
          Add {name(picked.add)} <FlagTag f={flagOf(s, picked.add)} cfg={s.flag_config} />{" "}
          {basis ? <span title={basis.title}>{basisPhrase(basis)}</span> : "with no drop"}
        </span>
        <p className="muted small">
          {p && `${p.nba_team ?? "no team"} · ${p.positions.join(", ")} · `}
          {row ? availabilityLabel(row) : "not in the pool"}
          {d && ` · plays from ${dayLabel(d.from)}${picked.drop != null && row?.availability === "W" ? `, when ${name(picked.drop)} leaves` : ""}`}
        </p>
        {returns && (
          <p className="muted small" title="the least valuable active player by per-game value on the return day">
            {returns}
          </p>
        )}
      </div>
      {q.error && <p className="error">{q.error.message}</p>}
      {!d && !q.error && <p className="muted">Valuing the move…</p>}
      {d && (
        <>
          <div className="block">
            <span className="k" title="expected categories won this week, the week so far included">
              {cap(horizonName(m, "week"))} · {d.horizons.week.before.toFixed(2)} → {d.horizons.week.after.toFixed(2)} ({gainLabel(d.horizons.week.gain)})
            </span>
            <WeekCats cats={cats} before={d.horizons.week.cats.before} after={d.horizons.week.cats.after} />
          </div>
          <div className="block">
            <span className="k" title="expected categories won over the three weeks, each week's odds averaged over the other teams">
              {cap(horizonName(m, "three"))} · {d.horizons.three.before.toFixed(2)} → {d.horizons.three.after.toFixed(2)} ({gainLabel(d.horizons.three.gain)})
            </span>
            <FieldCats cats={cats} before={d.horizons.three.cats.before} after={d.horizons.three.cats.after} />
          </div>
          <div className="block">
            <span className="k" title={rosHeadTitle(s.scoring)}>
              Rest of the season · {d.ros?.value != null ? rosLabel(d.ros, s.scoring) : "not valued"}
            </span>
            <p className="muted small">{cap(rosTitle(d.ros, d, name, s.scoring))}.</p>
          </div>
          <div className="block">
            <span className="k">Drop instead</span>
            <table className="season-table">
              <thead>
                <tr>
                  <th>For</th>
                  <th className="num">{GAIN_SHORT.week}</th>
                  <th className="num">{GAIN_SHORT.three}</th>
                  <th className="num" title={rosHeadTitle(s.scoring)}>
                    ROS
                  </th>
                </tr>
              </thead>
              <tbody>
                {d.drops.map((x) => (
                  <tr key={x.drop ?? "open"} className={`pick${x.drop === picked.drop ? " hl" : ""}`} onClick={() => onPick({ add: picked.add, drop: x.drop })}>
                    <BasisCell x={x} name={name}>
                      {x.kept && (
                        <span className="dim small" title="the keep rule keeps him: the search never drops him, the gain says what dropping him would bring">
                          {" "}
                          · kept
                        </span>
                      )}
                    </BasisCell>
                    <td className={`num ${gainTone(x.week, min)}`}>{gainLabel(x.week)}</td>
                    <td className={`num ${gainTone(x.three, min)}`}>{gainLabel(x.three)}</td>
                    <td className={`num ${rosTone(x.ros, s.scoring)}`} title={rosTitle(x.ros, { add: picked.add, drop: x.drop }, name, s.scoring)}>
                      {rosLabel(x.ros, s.scoring)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.adds.length > 0 && (
            <div className="block">
              <span className="k">Other adds for {name(picked.drop)}</span>
              <table className="season-table">
                <thead>
                  <tr>
                    <th>Add</th>
                    <th className="num">{GAIN_SHORT.week}</th>
                    <th className="num">{GAIN_SHORT.three}</th>
                    <th className="num" title={rosHeadTitle(s.scoring)}>
                      ROS
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {d.adds.map((x) => (
                    <tr key={x.add} className="pick" onClick={() => onPick({ add: x.add, drop: picked.drop })}>
                      <td>{name(x.add)}</td>
                      <td className={`num ${gainTone(x.week, min)}`}>{gainLabel(x.week)}</td>
                      <td className={`num ${gainTone(x.three, min)}`}>{gainLabel(x.three)}</td>
                      <td className={`num ${rosTone(x.ros, s.scoring)}`} title={rosTitle(x.ros, { add: x.add, drop: picked.drop }, name, s.scoring)}>
                        {rosLabel(x.ros, s.scoring)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}

type CatsByCat = Partial<Record<Cat, MoveCategory>>;

/** This week against the opponent: my final before and after, theirs, and the odds of each. */
function WeekCats({ cats, before, after }: { cats: Cat[]; before: CatsByCat; after: CatsByCat }) {
  return (
    <table className="season-table">
      <thead>
        <tr>
          <th></th>
          <th className="num" title="my projected final without the move">
            me
          </th>
          <th className="num" title="my projected final with the move">
            after
          </th>
          <th className="num">them</th>
          <th className="num" title="the odds of winning the category without the move">
            win
          </th>
          <th className="num" title="the odds with the move">
            after
          </th>
        </tr>
      </thead>
      <tbody>
        {cats.map((c) => {
          const b = before[c];
          const a = after[c];
          return (
            <tr key={c}>
              <td>{CAT_LABEL[c]}</td>
              <td className="num dim">{catValue(c, b?.mine)}</td>
              <td className="num">{catValue(c, a?.mine)}</td>
              <td className="num dim">{catValue(c, b?.theirs)}</td>
              <td className={`num ${b ? oddsTone(b.wins) : ""}`}>{b ? oddsLabel(b.wins) : ""}</td>
              <td className={`num ${a ? oddsTone(a.wins) : ""}`}>{a ? oddsLabel(a.wins) : ""}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** The three weeks against the field: expected wins of each category, before and after. */
function FieldCats({ cats, before, after }: { cats: Cat[]; before: CatsByCat; after: CatsByCat }) {
  return (
    <table className="season-table">
      <thead>
        <tr>
          <th></th>
          <th className="num" title="expected weeks won without the move">
            wins
          </th>
          <th className="num" title="with the move">
            after
          </th>
          <th className="num">change</th>
        </tr>
      </thead>
      <tbody>
        {cats.map((c) => {
          const b = before[c]?.wins;
          const a = after[c]?.wins;
          const diff = a != null && b != null ? a - b : null;
          return (
            <tr key={c}>
              <td>{CAT_LABEL[c]}</td>
              <td className="num dim">{b?.toFixed(2) ?? ""}</td>
              <td className="num">{a?.toFixed(2) ?? ""}</td>
              <td className={`num ${diff == null ? "" : diff > 0.005 ? "good" : diff < -0.005 ? "bad" : ""}`}>{gainLabel(diff)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ---------------------------------------------------------------- drawer
function Roster({ rows, w }: { rows: RosterRow[]; w: WeekProjection }) {
  if (!rows.length) return <p className="muted">No roster read for my team.</p>;
  const proj = (r: RosterRow) => w.players[String(r.player.yahoo_id)];
  return (
    <table className="season-table">
      <thead>
        <tr>
          <th>Slot</th>
          <th>Player</th>
          <th>Team</th>
          <th>Pos</th>
          <th className="num" title="games he plays in the rest of this week, from today; in brackets the games he starts when a crowded day leaves him on the bench">
            G
          </th>
          <th className="num" title="games in the three weeks after this one">
            3wk
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.slot}-${r.player.yahoo_id}-${i}`} className={r.slot === "BN" || r.slot.startsWith("IL") ? "bench" : undefined}>
            <td className="dim">{r.slot}</td>
            <td className="strong">
              {r.player.name} <Status player={r.player} />
            </td>
            <td>{r.player.nba_team}</td>
            <td>{r.player.positions.join(", ")}</td>
            <RosterGames row={r} p={proj(r)} />
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RosterGames({ row, p }: { row: RosterRow; p: WeekProjection["players"][string] | undefined }) {
  const g = horizonGames(p?.games, "week") ?? row.games_left;
  const started = p?.started?.[0];
  return (
    <>
      <td className="num">
        {g ?? ""}
        {started != null && g != null && started < g && <span className="dim"> ({started})</span>}
      </td>
      <td className="num dim">{horizonGames(p?.games, "next3") ?? ""}</td>
    </>
  );
}

/** A pairing's columns, mine first. */
function ordered(m: SeasonMatchup, mine: number | undefined): [number, number] {
  return m.teams[1] === mine ? [m.teams[1], m.teams[0]] : m.teams;
}

/** The League card's tabs (#116): the standings with the weeks recorded, or this week's
 * pairings. */
type LeagueTab = "standings" | "matchups";
const LEAGUE_TABS: [LeagueTab, string][] = [
  ["standings", "Standings"],
  ["matchups", "Matchups"],
];

function League({ s }: { s: SeasonView }) {
  const mine = s.my_team?.team_id;
  const points = s.scoring === "points";
  return (
    <>
      <div className="block">
        <span className="k">Standings</span>
        <table className="season-table">
          <thead>
            <tr>
              <th className="num">#</th>
              <th>Team</th>
              <th>W-L-T</th>
              {points && <th className="num">PF</th>}
              <th className="num" title="waiver priority">
                Wvr
              </th>
              {s.settings.uses_faab && (
                <th className="num" title="FAAB left">
                  $
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {s.teams.map((t) => (
              <tr key={t.team_id} className={t.team_id === mine ? "mine" : undefined}>
                <td className="num dim">{t.rank ?? ""}</td>
                <td>{t.name}</td>
                <td>{t.record ?? ""}</td>
                {points && <td className="num">{t.points_for ?? ""}</td>}
                <td className="num">{t.waiver_priority ?? ""}</td>
                {s.settings.uses_faab && <td className="num">{t.faab ?? ""}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Weeks league={s.league} />
      {s.transactions.length > 0 && (
        <div className="block">
          <span className="k">Recent moves</span>
          <table className="season-table">
            <tbody>
              {s.transactions.slice(0, 12).map((t, i) => (
                <tr key={i} className={t.team_id === mine ? "mine" : undefined}>
                  <td className={t.kind === "add" ? "good" : t.kind === "drop" ? "bad" : "accent"}>{t.kind}</td>
                  <td>{t.player.name}</td>
                  <td className="dim">{t.team_name ?? ""}</td>
                  <td className="dim">{t.when ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

/** This week's pairings with their live scores (#116), mine first; a click opens a pairing's
 * categories as far as its matchup page was read. */
function Pairings({ s, now }: { s: SeasonView; now: number }) {
  const mine = s.my_team?.team_id;
  const [open, setOpen] = useState<string | null>(null);
  const name = (id: number) => s.teams.find((t) => t.team_id === id)?.name ?? `Team ${id}`;
  const pairs = [...s.matchups].sort((x, y) => Number(mine != null && y.teams.includes(mine)) - Number(mine != null && x.teams.includes(mine)));
  if (!pairs.length) return <p className="dim small">No pairing read for this week.</p>;
  return (
    <div className="block">
      <span className="k">Week {pairs[0].week} · click a pairing for its categories</span>
      <table className="season-table pairings">
        <tbody>
          {pairs.map((m) => {
            const key = `${m.week}/${Math.min(...m.teams)}-${Math.max(...m.teams)}`;
            const [a, b] = ordered(m, mine);
            const score = m.score && a !== m.teams[0] ? ([m.score[1], m.score[0]] as [number, number]) : m.score;
            const isOpen = open === key;
            const read = s.fetched[`matchup/${key}`];
            return (
              <Fragment key={key}>
                <tr className={`pick${a === mine ? " mine" : ""}`} aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : key)}>
                  <td title={name(a)}>{name(a)}</td>
                  <td className="num strong">{score ? scoreLabel({ score, scoring: s.scoring }) : "—"}</td>
                  <td className="r" title={name(b)}>
                    {name(b)}
                  </td>
                </tr>
                {isOpen && (
                  <tr className="breakdown">
                    <td colSpan={3}>
                      <div className="pair-totals">
                        <PairTotals m={m} a={a} b={b} name={name} />
                        <span className="dim small">
                          {read
                            ? `categories read ${ageLabel(read.at, now)}`
                            : `categories not read: ${s.public ? "a refresh reads every pairing's matchup page" : "open its matchup page in Chrome with the extension"}`}
                        </span>
                      </div>
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

/** The weeks the recorder kept (#97): my opponent, result and place after each, latest first. */
function Weeks({ league }: { league: string }) {
  const q = useQuery({ queryKey: ["weeks", league], queryFn: () => api.weeks(league), refetchInterval: 300_000 });
  const weeks = q.data?.weeks ?? [];
  return (
    <div className="block">
      <span className="k">Weeks</span>
      {q.error && <p className="error small">{q.error.message}</p>}
      {!q.error && !weeks.length && <p className="dim small">No week recorded yet: each week is recorded the Monday after it ends.</p>}
      {weeks.length > 0 && (
        <table className="season-table">
          <thead>
            <tr>
              <th className="num">Wk</th>
              <th>Opponent</th>
              <th>Result</th>
              <th className="num" title="my place in the standings after the week">
                #
              </th>
            </tr>
          </thead>
          <tbody>
            {[...weeks].reverse().map((w) => (
              <tr key={w.week} title={recordedTitle(w)}>
                <td className="num dim">{w.week}</td>
                <td>{w.opponent_name ?? (w.opponent != null ? `Team ${w.opponent}` : "")}</td>
                <td className={weekTone(w.result)}>
                  {weekResult(w.result)}
                  {w.revised_at && <span className="dim"> *</span>}
                </td>
                <td className="num">{w.rank ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function recordedTitle(w: RecordedWeek): string {
  const parts = [`${weekDates(w)}${w.record ? `, ${w.record} after it` : ""}`];
  if (w.games) parts.push(`${w.games.played} games played`);
  if (w.revised_at) parts.push(`revised ${dayLabel(w.revised_at.slice(0, 10))} (a stat correction)`);
  const missing = Object.entries(w.missing).map(([k, v]) => `${v} ${k}`);
  if (missing.length) parts.push(`missing: ${missing.join(", ")}`);
  return parts.join(" · ");
}

/** A pairing's totals so far, its first team on the first line: Yahoo's columns, or a points
 * league's score lines. */
function PairTotals({ m, a, b, name }: { m: SeasonMatchup; a: number; b: number; name: (id: number) => string }) {
  const flip = a !== m.teams[0];
  const pair = (v: [number, number]) => (flip ? [v[1], v[0]] : v);
  const totalsA = m.totals[String(a)] ?? {};
  const totalsB = m.totals[String(b)] ?? {};
  const cats = Object.keys(totalsA);
  // A categories matchup has only the score, which the row carries; a points one adds Yahoo's
  // projections.
  const lines = Object.entries(m.lines).filter(([label]) => label !== "vs" || Object.keys(m.lines).length > 1);
  return (
    <>
      {lines.length > 0 && (
        <table className="season-table">
          <thead>
            <tr>
              <th></th>
              <th className="num">{name(a)}</th>
              <th className="num">{name(b)}</th>
            </tr>
          </thead>
          <tbody>
            {lines.map(([label, v]) => (
              <tr key={label}>
                <td className="dim">{label === "vs" ? "score" : label}</td>
                <td className="num">{pair(v)[0]}</td>
                <td className="num">{pair(v)[1]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {cats.length > 0 && (
        <table className="season-table">
          <thead>
            <tr>
              <th></th>
              {cats.map((c) => (
                <th key={c} className="num">
                  {c.replace(/\*$/, "")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[a, b].map((t, i) => (
              <tr key={t}>
                <td>{name(t)}</td>
                {cats.map((c) => (
                  <td key={c} className="num">
                    {(i === 0 ? totalsA : totalsB)[c] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function SeasonFooter({ s, now }: { s: SeasonView; now: number }) {
  const set = s.settings;
  const waivers = [
    set.waiver_rule ? `${set.waiver_rule} waivers` : null,
    set.uses_faab ? "FAAB" : null,
    set.max_weekly_adds != null ? `${set.max_weekly_adds} adds a week` : null,
  ].filter(Boolean);
  return (
    <footer className="footer season-foot">
      <span>From {s.sources.length ? s.sources.map((x) => (x === "public" ? "Yahoo's public pages" : "the extension")).join(" and ") : "nothing yet"}</span>
      <span title={s.calendar_estimated ? "no week dates read from Yahoo: Monday-to-Sunday weeks assumed" : "the week dates read from the league's team page"}>
        {s.calendar_estimated == null ? "no calendar" : `${s.end_week ?? "?"} weeks${s.calendar_estimated ? " (estimated)" : ""}`}
      </span>
      <span title="the NBA schedule behind the games-left counts (ESPN)">{s.schedule.last ? `schedule to ${s.schedule.last}` : "no schedule"}</span>
      {waivers.length > 0 && <span>{waivers.join(" · ")}</span>}
      <span className="grow" />
      <span>
        <kbd>?</kbd> keys · <kbd>w</kbd> <kbd>h</kbd> <kbd>s</kbd> views · <kbd>[</kbd> view drawer · <kbd>1</kbd>–<kbd>9</kbd> cards · <kbd>⇧</kbd>+digit bottom half · <kbd>]</kbd> panel · <kbd>p</kbd> progress
      </span>
      <span title={Object.entries(s.fetched).map(([k, f]) => `${k}: ${f.at} (${f.source})`).join("\n")}>Snapshot {ageLabel(s.updated_at, now)}</span>
      <span>League {s.league}</span>
    </footer>
  );
}
