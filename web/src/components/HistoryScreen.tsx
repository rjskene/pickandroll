import { Fragment, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type HistoryRow } from "../api";
import { bidText, filterRows, KIND_WORDS, moveLine, NO_FILTER, RESULT_TONE, whyLines, type HistoryFilter } from "../history";
import { queueKeys } from "../keys";
import { dayLabel } from "../season";
import { useHotkeys } from "../useKeys";
import { LeaguesIcon } from "./icons";
import AppBarLead from "./AppBarLead";
import { useLandingOrder } from "./landingOrder";
import { OverviewStatus } from "./StatusLight";
import { useNow } from "./YahooSync";

/** The History screen (#334) at /history: every move and trade in every league, the private one
 * too, newest first, each opening to why it was made. It reads only. */
export default function HistoryScreen({ onBack, onOpenLeague, onProgress, onExplain }: { onBack: () => void; onOpenLeague: (league: string) => void; onProgress: () => void; onExplain: () => void }) {
  const q = useQuery({ queryKey: ["history"], queryFn: () => api.history() });
  const seasons = useQuery({ queryKey: ["seasons"], queryFn: api.seasons, refetchInterval: 60_000 });
  const now = useNow(30_000);
  const landing = useLandingOrder();
  const leagues = [...landing.rows.pinned, ...landing.rows.rest];
  const [filter, setFilter] = useState<HistoryFilter>(NO_FILTER);
  const [open, setOpen] = useState<string | null>(null);
  useHotkeys(queueKeys(onBack));
  const p = q.data;
  const title = useMemo(() => {
    const names = new Map((seasons.data ?? []).map((s) => [s.league, s.name]));
    return (league: string) => names.get(league) ?? `league ${league}`;
  }, [seasons.data]);
  const name = useMemo(() => {
    const names = p?.names ?? {};
    return (id: number | null | undefined) => (id == null ? "" : (names[String(id)] ?? `player ${id}`));
  }, [p]);
  const shown = useMemo(() => filterRows(p?.rows ?? [], filter), [p, filter]);
  const ids = useMemo(() => [...new Set((p?.rows ?? []).map((r) => r.league))], [p]);
  return (
    <main className="shell">
      <header className="topbar season-top">
        <AppBarLead onHome={onBack} status={<OverviewStatus leagues={leagues} now={now} />} onProgress={onProgress} onExplain={onExplain} />
        <span className="muted title">History</span>
        <span className="grow" />
        <button className="icon" onClick={onBack} aria-label="All leagues" title="All leagues (Esc)">
          <LeaguesIcon />
        </button>
      </header>
      {q.error && <p className="error" style={{ padding: "0 24px" }}>{q.error.message}</p>}
      {!p ? (
        <p className="muted" style={{ padding: 24 }}>
          Reading the record…
        </p>
      ) : (
        <div className="landing-grid qs">
          <div className="hs-filters row" role="group" aria-label="Filters">
            <label>
              <span className="k">League</span>
              <select value={filter.league ?? ""} onChange={(e) => setFilter({ ...filter, league: e.target.value || null })}>
                <option value="">All</option>
                {ids.map((id) => (
                  <option key={id} value={id}>
                    {title(id)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="k">Kind</span>
              <select value={filter.kind ?? ""} onChange={(e) => setFilter({ ...filter, kind: (e.target.value || null) as HistoryRow["kind"] | null })}>
                <option value="">All</option>
                {p.kinds.map((k) => (
                  <option key={k} value={k}>
                    {KIND_WORDS[k]}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="k">Result</span>
              <select value={filter.result ?? ""} onChange={(e) => setFilter({ ...filter, result: (e.target.value || null) as HistoryRow["result"] | null })}>
                <option value="">All</option>
                {p.results.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </label>
            <span className="muted small">
              {shown.length} of {p.rows.length}
            </span>
          </div>
          {p.skipped.map((s) => (
            <p key={s.league} className="error small">
              {title(s.league)} did not read: {s.reason}
            </p>
          ))}
          {shown.length === 0 ? (
            <p className="dim small">Nothing matches.</p>
          ) : (
            <div className="qs-scroll">
              <table className="season-table qs-table hs-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>League</th>
                    <th>Kind</th>
                    <th>Move</th>
                    <th className="num">Bid</th>
                    <th>Result</th>
                    <th>By</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <Fragment key={r.id}>
                      <tr className="hs-row" onClick={() => setOpen(open === r.id ? null : r.id)}>
                        <td>
                          <button className="link" aria-expanded={open === r.id} onClick={(e) => (e.stopPropagation(), setOpen(open === r.id ? null : r.id))}>
                            {open === r.id ? "▾" : "▸"} {dayLabel(r.date) || "no date"}
                          </button>
                        </td>
                        <td>
                          <button className="link" title="open the league" onClick={(e) => (e.stopPropagation(), onOpenLeague(r.league))}>
                            {title(r.league)}
                          </button>
                        </td>
                        <td>{r.unread ? "unread trade" : KIND_WORDS[r.kind]}</td>
                        <td>{moveLine(r, name)}</td>
                        <td className="num">{bidText(r.bid)}</td>
                        <td className={RESULT_TONE[r.result]}>{r.unread ? "" : r.result}</td>
                        <td className="muted">{r.who ?? ""}</td>
                      </tr>
                      {open === r.id && (
                        <tr className="hs-why">
                          <td colSpan={7}>
                            {whyLines(r, name).map((line, i) => (
                              <p key={i}>{line}</p>
                            ))}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </main>
  );
}
