// The hooks behind the card rail (#109): a screen's two-half drawer, kept in the browser, and its
// keyboard shortcuts on the window. The state changes and the key handler are in keys.ts.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  clampSplit,
  closeCard as closed,
  handleKey,
  isOpen,
  MIN_DRAWER_WIDTH,
  openCard as opened,
  parseDrawer,
  parseViews,
  replaceCard as replaced,
  swapHalves as swapped,
  toggleDrawer as toggled,
  type DrawerState,
  type Half,
  type KeyMap,
  type Pair,
  type SeasonViewId,
  type Views,
} from "./keys";

/** Between the minimum and six tenths of the window, so the board always keeps room. */
export function clampWidth(px: number): number {
  const max = Math.max(MIN_DRAWER_WIDTH, Math.round(window.innerWidth * 0.6));
  return Math.min(max, Math.max(MIN_DRAWER_WIDTH, Math.round(px)));
}

export interface DrawerApi<Id extends string> {
  drawer: DrawerState<Id>;
  drawerOpen: boolean;
  openCard: (id: Id, half?: Half) => void;
  closeCard: (id: Id) => void;
  toggleDrawer: () => void;
  collapseDrawer: () => void;
  swapHalves: () => void;
  setSplit: (ratio: number) => void;
  setWidth: (px: number) => void;
  /** Show ``to`` in the half ``from`` holds, else on top. */
  replaceCard: (from: Id, to: Id) => void;
}

/** A two-half drawer saved under ``storageKey``; ``fallback`` is what `]` opens when the drawer
 * never had a pair. */
export function useDrawer<Id extends string>(
  storageKey: string,
  isCard: (v: unknown) => v is Id,
  defaults: DrawerState<Id>,
  fallback: Pair<Id>,
): DrawerApi<Id> {
  const [drawer, setDrawer] = useState<DrawerState<Id>>(() => {
    try {
      return parseDrawer(localStorage.getItem(storageKey), isCard, defaults, clampWidth);
    } catch {
      return defaults; // blocked storage
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(drawer));
    } catch {
      /* storage unavailable */
    }
  }, [storageKey, drawer]);
  const openCard = useCallback((id: Id, half: Half = "top") => setDrawer((d) => opened(d, id, half)), []);
  const closeCard = useCallback((id: Id) => setDrawer((d) => closed(d, id)), []);
  const fallbackRef = useRef(fallback);
  const toggleDrawer = useCallback(() => setDrawer((d) => toggled(d, fallbackRef.current)), []);
  const collapseDrawer = useCallback(() => setDrawer((d) => ({ ...d, collapsed: true })), []);
  const swapHalves = useCallback(() => setDrawer((d) => swapped(d)), []);
  const setSplit = useCallback((ratio: number) => setDrawer((d) => ({ ...d, split: clampSplit(ratio) })), []);
  const setWidth = useCallback((px: number) => setDrawer((d) => ({ ...d, width: clampWidth(px) })), []);
  const replaceCard = useCallback((from: Id, to: Id) => setDrawer((d) => replaced(d, from, to)), []);
  return {
    drawer,
    drawerOpen: isOpen(drawer),
    openCard,
    closeCard,
    toggleDrawer,
    collapseDrawer,
    swapHalves,
    setSplit,
    setWidth,
    replaceCard,
  };
}

export interface ViewsApi extends Views {
  setView: (view: SeasonViewId) => void;
  toggleViews: () => void;
}

/** The league page's view and its drawer (#116), saved under ``storageKey`` as the panel is. */
export function useViews(storageKey: string): ViewsApi {
  const [views, setViews] = useState<Views>(() => {
    try {
      return parseViews(localStorage.getItem(storageKey));
    } catch {
      return parseViews(null); // blocked storage
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(views));
    } catch {
      /* storage unavailable */
    }
  }, [storageKey, views]);
  const setView = useCallback((view: SeasonViewId) => setViews((v) => ({ ...v, view })), []);
  const toggleViews = useCallback(() => setViews((v) => ({ ...v, shown: !v.shown })), []);
  return { ...views, setView, toggleViews };
}

/** A screen's shortcuts on the window, read from the latest ``map`` on every key. */
export function useHotkeys(map: KeyMap): void {
  const latest = useRef(map);
  latest.current = map;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (handleKey(e, latest.current)) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
