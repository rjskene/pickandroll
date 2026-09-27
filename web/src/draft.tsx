// Draft-screen state shared by the board, the drawer cards, the rail and the hotkeys:
// which cards are open, the latest recommendation (solved in the background by the server
// after every change) and its settings, pick mutations, the board highlight, toasts and the
// shortcut sheet.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  pickOwner,
  teamLabel,
  type Objective,
  type Recommendation,
  type SessionSummary,
  type SimStrategy,
  type SolveEvent,
  type SolverStatus,
  type SurvivalEvent,
} from "./api";

export type CardId = "pick" | "cats" | "alts" | "plan" | "team" | "log" | "solver";
export type Half = "top" | "bottom";

export const CARDS: { id: CardId; title: string; blurb: string }[] = [
  { id: "pick", title: "Pick", blurb: "recommended pick" },
  { id: "cats", title: "Categories", blurb: "odds of winning each category, and the league" },
  { id: "alts", title: "Alternatives", blurb: "priced alternatives and what-if scenarios" },
  { id: "plan", title: "Plan", blurb: "plan for the remaining picks" },
  { id: "team", title: "Team", blurb: "score, expected profile and roster" },
  { id: "log", title: "Log", blurb: "every pick so far" },
  { id: "solver", title: "Solver", blurb: "timings, objective, settings" },
];
export const cardIndex = (id: CardId): number => CARDS.findIndex((c) => c.id === id);

interface Pair {
  top: CardId | null;
  bottom: CardId | null;
}
export interface DrawerState extends Pair {
  collapsed: boolean;
  /** Share of the drawer height given to the top card when both halves are open. */
  split: number;
  /** The last non-empty pair, restored by `]` after both halves were closed. */
  last: Pair;
  /** Drawer width in pixels, dragged at its left edge. */
  width: number;
}
const DRAWER_KEY = "pickandroll.drawer";
export const DRAWER_WIDTH = 420;
const MIN_DRAWER_WIDTH = 320;
/** Between the minimum and six tenths of the window, so the board always keeps room. */
export function clampWidth(px: number): number {
  const max = Math.max(MIN_DRAWER_WIDTH, Math.round(window.innerWidth * 0.6));
  return Math.min(max, Math.max(MIN_DRAWER_WIDTH, Math.round(px)));
}
const DEFAULT_DRAWER: DrawerState = { top: "pick", bottom: "cats", collapsed: false, split: 0.5, last: { top: "pick", bottom: "cats" }, width: DRAWER_WIDTH };
const isCard = (v: unknown): v is CardId => typeof v === "string" && CARDS.some((c) => c.id === v);

function loadDrawer(): DrawerState {
  try {
    const raw = localStorage.getItem(DRAWER_KEY);
    if (raw) {
      const d = JSON.parse(raw) as Partial<DrawerState>;
      const top = isCard(d.top) ? d.top : null;
      const bottom = isCard(d.bottom) ? d.bottom : null;
      return {
        top,
        bottom,
        collapsed: !!d.collapsed,
        split: typeof d.split === "number" ? Math.min(0.8, Math.max(0.2, d.split)) : 0.5,
        width: clampWidth(typeof d.width === "number" ? d.width : DRAWER_WIDTH),
        last: d.last && (isCard(d.last.top) || isCard(d.last.bottom)) ? { top: isCard(d.last.top) ? d.last.top : null, bottom: isCard(d.last.bottom) ? d.last.bottom : null } : { top, bottom },
      };
    }
  } catch {
    /* blocked storage: defaults */
  }
  return DEFAULT_DRAWER;
}

export interface Settings {
  /** Candidates priced exactly. */
  n: number;
  /** "If he is gone" plans solved while someone else is on the clock. */
  scenarios: number;
  /** Ask the server to re-solve on every pick when its own solve-ahead is off. */
  refreshOnPick: boolean;
  horizon: boolean;
  /** Override the session's objective; null keeps it. */
  objective: Objective | null;
}
const DEFAULT_SETTINGS: Settings = { n: 8, scenarios: 3, refreshOnPick: true, horizon: true, objective: null };

export interface Toast {
  id: number;
  message: string;
  undo?: boolean;
}

