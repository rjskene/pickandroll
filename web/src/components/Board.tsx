import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, CAT_LABEL, CATS, teamLabel, type BoardPlayer, type Cat, type SimStrategy } from "../api";
import { useDraft } from "../draft";
import { adpIsStandIn, adpLabel, fmtCost, oddsClass } from "../format";

function heat(z: number): string | undefined {
  if (Math.abs(z) < 0.5) return undefined;
  const t = Math.min(3, Math.abs(z));
  return z > 0 ? `hsl(150 45% ${14 + t * 8}%)` : `hsl(0 45% ${14 + t * 7}%)`;
}

const NOISE = [
  { value: 0, label: "no randomness" },
  { value: 0.5, label: "a little randomness" },
  { value: 1, label: "normal randomness" },
  { value: 2, label: "wild" },
];
/** The default (draft.tsx) first: the other teams draft as the availability model assumes. */
const STRATEGIES: { value: SimStrategy; label: string; title: string }[] = [
  { value: "adp", label: "by ADP", title: "Each team takes the earliest noisy ADP slot: market ADP (keepers out of the market) with the session's spread, as the survival formula assumes" },
  { value: "z", label: "by z-score", title: "Each team takes one of the best players by total z; randomness favours the ones closest to the top" },
  { value: "lp", label: "by LP", title: "Each team solves its own roster problem (with a punt of its own) and takes the best new player from it" },
];

// ---------------------------------------------------------------- sorting
/** Any column but the Draft button. Categories sort by their z. */
type SortKey = "name" | "positions" | "games" | "adp" | "total" | "p_next" | "cost" | Cat;
type Dir = "asc" | "desc";
interface Sort {
  key: SortKey;
  dir: Dir;
}
/** The server's order: best total z first. */
const DEFAULT_SORT: Sort = { key: "total", dir: "desc" };
/** A first click sorts best first: low is best for ADP and cost, names read A to Z. */
const FIRST_DIR: Partial<Record<SortKey, Dir>> = { name: "asc", positions: "asc", adp: "asc", cost: "asc" };
const sortKey = (sessionId: string) => `pickandroll.sort.${sessionId}`;

function loadSort(sessionId: string): Sort {
  try {
    const raw = localStorage.getItem(sortKey(sessionId));
    if (raw) {
      const s = JSON.parse(raw) as Partial<Sort>;
      if (typeof s.key === "string" && (s.dir === "asc" || s.dir === "desc")) return { key: s.key as SortKey, dir: s.dir };
    }
  } catch {
    /* blocked storage: default order */
  }
  return DEFAULT_SORT;
}

function sortValue(p: BoardPlayer, key: SortKey): number | string | null {
  switch (key) {
    case "name":
      return p.name;
    case "positions":
      return p.positions || null;
    case "games":
      return p.games;
    case "adp":
      return p.adp;
    case "total":
      return p.total;
    case "p_next":
      return p.taken ? null : p.p_next;
    case "cost":
      return p.taken ? null : p.cost;
    default:
      return p.z[key];
  }
}

/** Rows in sort order. Missing values go last either way; equal values keep the server's
 * order, so drafted rows stay where their numbers put them. */
function sortRows(rows: BoardPlayer[], sort: Sort): BoardPlayer[] {
  const sign = sort.dir === "asc" ? 1 : -1;
  return rows
    .map((p, i) => ({ p, i, v: sortValue(p, sort.key) }))
    .sort((a, b) => {
      if (a.v == null || b.v == null) return a.v == null && b.v == null ? a.i - b.i : a.v == null ? 1 : -1;
      const c = typeof a.v === "string" || typeof b.v === "string" ? String(a.v).localeCompare(String(b.v)) : a.v - b.v;
      return c !== 0 ? c * sign : a.i - b.i;
    })
    .map((x) => x.p);
}

