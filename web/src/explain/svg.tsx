// Shared SVG pieces for the figures (#284): an arrowhead marker, muted by default, accent or red
// (#286) when asked. One per figure, since a marker's id must be unique on the page.
export function Arrow({ id, accent, bad }: { id: string; accent?: boolean; bad?: boolean }) {
  const tone = accent ? " ac" : bad ? " bad" : "";
  return (
    <defs>
      <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
        <path d="M0 0L10 5L0 10z" className={`ex-arrowhead${tone}`} />
      </marker>
    </defs>
  );
}