export interface DraftApi {
  session: SessionSummary;
  onClockTeam: string;
  draftingTeam: string;
  setTeamOverride: (team: string | null) => void;
  // drawer
  drawer: DrawerState;
  drawerOpen: boolean;
  openCard: (id: CardId, half?: Half) => void;
  closeCard: (id: CardId) => void;
  toggleDrawer: () => void;
  collapseDrawer: () => void;
  swapHalves: () => void;
  setSplit: (ratio: number) => void;
  setWidth: (px: number) => void;
  // recommendation
  settings: Settings;
  setSettings: (patch: Partial<Settings>) => void;
  result: Recommendation | undefined;
  /** The result was solved for an earlier board; a fresh solve is on its way. */
  stale: boolean;
  /** A solve is running or the result is stale: cards show placeholders instead of it. */
  busy: boolean;
  solver: SolverStatus | undefined;
  solving: boolean;
  solveError: string | null;
  solveEvents: SolveEvent[];
  survival: SurvivalEvent | null;
  solve: () => void;
  // picks
  draftPlayer: (playerId: string, opts?: { via?: "key" | "click" | "auto"; team?: string }) => void;
  drafting: boolean;
  undo: () => void;
  simulate: (body: { count?: number; until_my_pick: boolean }) => void;
  simulating: boolean;
  noise: number;
  setNoise: (n: number) => void;
  strategy: SimStrategy;
  setStrategy: (s: SimStrategy) => void;
  pickError: string | null;
  /** A live feed is attached: nothing is ever drafted for me automatically and nothing is simulated. */
  live: boolean;
  /** Mock draft: simulate the other teams and let the solver make my picks until the draft is complete. */
  mock: boolean;
  setMock: (v: boolean) => void;
  // board
  hideTaken: boolean;
  setHideTaken: (v: boolean) => void;
  toggleHideTaken: () => void;
  highlight: string | null;
  setHighlight: (id: string | null) => void;
  moveHighlight: (delta: number) => void;
  setVisibleRows: (ids: string[]) => void;
  searchRef: RefObject<HTMLInputElement | null>;
  // toast and sheet
  toast: Toast | null;
  showToast: (t: Omit<Toast, "id">) => void;
  dismissToast: () => void;
  sheetOpen: boolean;
  setSheetOpen: (v: boolean) => void;
}

const DraftContext = createContext<DraftApi | null>(null);

export function useDraft(): DraftApi {
  const value = useContext(DraftContext);
  if (!value) throw new Error("useDraft must be used inside DraftProvider");
  return value;
}

interface ProviderProps {
  session: SessionSummary;
  solveEvents: SolveEvent[];
  survival: SurvivalEvent | null;
  live: boolean;
  children: ReactNode;
}

