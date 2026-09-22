// Draft-screen state shared by the board, the drawer cards, the rail and the hotkeys:
// which cards are open, the current recommendation and its settings, pick mutations,
// the board highlight, toasts and the shortcut sheet.
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
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, pickOwner, teamLabel, type Cat, type Recommendation, type SessionSummary, type SolveEvent } from "./api";
import { parsePunt } from "./format";

export type CardId = "pick" | "alts" | "plan" | "team" | "log" | "solver";
export type Half = "top" | "bottom";

export const CARDS: { id: CardId; title: string; blurb: string }[] = [
  { id: "pick", title: "Pick", blurb: "recommended pick" },
  { id: "alts", title: "Alternatives", blurb: "priced alternatives" },
  { id: "plan", title: "Plan", blurb: "plan for the remaining picks" },
  { id: "team", title: "Team", blurb: "expected profile and roster" },
  { id: "log", title: "Log", blurb: "every pick so far" },
  { id: "solver", title: "Solver", blurb: "timings, punt strategies, settings" },
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
}
const DRAWER_KEY = "pickandroll.drawer";
const DEFAULT_DRAWER: DrawerState = { top: "pick", bottom: "team", collapsed: false, split: 0.5, last: { top: "pick", bottom: "team" } };
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
        last: d.last && (isCard(d.last.top) || isCard(d.last.bottom)) ? { top: isCard(d.last.top) ? d.last.top : null, bottom: isCard(d.last.bottom) ? d.last.bottom : null } : { top, bottom },
      };
    }
  } catch {
    /* blocked storage: defaults */
  }
  return DEFAULT_DRAWER;
}

export interface Settings {
  auto: boolean;
  punt: Cat[];
  maxPunts: number;
  balance: number;
  n: number;
  refreshOnPick: boolean;
  horizon: boolean;
}
const DEFAULT_SETTINGS: Settings = { auto: true, punt: [], maxPunts: 2, balance: 0, n: 8, refreshOnPick: true, horizon: true };

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
  // recommendation
  settings: Settings;
  setSettings: (patch: Partial<Settings>) => void;
  result: Recommendation | undefined;
  solving: boolean;
  solveError: string | null;
  solveEvents: SolveEvent[];
  solve: () => void;
  pinPunt: (label: string) => void;
  // picks
  draftPlayer: (playerId: string, opts?: { via?: "key" | "click" | "auto"; team?: string }) => void;
  drafting: boolean;
  undo: () => void;
  simulate: (body: { count?: number; until_my_pick: boolean }) => void;
  simulating: boolean;
  noise: number;
  setNoise: (n: number) => void;
  pickError: string | null;
  /** Draft the recommended pick as soon as the solve finishes whenever I am on the clock. */
  autopilot: boolean;
  setAutopilot: (v: boolean) => void;
  /** Run the whole draft: simulate the other teams, autopilot my picks, until complete. */
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
  children: ReactNode;
}

