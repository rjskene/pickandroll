import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, CAT_LABEL, type MoveHorizon, type ProjectionSystem, type RosterRow, type SeasonView, type TradePayload, type TradeSide } from "../api";
import {
  dayLabel,
  effectiveNote,
  gainLabel,
  gainTone,
  marginText,
  movedGames,
  movedGamesTitle,
  playersById,
  rosterNote,
  statusTitle,
  statusTone,
  tradeVerdict,
} from "../season";

const HELD = new Set(["IL", "IL+", "NA"]);
const SHORT: Record<MoveHorizon, string> = { week: "+1wk", three: "+3wk" };
const HORIZONS = ["week", "three"] as const;
/** A change worth a colour. */
const SHOWN = 0.005;

const cap = (x: string) => x.charAt(0).toUpperCase() + x.slice(1);

function toggled(list: number[], id: number): number[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

function same(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x));
}

/** The Trade card (#96): a proposal between my roster and one other team's, both sides before
 * and after on the moves' horizons, each roster's slots, the margin and the traded players'
 * games. The reading is "no worse on our model", never whether they would accept; nothing here
 * proposes the trade or acts in Yahoo. */
export default function Trade({ league, s, system }: { league: string; s: SeasonView; system: ProjectionSystem }) {
  const mine = s.my_team?.team_id;
  const others = s.teams.filter((t) => t.team_id !== mine && (s.rosters[String(t.team_id)]?.length ?? 0) > 0);
  const [team, setTeam] = useState<number | null>(s.opponent?.team_id ?? others[0]?.team_id ?? null);
  const [give, setGive] = useState<number[]>([]);
  const [get, setGet] = useState<number[]>([]);
  const [effective, setEffective] = useState("");
  const evaluate = useMutation({
    mutationFn: (team: number) => api.trade(league, { team, give, get, system, effective: effective || null }),
  });
  if (mine == null) return <p className="muted">The trade needs my team: none is set for this league.</p>;
  if (!others.length || team == null) return <p className="muted">No other team&apos;s roster has been read for this league.</p>;
  const t = evaluate.data;
  const current = t != null && t.trade.team === team && same(t.trade.give, give) && same(t.trade.get, get);
  return (
    <>
      <div className="block">
        <label className="trade-with">
          <span className="k">With</span>
          <select
            value={team}
            onChange={(e) => {
              setTeam(Number(e.target.value));
              setGet([]);
            }}
            aria-label="Trade with"
          >
            {others.map((x) => (
              <option key={x.team_id} value={x.team_id}>
                {x.name}
                {x.team_id === s.opponent?.team_id ? " (this week's opponent)" : ""}
              </option>
            ))}
          </select>
        </label>
        <div className="trade-pick">
          <PickList title="I give" rows={s.roster} chosen={give} onToggle={(id) => setGive((g) => toggled(g, id))} />
          <PickList title="I get" rows={s.rosters[String(team)] ?? []} chosen={get} onToggle={(id) => setGet((g) => toggled(g, id))} />
        </div>
        <div className="trade-go">
          <label className="muted small" title="leave it empty for the day Yahoo would process the trade if accepted today">
            Effective <input type="date" value={effective} min={s.today} onChange={(e) => setEffective(e.target.value)} />
          </label>
          <span className="grow" />
          <button className="small" disabled={(!give.length && !get.length) || evaluate.isPending} onClick={() => evaluate.mutate(team)}>
            {evaluate.isPending ? "Evaluating…" : "Evaluate"}
          </button>
        </div>
      </div>
      {evaluate.error && <p className="error">{evaluate.error.message}</p>}
      {t && <TradeResult t={t} s={s} stale={!current} />}
      <p className="dim small">Nothing here proposes the trade or acts in Yahoo: the offer stays yours to make on Yahoo&apos;s pages.</p>
    </>
  );
}

function PickList({ title, rows, chosen, onToggle }: { title: string; rows: RosterRow[]; chosen: number[]; onToggle: (id: number) => void }) {
  return (
    <fieldset className="trade-side">
      <legend className="k">{title}</legend>
      {rows.map((r) => {
        const id = r.player.yahoo_id;
        const tone = statusTone(r.player);
        return (
          <label key={id} className={HELD.has(r.slot) ? "held" : undefined} title={`${r.player.nba_team ?? "no team"} · ${r.player.positions.join(", ")} · ${r.slot}`}>
            <input type="checkbox" checked={chosen.includes(id)} onChange={() => onToggle(id)} />
            <span className="name">{r.player.name}</span>
            {tone && (
              <span className={`tag ${tone}`} title={statusTitle(r.player)}>
                {r.player.status}
              </span>
            )}
            {HELD.has(r.slot) && <span className="dim">{r.slot}</span>}
          </label>
        );
      })}
    </fieldset>
  );
}

function Change({ x }: { x: number }) {
  return <td className={`num ${gainTone(x, SHOWN)}`}>{gainLabel(x)}</td>;
}