export function DraftProvider({ session, solveEvents, survival, live, children }: ProviderProps) {
  const queryClient = useQueryClient();
  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["session", session.id] });
    queryClient.invalidateQueries({ queryKey: ["board", session.id] });
    queryClient.invalidateQueries({ queryKey: ["picks", session.id] });
    queryClient.invalidateQueries({ queryKey: ["score", session.id] });
    queryClient.invalidateQueries({ queryKey: ["teams", session.id] });
  }, [queryClient, session.id]);

  const owner = pickOwner(session.num_teams, session.next_overall);
  const onClockTeam = teamLabel(session, owner.position);
  const [teamOverride, setTeamOverride] = useState<string | null>(null);
  const draftingTeam = teamOverride ?? onClockTeam;

  // ---------------------------------------------------------------- drawer
  const [drawer, setDrawer] = useState<DrawerState>(loadDrawer);
  useEffect(() => {
    try {
      localStorage.setItem(DRAWER_KEY, JSON.stringify(drawer));
    } catch {
      /* storage unavailable */
    }
  }, [drawer]);
  const drawerOpen = !drawer.collapsed && (drawer.top !== null || drawer.bottom !== null);

  const openCard = useCallback((id: CardId, half: Half = "top") => {
    setDrawer((d) => {
      if (d.collapsed) {
        // Reopening: keep the pair if the card is already in it, else place the card.
        if (d.top === id || d.bottom === id) return { ...d, collapsed: false };
        const top = half === "top" ? id : d.top;
        const bottom = half === "bottom" ? id : d.bottom;
        return { ...d, top, bottom, collapsed: false, last: { top, bottom } };
      }
      let { top, bottom } = d;
      if (top === id) top = null;
      else if (bottom === id) bottom = null;
      else if (half === "top") top = id;
      else bottom = id;
      const empty = top === null && bottom === null;
      return { ...d, top, bottom, collapsed: empty, last: empty ? d.last : { top, bottom } };
    });
  }, []);
  const closeCard = useCallback(
    (id: CardId) => setDrawer((d) => (d.top === id || d.bottom === id ? applyClose(d, id) : d)),
    [],
  );
  const toggleDrawer = useCallback(() => {
    setDrawer((d) => {
      const open = !d.collapsed && (d.top !== null || d.bottom !== null);
      if (open) return { ...d, collapsed: true };
      if (d.top !== null || d.bottom !== null) return { ...d, collapsed: false };
      const last = d.last.top !== null || d.last.bottom !== null ? d.last : { top: "pick" as CardId, bottom: null };
      return { ...d, top: last.top, bottom: last.bottom, collapsed: false };
    });
  }, []);
  const collapseDrawer = useCallback(() => setDrawer((d) => ({ ...d, collapsed: true })), []);
  const swapHalves = useCallback(
    () => setDrawer((d) => ({ ...d, top: d.bottom, bottom: d.top, last: { top: d.bottom, bottom: d.top } })),
    [],
  );
  const setSplit = useCallback((ratio: number) => setDrawer((d) => ({ ...d, split: Math.min(0.8, Math.max(0.2, ratio)) })), []);
  const setWidth = useCallback((px: number) => setDrawer((d) => ({ ...d, width: clampWidth(px) })), []);

  // ---------------------------------------------------------------- toast and sheet
  const [toast, setToast] = useState<Toast | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  const showToast = useCallback((t: Omit<Toast, "id">) => {
    window.clearTimeout(toastTimer.current);
    setToast({ ...t, id: Date.now() });
    toastTimer.current = window.setTimeout(() => setToast(null), 5000);
  }, []);
  const dismissToast = useCallback(() => {
    window.clearTimeout(toastTimer.current);
    setToast(null);
  }, []);
  const [sheetOpen, setSheetOpen] = useState(false);

  // ---------------------------------------------------------------- recommendation
  // The server solves ahead of the clock after every change and publishes a `recommendation`
  // event; App invalidates this query on it. Manual re-solves and sessions without solve-ahead
  // queue a solve through /solve with the current settings.
  const [settings, setSettingsState] = useState<Settings>(DEFAULT_SETTINGS);
  const setSettings = useCallback((patch: Partial<Settings>) => setSettingsState((s) => ({ ...s, ...patch })), []);
  const params = useMemo(
    () => ({ n: settings.n, horizon: settings.horizon, scenarios: settings.scenarios, objective: settings.objective }),
    [settings],
  );
  const paramsRef = useRef(params);
  paramsRef.current = params;
  const latest = useQuery({
    queryKey: ["recommendation", session.id],
    queryFn: () => api.recommendation(session.id),
    refetchInterval: (q) => (q.state.data?.solver.running || q.state.data?.solver.pending ? 2000 : false),
  });
  const result = latest.data?.recommendation ?? undefined;
  const stale = !!result && (latest.data!.stale || (latest.data!.solved_version ?? -1) < session.version);
  const solveMutation = useMutation({
    mutationFn: () => api.solve(session.id, paramsRef.current),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["recommendation", session.id] }),
  });
  const { mutate: runSolve } = solveMutation;
  const solve = useCallback(() => runSolve(), [runSolve]);
  const solvedFor = useRef("");
  const havePicks = session.my_next_pick !== null && !session.complete;
  const serverSolves = session.solver.enabled;
  useEffect(() => {
    const key = `${session.id}:${session.version}`;
    if (!serverSolves && settings.refreshOnPick && havePicks && solvedFor.current !== key) {
      solvedFor.current = key;
      runSolve();
    }
  }, [session.id, session.version, havePicks, settings.refreshOnPick, serverSolves, runSolve]);
  const solving = solveMutation.isPending || !!latest.data?.solver.running || (!!latest.data?.solver.pending && !result);
  const busy = solving || stale;

  // ---------------------------------------------------------------- picks
  const draftMutation = useMutation({
    mutationFn: (v: { playerId: string; team: string; via: "key" | "click" | "auto" }) =>
      api.addPick(session.id, { team: v.team, player_id: v.playerId }),
    onSuccess: (row, v) => {
      setTeamOverride(null);
      invalidate();
      if (v.via === "key") showToast({ message: `Drafted ${row.name} to ${row.team}`, undo: true });
      if (v.via === "auto") showToast({ message: `Mock draft: the solver took ${row.name} at pick ${row.overall}`, undo: true });
    },
  });
  const { mutate: runDraft, isPending: drafting } = draftMutation;
  const draftPlayer = useCallback(
    (playerId: string, opts: { via?: "key" | "click" | "auto"; team?: string } = {}) => {
      if (session.complete || drafting) return;
      runDraft({ playerId, team: opts.team ?? draftingTeam, via: opts.via ?? "click" });
    },
    [session.complete, drafting, runDraft, draftingTeam],
  );
  const undoMutation = useMutation({
    mutationFn: () => api.undoPick(session.id),
    onSuccess: (row) => {
      invalidate();
      showToast({ message: `Undid ${row.name} (${row.team})` });
    },
  });
  const { mutate: runUndo } = undoMutation;
  const undo = useCallback(() => {
    if (session.picks_made > 0) runUndo();
  }, [session.picks_made, runUndo]);
  const [noise, setNoise] = useState(1);
  const [strategy, setStrategy] = useState<SimStrategy>("z");
  const simRef = useRef({ noise, strategy });
  simRef.current = { noise, strategy };
  const simMutation = useMutation({
    mutationFn: (body: { count?: number; until_my_pick: boolean }) => api.autopick(session.id, { ...body, ...simRef.current }),
    onSuccess: (r) => {
      simVersion.current = r.version;
      invalidate();
      if (r.added.length > 1) showToast({ message: `Simulated ${r.added.length} picks` });
    },
  });
  const simVersion = useRef(-1);
  const { mutate: runSim, isPending: simulating } = simMutation;
  const simulate = useCallback(
    (body: { count?: number; until_my_pick: boolean }) => {
      if (live) {
        showToast({ message: "Live draft: picks come from the feed, nothing is simulated" });
        return;
      }
      if (!session.complete && !simulating) runSim(body);
    },
    [live, session.complete, simulating, runSim, showToast],
  );
  const pickError = draftMutation.error?.message ?? undoMutation.error?.message ?? simMutation.error?.message ?? null;

  // ---------------------------------------------------------------- mock draft
  // Never in a live draft: my picks are mine to make there. In a mock the solver drafts for me
  // as soon as a solve for the current board lands, and the other teams are simulated up to my
  // next pick.
  const [mockState, setMockState] = useState(false);
  const mock = mockState && !live;
  const setMock = useCallback(
    (v: boolean) => {
      if (v && live) {
        showToast({ message: "Live draft: auto-drafting for you is off" });
        return;
      }
      setMockState(v);
    },
    [live, showToast],
  );
  const autoDraftedFor = useRef(-1);
  useEffect(() => {
    if (!mock) return;
    if (session.complete) {
      setMockState(false);
      return;
    }
    if (!session.on_the_clock) {
      // The other teams pick until my turn. Wait for the session to catch up with the last sim.
      if (!simulating && !drafting && session.version >= simVersion.current) runSim({ until_my_pick: true });
      return;
    }
    if (drafting || solveMutation.isPending || autoDraftedFor.current === session.version) return;
    const key = `${session.id}:${session.version}`;
    if (!result || result.version !== session.version) {
      if (!serverSolves && solvedFor.current !== key) {
        solvedFor.current = key;
        runSolve();
      }
      return;
    }
    const top = result.candidates[0];
    if (!top) return;
    autoDraftedFor.current = session.version;
    runDraft({ playerId: top.player, team: onClockTeam, via: "auto" });
  }, [mock, session.complete, session.on_the_clock, session.version, session.id, simulating, drafting, solveMutation.isPending, result, serverSolves, runSim, runSolve, runDraft, onClockTeam]);
  useEffect(() => {
    if (simMutation.error || draftMutation.error) setMockState(false); // stop the loop on any failure
  }, [simMutation.error, draftMutation.error]);

  // ---------------------------------------------------------------- board
  const [hideTaken, setHideTaken] = useState(true);
  const toggleHideTaken = useCallback(() => setHideTaken((v) => !v), []);
  const [highlight, setHighlight] = useState<string | null>(null);
  const visibleRows = useRef<string[]>([]);
  const setVisibleRows = useCallback((ids: string[]) => {
    visibleRows.current = ids;
  }, []);
  const moveHighlight = useCallback((delta: number) => {
    setHighlight((h) => {
      const rows = visibleRows.current;
      if (!rows.length) return null;
      let i = h ? rows.indexOf(h) : -1;
      if (i < 0) i = delta > 0 ? -1 : rows.length;
      i = Math.min(rows.length - 1, Math.max(0, i + delta));
      return rows[i];
    });
  }, []);
  const searchRef = useRef<HTMLInputElement | null>(null);

  const value: DraftApi = {
    session,
    onClockTeam,
    draftingTeam,
    setTeamOverride,
    drawer,
    drawerOpen,
    openCard,
    closeCard,
    toggleDrawer,
    collapseDrawer,
    swapHalves,
    setSplit,
    setWidth,
    settings,
    setSettings,
    result,
    stale,
    busy,
    solver: latest.data?.solver,
    solving,
    solveError: solveMutation.error?.message ?? latest.data?.solver.last_error ?? null,
    solveEvents,
    survival,
    solve,
    draftPlayer,
    drafting,
    undo,
    simulate,
    simulating,
    noise,
    setNoise,
    strategy,
    setStrategy,
    pickError,
    live,
    mock,
    setMock,
    hideTaken,
    setHideTaken,
    toggleHideTaken,
    highlight,
    setHighlight,
    moveHighlight,
    setVisibleRows,
    searchRef,
    toast,
    showToast,
    dismissToast,
    sheetOpen,
    setSheetOpen,
  };
  return <DraftContext.Provider value={value}>{children}</DraftContext.Provider>;
}

