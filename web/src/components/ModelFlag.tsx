import { useDraft } from "../draft";

const ROSTER_TITLE =
  "This solve could not build the horizon plan (every remaining pick, each priced with the odds the " +
  "player survives to it), so it planned a single roster without pick timing. Its scores and picks " +
  "are not comparable with the horizon plan's.";

/** Which model produced the latest solve: a quiet "horizon" badge, or an unmissable red flag
 * with the reason when the solver fell back to the single-roster model. ``banner`` spreads the
 * fallback across its container; the horizon badge stays small either way. */
export default function ModelFlag({ banner = false }: { banner?: boolean }) {
  const d = useDraft();
  const r = d.result;
  if (!r) return null;
  // The sum-objective fallback of a curve plan is a different thing: a secondary note.
  const sum = r.fallback ? <span className="sum" title={r.fallback}>objective fell back to sum</span> : null;
  if (r.mode === "horizon") {
    return (
      <span className="model-flag horizon" title="The latest solve ran the horizon plan: every remaining pick, priced with survival odds">
        <span className="badge">horizon</span>
        {sum}
      </span>
    );
  }
  const why = r.roster_reason ?? (d.settings.horizon ? "the horizon plan was not run" : "\"plan all remaining picks\" is off in Settings");
  return (
    <span className={`model-flag roster${banner ? " banner" : ""}`} role="status" title={ROSTER_TITLE}>
      <span className="badge">Single-roster fallback</span>
      <span className="why">{why}</span>
      {sum}
    </span>
  );
}