export default function Board() {
  const d = useDraft();
  const s = d.session;
  const board = useQuery({ queryKey: ["board", s.id], queryFn: () => api.board(s.id) });
  const [search, setSearch] = useState("");
  // Keepers are taken, so "available only" leaves them out too; this lists them anyway.
  const [showKeepers, setShowKeepers] = useState(false);
  const wide = !d.drawerOpen;
  // No highlight while a solve runs or the answer is stale: the name may just have been drafted.
  const recommended = d.busy ? null : (d.result?.candidates[0]?.player ?? null);

  const [sort, setSort] = useState<Sort>(() => loadSort(s.id));
  useEffect(() => {
    try {
      localStorage.setItem(sortKey(s.id), JSON.stringify(sort));
    } catch {
      /* storage unavailable */
    }
  }, [sort, s.id]);
  const sortBy = (key: SortKey) =>
    setSort((cur) => (cur.key === key ? { key, dir: cur.dir === "asc" ? "desc" : "asc" } : { key, dir: FIRST_DIR[key] ?? "desc" }));

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const shown = (board.data?.players ?? []).filter(
      (p) => (!d.availableOnly || !p.taken || (showKeepers && p.keeper)) && (!needle || p.name.toLowerCase().includes(needle)),
    );
    return sortRows(shown, sort);
  }, [board.data, search, d.availableOnly, showKeepers, sort]);
  const { setVisibleRows } = d;
  useEffect(() => {
    setVisibleRows(rows.filter((p) => !p.taken).map((p) => p.player_id));
  }, [rows, setVisibleRows]);
  useEffect(() => {
    if (d.highlight) document.querySelector("tr.hl")?.scrollIntoView({ block: "nearest" });
  }, [d.highlight]);

  const teams = Array.from({ length: s.num_teams }, (_, i) => teamLabel(s, i + 1));
  const who = (team: string) => (team === s.my_team ? "me" : team);
  const draftFirstMatch = () => {
    const first = rows.find((p) => !p.taken);
    if (first && search.trim()) d.draftPlayer(first.player_id, { via: "key" });
  };
  const nextPick = board.data?.next_pick ?? null;
  const priced = board.data?.prices_version != null;
  const scale = board.data?.scale ?? undefined;
  const busy = d.drafting || d.simulating;
  const draftRow = (p: BoardPlayer) => d.draftPlayer(p.player_id);

  /** A header cell that sorts its column: a click toggles the direction, an arrow marks the sort. */
  const th = (key: SortKey, label: string, opts: { className?: string; title?: string } = {}) => {
    const on = sort.key === key;
    return (
      <th
        key={key}
        className={[opts.className, "sortable", on ? "sorted" : ""].filter(Boolean).join(" ")}
        title={opts.title ? `${opts.title} · click to sort` : "click to sort"}
        aria-sort={on ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
        onClick={() => sortBy(key)}
      >
        {label}
        {on && <span className="arrow">{sort.dir === "asc" ? "▲" : "▼"}</span>}
      </th>
    );
  };

  return (
    <section className="panel board">
      <header className="board-head">
        <h2>BOARD</h2>
        <input
          ref={d.searchRef}
          type="search"
          placeholder="Search  /"
          title="Search (/) · Enter drafts the first match"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && draftFirstMatch()}
        />
        <label className="inline muted" title="List only the players still available (h); otherwise drafted players stay listed, struck through, with who took them">
          <input
            type="checkbox"
            checked={d.availableOnly}
            onChange={(e) => {
              d.setAvailableOnly(e.target.checked);
              e.currentTarget.blur();
            }}
          />{" "}
          available only
        </label>
        {d.availableOnly && s.keepers.length > 0 && (
          <label className="inline muted" title="List the keepers too while only available players are listed">
            <input
              type="checkbox"
              checked={showKeepers}
              onChange={(e) => {
                setShowKeepers(e.target.checked);
                e.currentTarget.blur();
              }}
            />{" "}
            show keepers
          </label>
        )}
        {!s.complete && !d.live && (
          <span className="inline muted sim" title="Simulate the other teams' picks">
            <span className="k">Sim</span>
            <button className="small" disabled={busy} onClick={() => d.simulate({ count: 1, until_my_pick: false })} title="Simulate one pick (shift+S)">
              next pick
            </button>
            <button className="small" disabled={busy || s.on_the_clock} onClick={() => d.simulate({ until_my_pick: true })} title="Simulate up to my pick (s)">
              to my pick
            </button>
            <button className={`small ${d.mock ? "primary" : ""}`} onClick={() => d.setMock(!d.mock)} title="Run the whole mock draft: the other teams are simulated, the solver drafts for you (m)">
              {d.mock ? "■ stop mock draft" : "▶ mock draft"}
            </button>
            <select
              value={d.strategy}
              onChange={(e) => {
                d.setStrategy(e.target.value as SimStrategy);
                e.currentTarget.blur();
              }}
              aria-label="Simulation strategy"
              title={STRATEGIES.find((x) => x.value === d.strategy)?.title}
            >
              {STRATEGIES.map((o) => (
                <option key={o.value} value={o.value} title={o.title}>
                  {o.label}
                </option>
              ))}
            </select>
            <select
              value={d.noise}
              onChange={(e) => {
                d.setNoise(Number(e.target.value));
                e.currentTarget.blur();
              }}
              aria-label="Simulation randomness"
            >
              {NOISE.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </span>
        )}
        <span className="grow" />
        {!s.complete && (
          <label className="inline muted">
            Pick {s.next_overall} goes to
            <select
              value={d.draftingTeam}
              onChange={(e) => {
                d.setTeamOverride(e.target.value);
                e.currentTarget.blur();
              }}
            >
              {teams.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>
      {d.pickError && <p className="error">{d.pickError}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {th("name", "Player")}
              {th("positions", "Pos")}
              {th("games", "GP", { className: "num" })}
              {wide && th("adp", `ADP${adpIsStandIn(s.adp_source) ? "*" : ""}`, { className: "num", title: `average draft position: ${adpLabel(s.adp_source)}` })}
              {th("total", "Z", { className: "num" })}
              {CATS.map((c) => th(c, CAT_LABEL[c], { className: "num" }))}
              {wide &&
                th("p_next", nextPick ? `Survives to #${nextPick}` : "Survives", {
                  title: nextPick ? `chance he is still on the board at your pick ${nextPick}` : "survival odds",
                })}
              {th("cost", "Cost", {
                className: "num",
                title: "cost of taking this player with your next pick instead of the plan's choice, on the objective's scale: exact re-solve for priced candidates, ≈ first-order estimate for the rest",
              })}
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const cls = [p.taken ? "taken" : "", p.player_id === recommended ? "reco" : "", p.player_id === d.highlight ? "hl" : ""].filter(Boolean).join(" ");
              return (
                <tr key={p.player_id} className={cls} onClick={() => !p.taken && d.setHighlight(p.player_id)}>
                  <td className={p.player_id === recommended ? "strong" : ""}>
                    {p.keeper && (
                      <span className="kmark" title={`kept by ${p.keeper}`}>
                        K
                      </span>
                    )}
                    {p.name} <span className="dim">{p.team}</span>
                    {p.taken_by ? (
                      <span className="dim by" title={`${p.keeper ? "kept" : "drafted"} by ${who(p.taken_by.team)} at pick ${p.taken_by.overall}`}>
                        {" "}
                        · {who(p.taken_by.team)} #{p.taken_by.overall}
                      </span>
                    ) : (
                      p.keeper && <span className="dim"> · {p.keeper}</span>
                    )}
                  </td>
                  <td>{p.positions || <span className="dim">?</span>}</td>
                  <td className="num">{Math.round(p.games)}</td>
                  {wide && (
                    <td className="num" title={p.keepers_ahead > 0 ? `Yahoo ADP ${p.adp?.toFixed(1)}; ${p.keepers_ahead > 1 ? `${p.keepers_ahead} keepers ranked ahead of him are` : "a keeper ranked ahead of him is"} out of the market, so it reaches him at ${p.adp_eff?.toFixed(1)}` : undefined}>
                      {p.adp == null ? "" : p.keepers_ahead > 0 && p.adp_eff != null ? `${p.adp.toFixed(0)} → ${p.adp_eff.toFixed(0)}` : p.adp.toFixed(1)}
                    </td>
                  )}
                  <td className="num strong">{p.total.toFixed(1)}</td>
                  {CATS.map((c) => (
                    <td key={c} className="num">
                      <span className="cell" style={{ background: heat(p.z[c]) }}>
                        {p.z[c].toFixed(1)}
                      </span>
                    </td>
                  ))}
                  {wide && (
                    <td>
                      {!p.taken && p.p_next != null && (
                        <span className="survival">
                          <span className="bar">
                            <span className={oddsClass(p.p_next)} style={{ width: `${Math.round(p.p_next * 100)}%` }} />
                          </span>
                          <span className="muted">{Math.round(p.p_next * 100)}%</span>
                        </span>
                      )}
                    </td>
                  )}
                  <td
                    className={`num ${p.cost != null && p.cost < 0.005 ? "good" : "muted"}`}
                    title={!p.taken && priced && p.cost != null ? (p.cost_exact ? "exact re-solve with this player taken first" : "first-order estimate from the plan's slopes, not re-solved") : ""}
                  >
                    {!p.taken && priced && p.cost != null ? fmtCost(p.cost, scale, !p.cost_exact) : ""}
                  </td>
                  <td>
                    {!p.taken && !s.complete && (
                      <button
                        className={`small ${p.player_id === recommended ? "primary" : ""}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          draftRow(p);
                        }}
                        disabled={busy}
                      >
                        Draft
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
