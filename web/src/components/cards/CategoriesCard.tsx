import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, CAT_LABEL, type Cat, type CategoryRow } from "../../api";
import { useDraft } from "../../draft";
import { fmtSlope, labelClass, pct } from "../../format";

function heat(z: number): string | undefined {
  if (Math.abs(z) < 1) return undefined;
  const t = Math.min(4, Math.abs(z) / 3);
  return z > 0 ? `hsl(150 45% ${14 + t * 8}%)` : `hsl(0 45% ${14 + t * 7}%)`;
}

/** The centrepiece: one row per category with my drafted total, the plan's expected final,
 * the odds of winning it, the opponents beaten, and the marginal value of one more z there. */
export default function CategoriesCard() {
  const d = useDraft();
  const s = d.session;
  const result = d.result;
  const teams = useQuery({ queryKey: ["teams", s.id], queryFn: () => api.teams(s.id) });
  const [view, setView] = useState<"totals" | "projected">("projected");
  const rows: CategoryRow[] | undefined = result?.categories;
  const opponents = s.num_teams - 1;
  const conceded = rows?.filter((r) => r.label === "conceded").map((r) => CAT_LABEL[r.cat]) ?? [];
  const secured = rows?.filter((r) => r.label === "secured").map((r) => CAT_LABEL[r.cat]) ?? [];
  return (
    <>
      <div className="block">
        <div className="row">
          <span className="k">
            {result ? `Expected ${result.wins.toFixed(2)} of ${s.cats.length} categories · ${result.league.matchups_won} of ${opponents} matchups` : "Categories"}
          </span>
          <span className="muted" style={{ fontSize: 11 }}>
            {result ? `if the plan holds · ${result.availability_source === "survival" ? "simulated odds" : "ADP odds"}` : d.solving ? "solving…" : "appears after the first solve"}
          </span>
        </div>
        {d.stale && <p className="accent" style={{ fontSize: 12 }}>Board moved since this solve · re-planning…</p>}
        {rows && (
          <table className="cats">
            <thead>
              <tr>
                <th></th>
                <th className="num" title="z total of the players already drafted">Drafted</th>
                <th className="num" title="expected final z total if the plan holds">Final</th>
                <th title="chance the final total beats a team drawn from the league">Win odds</th>
                <th className="num" title={`opponents my drafted total beats now / my expected final beats at the end (of ${opponents})`}>Beat</th>
                <th className="num" title="marginal value: categories won per one more z-point here, where the next pick should invest">Marginal</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.cat} className={`lbl-${r.label}`}>
                  <td className="lbl">{CAT_LABEL[r.cat]}</td>
                  <td className="num">{r.drafted.toFixed(1)}</td>
                  <td className="num strong">{r.expected.toFixed(1)}</td>
                  <td>
                    <span className="survival">
                      <span className="bar">
                        <span className={labelClass(r.label)} style={{ width: pct(r.odds) }} />
                      </span>
                      <span className={labelClass(r.label)}>{pct(r.odds)}</span>
                    </span>
                  </td>
                  <td className="num">
                    {r.beaten_now}/{r.beaten_expected}
                  </td>
                  <td className="num">{fmtSlope(r.slope)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {rows && (
          <span className="muted" style={{ fontSize: 11 }}>
            {conceded.length ? `Conceding ${conceded.join(", ")} as the board stands` : "Nothing conceded"}
            {secured.length ? ` · secured ${secured.join(", ")}` : ""} · a punt is an outcome here, never a goal.
          </span>
        )}
      </div>
      <div className="block">
        <div className="row">
          <span className="k">League</span>
          <span className="muted inline" style={{ fontSize: 11 }}>
            <button className={`switch ${view === "totals" ? "on" : ""}`} onClick={() => setView("totals")}>drafted</button>
            <button className={`switch ${view === "projected" ? "on" : ""}`} onClick={() => setView("projected")}>projected</button>
          </span>
        </div>
        {teams.data ? (
          <div className="table-wrap" style={{ maxHeight: 320 }}>
            <table className="league">
              <thead>
                <tr>
                  <th>Team</th>
                  <th className="num">#</th>
                  {teams.data.cats.map((c) => (
                    <th key={c} className="num">
                      {CAT_LABEL[c as Cat]}
                    </th>
                  ))}
                  <th className="num" title="categories in which my projected final leads this team">vs me</th>
                </tr>
              </thead>
              <tbody>
                {teams.data.teams.map((t) => (
                  <tr key={t.team} className={t.mine ? "mine" : ""}>
                    <td className={t.mine ? "strong" : ""}>{t.team}</td>
                    <td className="num dim">{t.picks}</td>
                    {teams.data!.cats.map((c) => {
                      const v = (view === "totals" ? t.totals : t.projected)[c as Cat];
                      return (
                        <td key={c} className="num">
                          <span className="cell" style={{ background: heat(v) }}>
                            {v.toFixed(1)}
                          </span>
                        </td>
                      );
                    })}
                    <td className={`num ${t.mine ? "" : t.won ? "good" : "bad"}`}>{t.mine ? "" : `${s.cats.length - (t.cats_beaten ?? 0)}–${t.cats_beaten ?? 0}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">Loading…</p>
        )}
        {teams.data && (
          <span className="muted" style={{ fontSize: 11 }}>
            Projected = drafted plus replacement-level fill for open slots; my row uses the plan ({teams.data.my_final_from}). Each cell is the team's z total; vs me reads as their wins–losses against my projected final.
          </span>
        )}
      </div>
    </>
  );
}
