// Shared SVG bits for the figures and the strip (#284): an arrowhead marker.
export function Arrow({ id, accent }: { id: string; accent?: boolean }) {
  return (
    <defs>
      <marker id={id} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
        <path d="M0 0L10 5L0 10z" className={accent ? "ex-arrowhead ac" : "ex-arrowhead"} />
      </marker>
    </defs>
  );
}
