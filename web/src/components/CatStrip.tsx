import { CAT_LABEL, type CategoryRow, type WinLabel } from "../api";
import { pct } from "../format";

const GROUPS: { label: WinLabel; title: string; cls: string }[] = [
  { label: "conceded", title: "conceding", cls: "bad" },
  { label: "secured", title: "secured", cls: "good" },
  { label: "contested", title: "contested", cls: "accent" },
];

/** Where the plan's final totals land, as category chips: conceded (under 15% to win), secured
 * (over 85%) and contested. A concession is an outcome of the best roster found, never a goal. */
export default function CatStrip({ rows }: { rows: CategoryRow[] }) {
  return (
    <div className="catstrip" title="From the plan's expected finals: conceded = under 15% to win, secured = over 85%. A concession is an outcome of the best roster the solver found, never a goal it is given.">
      {GROUPS.map((g) => {
        const cats = rows.filter((r) => r.label === g.label);
        if (!cats.length) return g.label === "conceded" ? <span key={g.label} className="k good">nothing conceded</span> : null;
        return (
          <span key={g.label} className="group">
            <span className={`k ${g.cls}`}>{g.title}</span>
            {cats.map((r) => (
              <span key={r.cat} className={`tag ${g.cls}`} title={`${CAT_LABEL[r.cat]}: ${pct(r.odds)} to win`}>
                {CAT_LABEL[r.cat]}
              </span>
            ))}
          </span>
        );
      })}
    </div>
  );
}
