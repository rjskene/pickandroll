// Whether a frame is narrow enough for the phone layout (under 560 px), by its own width.
import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

export const PHONE_WIDTH = 560;

export function usePhone<T extends HTMLElement>(): [RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [phone, setPhone] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => setPhone(el.getBoundingClientRect().width < PHONE_WIDTH);
    read();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, phone];
}
