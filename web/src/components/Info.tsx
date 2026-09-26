import { useEffect, useRef, useState, type ReactNode } from "react";

/** A small "i" button that opens a short explanation next to a label. Click toggles it; a click
 * elsewhere or Esc closes it. Inside a form label the click never reaches the label's control. */
export default function Info({ title, align = "left", children }: { title: string; align?: "left" | "right"; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
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
        <span className={`popover ${align}`} role="dialog" aria-label={title} onClick={(e) => e.preventDefault()}>
          {children}
        </span>
      )}
    </span>
  );
}