function applyClose(d: DrawerState, id: CardId): DrawerState {
  const top = d.top === id ? null : d.top;
  const bottom = d.bottom === id ? null : d.bottom;
  const empty = top === null && bottom === null;
  return { ...d, top, bottom, collapsed: empty, last: empty ? d.last : { top, bottom } };
}

const SHIFTED_DIGITS: Record<string, number> = { "!": 1, "@": 2, "#": 3, "$": 4, "%": 5, "^": 6, "&": 7 };
const TEXT_INPUTS = new Set(["text", "search", "number", "email", "password", "url", "tel"]);

/** 1 to 7 from the physical key when the browser reports it, else from the typed character. */
function cardDigit(e: KeyboardEvent): number | null {
  const physical = /^Digit([1-7])$/.exec(e.code);
  if (physical) return Number(physical[1]);
  if (/^[1-7]$/.test(e.key)) return Number(e.key);
  return SHIFTED_DIGITS[e.key] ?? null;
}

/** Global keyboard shortcuts. Letters are ignored while a field has focus; Esc leaves the field first. */
export function Hotkeys() {
  const draft = useDraft();
  const latest = useRef(draft);
  latest.current = draft;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const d = latest.current;
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      const isControl = tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || tag === "BUTTON" || tag === "A";
      // Only text entry swallows letters: a focused checkbox, slider or select must not block shortcuts.
      const typing =
        tag === "TEXTAREA" ||
        !!target?.isContentEditable ||
        (tag === "INPUT" && TEXT_INPUTS.has((target as HTMLInputElement).type));
      if (e.key === "Escape") {
        if (d.sheetOpen) d.setSheetOpen(false);
        else if (typing || tag === "SELECT") target?.blur();
        else {
          if (isControl) target?.blur();
          d.collapseDrawer();
        }
        e.preventDefault();
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "?") {
        d.setSheetOpen(!d.sheetOpen);
        e.preventDefault();
        return;
      }
      // Any shortcut used while the key sheet is open also closes the sheet, so keys can be tried from it.
      const closeSheet = () => {
        if (d.sheetOpen) d.setSheetOpen(false);
      };
      const digit = cardDigit(e);
      if (digit) {
        d.openCard(CARDS[digit - 1].id, e.shiftKey ? "bottom" : "top");
        closeSheet();
        e.preventDefault();
        return;
      }
      if (tag === "SELECT") return; // letters change the selection natively
      switch (e.key) {
        case "]":
          d.toggleDrawer();
          break;
        case "x":
          d.swapHalves();
          break;
        case "/":
          d.searchRef.current?.focus();
          d.searchRef.current?.select();
          break;
        case "ArrowDown":
        case "j":
          d.moveHighlight(1);
          break;
        case "ArrowUp":
        case "k":
          d.moveHighlight(-1);
          break;
        case "Enter":
          if (isControl || !d.highlight) return; // let the focused control act
          d.draftPlayer(d.highlight, { via: "key" });
          break;
        case "d": {
          const top = d.result?.candidates[0];
          if (!top || d.busy) return; // never draft from a stale answer
          d.draftPlayer(top.player, { via: "key" });
          break;
        }
        case "z":
          d.undo();
          break;
        case "h":
          d.toggleHideTaken();
          break;
        case "r":
          d.solve();
          break;
        case "s":
          if (d.session.on_the_clock) d.showToast({ message: "You are on the clock: make your pick first" });
          else d.simulate({ until_my_pick: true });
          break;
        case "S":
          d.simulate({ count: 1, until_my_pick: false });
          break;
        case "m":
          if (d.mock) {
            d.setMock(false);
            d.showToast({ message: "Mock draft stopped" });
          } else if (!d.live) {
            d.setMock(true);
            d.showToast({ message: "Mock draft running: other teams simulated, the solver drafts for you" });
          } else d.setMock(true); // shows the live-draft toast
          break;
        default:
          return;
      }
      closeSheet();
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return null;
}
