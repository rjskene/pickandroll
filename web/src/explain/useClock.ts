// The clock under an animated frame (#283): plays on requestAnimationFrame at `speed` axis
// units a second, scrubs, steps from event to event; under reduced motion it stands on the
// final frame with play disabled.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { nextEvent, prevEvent } from "./lane";

export interface ClockOptions {
  min: number;
  max: number;
  /** Axis units a second of play. */
  speed: number;
  /** The instants prev and next step between, ascending. */
  events: number[];
}

export interface Clock {
  t: number;
  playing: boolean;
  reduced: boolean;
  /** Scrub to `v` (play stops). */
  set: (v: number) => void;
  /** Play or pause; from the end, play starts over. */
  toggle: () => void;
  prev: () => void;
  next: () => void;
}

export const reducedMotion = (): boolean => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function useClock({ min, max, speed, events }: ClockOptions): Clock {
  const reduced = useMemo(reducedMotion, []);
  const [t, setT] = useState(reduced ? max : min);
  const [playing, setPlaying] = useState(false);
  const at = useRef(reduced ? max : min);
  const set = useCallback(
    (v: number) => {
      const c = Math.max(min, Math.min(max, v));
      at.current = c;
      setT(c);
    },
    [min, max],
  );
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      if (!last) last = now;
      const v = at.current + ((now - last) / 1000) * speed;
      last = now;
      if (v >= max) {
        set(max);
        setPlaying(false);
        return;
      }
      set(v);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, max, set]);
  const toggle = useCallback(() => {
    if (reduced) return;
    if (playing) setPlaying(false);
    else {
      if (at.current >= max) set(min);
      setPlaying(true);
    }
  }, [playing, reduced, max, min, set]);
  const scrub = useCallback(
    (v: number) => {
      setPlaying(false);
      set(v);
    },
    [set],
  );
  const prev = useCallback(() => {
    setPlaying(false);
    set(prevEvent(events, at.current, min));
  }, [events, min, set]);
  const next = useCallback(() => {
    setPlaying(false);
    set(nextEvent(events, at.current, max));
  }, [events, max, set]);
  return { t, playing, reduced, set: scrub, toggle, prev, next };
}
