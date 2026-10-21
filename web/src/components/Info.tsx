import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** A small "i" button that opens a short explanation next to a label. Click toggles it; a click
 * elsewhere or Esc closes it. Inside a form label the click never reaches the label's control.
 * The explanation opens below the button, or above it when there is more room there, and
 * scrolls when it is taller than the room it has. */
export default function Info({ title, align = "left", children }: { title: string; align?: "left" | "right"; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement | null>(null);
  const pop = useRef<HTMLSpanElement | null>(null);
  useLayoutEffect(() => {
    const el = pop.current;
    if (!open || !el || !ref.current) return;
    const b = ref.current.getBoundingClientRect();
    const below = window.innerHeight - b.bottom - 16;
    const above = b.top - 16;
    const up = el.scrollHeight > below && above > below;
    el.classList.toggle("up", up);
    el.style.maxHeight = `${Math.max(120, up ? above : below)}px`;
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
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
        className="info-btn"
        aria-label={`About ${title}`}
        aria-expanded={open}
        title={open ? "" : title}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        i
      </button>
      {open && (
        <span
          ref={pop}
          className={`popover ${align}`}
          role="dialog"
          aria-label={title}
          onClick={(e) => {
            // Neither the label's control nor a parent's click (a sortable header) sees it.
            e.preventDefault();
            e.stopPropagation();
          }}
        >
          {children}
        </span>
      )}
    </span>
  );
}