export function DraftProvider({ session, solveEvents, children }: ProviderProps) {
  const queryClient = useQueryClient();
  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["session", session.id] });
    queryClient.invalidateQueries({ queryKey: ["board", session.id] });
    queryClient.invalidateQueries({ queryKey: ["picks", session.id] });
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
  const [settings, setSettingsState] = useState<Settings>(DEFAULT_SETTINGS);
  const setSettings = useCallback((patch: Partial<Settings>) => setSettingsState((s) => ({ ...s, ...patch })), []);
  const params = useMemo(
    () => ({ n: settings.n, punt: settings.auto ? null : settings.punt, max_punts: settings.maxPunts, balance: settings.balance, horizon: settings.horizon }),
    [settings],
  );
  const paramsRef = useRef(params);
  paramsRef.current = params;
  const recommend = useMutation({ mutationFn: () => api.recommend(session.id, paramsRef.current) });
  const { mutate: runSolve } = recommend;
  const solve = useCallback(() => runSolve(), [runSolve]);
  const solvedFor = useRef("");
  useEffect(() => {
    const key = `${session.id}:${session.version}`;
    if (settings.refreshOnPick && !session.complete && solvedFor.current !== key) {
      solvedFor.current = key;
      runSolve();
    }
  }, [session.id, session.version, session.complete, settings.refreshOnPick, runSolve]);
  const pinPunt = useCallback(
    (label: string) => {
      setSettingsState((s) => ({ ...s, auto: false, punt: parsePunt(label) }));
      window.setTimeout(() => runSolve(), 0);
    },
    [runSolve],
  );

  // ---------------------------------------------------------------- picks
  const draftMutation = useMutation({
    mutationFn: (v: { playerId: string; team: string; via: "key" | "click" | "auto" }) =>
      api.addPick(session.id, { team: v.team, player_id: v.playerId }),
    onSuccess: (row, v) => {
      setTeamOverride(null);
      invalidate();
      if (v.via === "key") showToast({ message: `Drafted ${row.name} to ${row.team}`, undo: true });
      if (v.via === "auto") showToast({ message: `Autopilot drafted ${row.name} (pick ${row.overall})`, undo: true });
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
  const noiseRef = useRef(noise);
  noiseRef.current = noise;
  const simMutation = useMutation({
    mutationFn: (body: { count?: number; until_my_pick: boolean }) => api.autopick(session.id, { ...body, noise: noiseRef.current }),
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
      if (!session.complete && !simulating) runSim(body);
    },
    [session.complete, simulating, runSim],
  );
  const pickError = draftMutation.error?.message ?? undoMutation.error?.message ?? simMutation.error?.message ?? null;

  // ---------------------------------------------------------------- autopilot and mock draft
  const [autopilot, setAutopilot] = useState(false);
  const [mock, setMock] = useState(false);
  const autoDraftedFor = useRef(-1);
  const { data: latestResult, isPending: solvePending } = recommend;
  useEffect(() => {
    if (session.complete) {
      if (mock) setMock(false);
      return;
    }
    if (!session.on_the_clock) {
      // Mock draft: the other teams pick until my turn. Wait for the session to catch up with the last sim.
      if (mock && !simulating && !drafting && session.version >= simVersion.current) runSim({ until_my_pick: true });
      return;
    }
    if (!(autopilot || mock) || drafting || solvePending) return;
    if (autoDraftedFor.current === session.version) return;
    const key = `${session.id}:${session.version}`;
    if (!latestResult || latestResult.version !== session.version) {
      if (solvedFor.current !== key) {
        solvedFor.current = key;
        runSolve();
      }
      return;
    }
    const top = latestResult.candidates[0];
    if (!top) return;
    autoDraftedFor.current = session.version;
    runDraft({ playerId: top.player, team: onClockTeam, via: "auto" });
  }, [session.complete, session.on_the_clock, session.version, session.id, mock, autopilot, simulating, drafting, solvePending, latestResult, runSim, runSolve, runDraft, onClockTeam]);
  useEffect(() => {
    if (simMutation.error || draftMutation.error) setMock(false); // stop the loop on any failure
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
    settings,
    setSettings,
    result: recommend.data,
    solving: recommend.isPending,
    solveError: recommend.error?.message ?? null,
    solveEvents,
    solve,
    pinPunt,
    draftPlayer,
    drafting,
    undo,
    simulate,
    simulating,
    noise,
    setNoise,
    pickError,
    autopilot,
    setAutopilot,
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

const SHIFTED_DIGITS: Record<string, number> = { "!": 1, "@": 2, "#": 3, "$": 4, "%": 5, "^": 6 };
const TEXT_INPUTS = new Set(["text", "search", "number", "email", "password", "url", "tel"]);

/** 1 to 6 from the physical key when the browser reports it, else from the typed character. */
function cardDigit(e: KeyboardEvent): number | null {
  const physical = /^Digit([1-6])$/.exec(e.code);
  if (physical) return Number(physical[1]);
  if (/^[1-6]$/.test(e.key)) return Number(e.key);
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
          if (!top || d.solving) return;
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
        case "a":
          d.setAutopilot(!d.autopilot);
          d.showToast({ message: d.autopilot ? "Autopilot off" : "Autopilot on: your picks draft themselves when the solve finishes" });
          break;
        case "m":
          d.setMock(!d.mock);
          d.showToast({ message: d.mock ? "Mock draft stopped" : "Mock draft running: other teams by ADP, you by the solver" });
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
