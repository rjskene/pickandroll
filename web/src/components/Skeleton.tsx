/** Placeholder lines shown in a card while the solver re-plans, so a stale answer (a name
 * that may just have been drafted) never sits where the fresh one will appear. */
export default function Skeleton({ rows = 6, note }: { rows?: number; note?: string }) {
  const widths = [92, 76, 84, 64, 88, 70, 80, 60, 86, 72, 78, 66, 90];
  return (
    <div className="skeleton" aria-busy="true" aria-live="polite">
      {note && <span className="accent" style={{ fontSize: 12 }}>{note}</span>}
      {Array.from({ length: rows }, (_, i) => (
        <span key={i} className="line" style={{ width: `${widths[i % widths.length]}%` }} />
      ))}
    </div>
  );
}
