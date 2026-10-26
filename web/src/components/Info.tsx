import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { outside, placePopover, POPOVER_WIDTH, WIDE_WIDTH } from "../popover";

/** The nearest ancestor that scrolls or clips: the column the button sits in. */
function columnOf(el: HTMLElement): HTMLElement | null {
  for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
    const s = getComputedStyle(n);
    if (/(auto|scroll|hidden|clip)/.test(`${s.overflowX} ${s.overflowY}`)) return n;
  }
  return null;
}

/** A small "i" button that opens a short explanation next to a label. Click toggles it; a click
 * elsewhere or Esc closes it. Inside a form label the click never reaches the label's control.
 * The explanation opens through a portal on the body (#185), above every column and the drawer,
 * so a scrolling column never clips it: below the button, or above it when there is more room
 * there, scrolling when it is taller than the room it has. It follows the button when a column
 * scrolls or the window resizes, and closes once the button leaves its column's view. With
 * ``label`` the button carries a short text beside the "i"; ``name`` overrides its accessible
 * name. */
export default function Info({
  title,
  align = "left",
  label,
  name,
  wide = false,
  children,
}: {
  title: string;
  align?: "left" | "right";
  label?: string;
  name?: string;
  wide?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement | null>(null);
  const pop = useRef<HTMLDivElement | null>(null);
  const id = useId();
  useLayoutEffect(() => {
    if (!open) return;
    let frame = 0;
    const place = () => {
      frame = 0;
      const el = pop.current;
      const btn = ref.current;
      if (!el || !btn) return;
      const b = btn.getBoundingClientRect();
      const column = columnOf(btn);
      if (column && outside(b, column.getBoundingClientRect())) {
        setOpen(false);
        return;
      }
      const p = placePopover(b, el.scrollHeight, { width: window.innerWidth, height: window.innerHeight }, align, wide ? WIDE_WIDTH : POPOVER_WIDTH);
      el.style.left = `${p.left}px`;
      el.style.width = `${p.width}px`;
      el.style.maxHeight = `${p.maxHeight}px`;
      el.style.top = p.top == null ? "auto" : `${p.top}px`;
      el.style.bottom = p.bottom == null ? "auto" : `${p.bottom}px`;
    };
    place();
    const later = (e: Event) => {
      // Its own scrolling moves nothing.
      if (e.target instanceof Node && pop.current?.contains(e.target)) return;
      if (!frame) frame = requestAnimationFrame(place);
    };
    window.addEventListener("scroll", later, true);
    window.addEventListener("resize", later);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", later, true);
      window.removeEventListener("resize", later);
    };
  }, [open, align, wide]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!ref.current?.contains(t) && !pop.current?.contains(t)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // The page's own Esc (a screen's shortcuts on the window) waits for the next one.
      e.stopPropagation();
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <span className="info" ref={ref}>
      <button
        type="button"
        className={`info-btn${label ? " labelled" : ""}`}
        aria-label={name ?? label ?? `About ${title}`}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        title={open ? "" : title}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        {label ? (
          <>
            <span className="info-i">i</span>
            {label}
          </>
        ) : (
          "i"
        )}
      </button>
      {open &&
        createPortal(
          <div
            ref={pop}
            id={id}
            className={`popover${wide ? " wide" : ""}`}
            role="dialog"
            aria-label={title}
            onClick={(e) => {
              // Neither the label's control nor a parent's click (a sortable header) sees it:
              // React carries a portal's events up its own tree.
              e.preventDefault();
              e.stopPropagation();
            }}
            // Outside its parent's DOM now: a parent's "click elsewhere closes" never sees it.
            onMouseDown={(e) => e.stopPropagation()}
          >
            {children}
          </div>,
          document.body,
        )}
    </span>
  );
}