function TradeResult({ t, s, stale }: { t: TradePayload; s: SeasonView; stale: boolean }) {
  const byId = useMemo(() => playersById(s), [s]);
  const name = (id: number) => byId.get(id)?.name ?? `player ${id}`;
  const { mine, theirs } = t.sides;
  const teamName = (id: number) => (id === mine.team ? "me" : id === theirs.team ? theirs.name : `team ${id}`);
  const unread = [mine, theirs].filter((x) => !x.so_far_read);
  return (
    <>
      <div className="block">
        <span className="k" title={`expected categories won over ${t.horizons[t.lead].label}`}>
          {cap(tradeVerdict(mine.horizons[t.lead].change))} for me
        </span>
        {stale && <p className="accent small">The proposal changed since this was evaluated: evaluate again.</p>}
        <table className="season-table">
          <thead>
            <tr>
              <th></th>
              {HORIZONS.map((h) => (
                <th key={h} className="num" title={`expected categories won over ${t.horizons[h].label}: after less before`}>
                  {SHORT[h]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[mine, theirs].map((side) => (
              <SideRow key={side.team} side={side} label={side === mine ? "Me" : side.name} />
            ))}
          </tbody>
        </table>
        <p className="muted small">
          {cap(effectiveNote(t))}. This week each side plays its own opponent ({theirs.name} plays {theirs.opponent === mine.team ? "me" : (theirs.opponent_name ?? "nobody named")}); {t.horizons.three.label}.
        </p>
      </div>
      <div className="block">
        <span className="k">By category</span>
        <table className="season-table">
          <thead>
            <tr>
              <th></th>
              {HORIZONS.map((h) => (
                <th key={`m${h}`} className="num" title={`my expected wins of the category over ${t.horizons[h].label}`}>
                  me {SHORT[h]}
                </th>
              ))}
              {HORIZONS.map((h) => (
                <th key={`t${h}`} className="num" title={`${theirs.name}'s over ${t.horizons[h].label}`}>
                  them {SHORT[h]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {mine.horizons.week.cats.map((c, i) => (
              <tr key={c.cat}>
                <td>{CAT_LABEL[c.cat]}</td>
                {HORIZONS.map((h) => (
                  <Change key={`m${h}`} x={mine.horizons[h].cats[i].change} />
                ))}
                {HORIZONS.map((h) => (
                  <Change key={`t${h}`} x={theirs.horizons[h].cats[i].change} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="dim small">A category given up is an outcome here, never a target.</p>
      </div>
      <div className="block">
        <span className="k">Rosters</span>
        <p className="small">Me: {rosterNote(mine.roster, name)}</p>
        <p className="small">
          {theirs.name}: {rosterNote(theirs.roster, name)}
        </p>
        {t.fill && (
          <p className="small" title="valued beside the trade, not in it: the add is a move of its own">
            Best free agent for my open spot: {t.fill.name}, {gainLabel(t.fill.gain.three)} over weeks {t.horizons.three.weeks.join("-") || "ahead"} ({gainLabel(t.fill.gain.week)} this week) from {dayLabel(t.fill.from)}.
          </p>
        )}
      </div>
      {t.margin && (
        <div className="block">
          <span className="k">Margin</span>
          <p className="small" title={`the share of its projection what I receive could produce, over ${t.horizons[t.margin.horizon].label}, with my change still at zero`}>
            {cap(marginText(t.margin))}; at its projection my change is {gainLabel(t.margin.change)}.
          </p>
        </div>
      )}
      <div className="block">
        <span className="k">Games</span>
        <table className="season-table">
          <thead>
            <tr>
              <th>Player</th>
              <th>To</th>
              <th className="num" title="games this week for his old team, then his new one">
                wk {t.horizons.week.weeks.join("")}
              </th>
              <th className="num" title="games in the three weeks after this one, old team then new">
                wk {t.horizons.three.weeks.length ? `${t.horizons.three.weeks[0]}-${t.horizons.three.weeks[t.horizons.three.weeks.length - 1]}` : "—"}
              </th>
            </tr>
          </thead>
          <tbody>
            {t.players.map((p) => (
              <tr key={p.player}>
                <td>{p.name}</td>
                <td>{teamName(p.to)}</td>
                {HORIZONS.map((h) => (
                  <td key={h} className="num" title={movedGamesTitle(p, h, teamName(p.from), teamName(p.to))}>
                    {movedGames(p, h)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {unread.length > 0 && (
          <p className="dim small">The week so far was not read for {unread.map((x) => (x === mine ? "me" : x.name)).join(" or ")}: this week counts from the rest of it alone.</p>
        )}
        {t.system.fallback && <p className="dim small">{t.system.fallback}.</p>}
      </div>
    </>
  );
}

function SideRow({ side, label }: { side: TradeSide; label: string }) {
  return (
    <tr>
      <td title={HORIZONS.map((h) => `${h === "week" ? "this week" : "weeks after"} ${side.horizons[h].before.toFixed(2)} → ${side.horizons[h].after.toFixed(2)}`).join(" · ")}>
        {label}
      </td>
      {HORIZONS.map((h) => (
        <Change key={h} x={side.horizons[h].change} />
      ))}
    </tr>
  );
}
