import { useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import { api, teamLabel, type GapPick } from "../../api";
import { useDraft } from "../../draft";
import { GapMark, SessionKeepers } from "../Keepers";
import { byTeam, draftOrder, logItems, type LogItem } from "./logRows";

type Order = "draft" | "team";
const ORDER_KEY = "pickandroll.logOrder";

function savedOrder(): Order {
  try {
    return localStorage.getItem(ORDER_KEY) === "team" ? "team" : "draft";
  } catch {
    return "draft";
  }
}

export default function LogCard() {
  const d = useDraft();
  const s = d.session;
  const picks = useQuery({ queryKey: ["picks", s.id], queryFn: () => api.picks(s.id) });
  const made = picks.data ?? [];
  // A keeper's pick is never the undo target: it would be logged again at once.
  const realPicks = made.filter((p) => !p.keeper).length;
  const gaps = new Map(d.gaps.map((g) => [g.overall, g]));
  const items = logItems(made, s.keepers, s.my_team);
  const [order, setOrderState] = useState<Order>(savedOrder);
  const setOrder = (o: Order) => {
    setOrderState(o);
    try {
      localStorage.setItem(ORDER_KEY, o);
    } catch {
      // The order is a convenience; without storage it resets on reload.
    }
  };
  // The keeper editor sits behind a disclosure; a gap's mark asking for its keeper opens it.
  const [editOpen, setEditOpen] = useState(false);
  const request = d.keeperRequest;
  useEffect(() => {
    if (request !== null) setEditOpen(true);
  }, [request]);
  // Keepers to come more than a round ahead fold into one row, so the latest picks stay on top.
  const [showAhead, setShowAhead] = useState(false);
  const { ahead, rows } = draftOrder(items, s.next_overall, s.num_teams);
  const teams = Array.from({ length: s.num_teams }, (_, i) => teamLabel(s, i + 1));
  return (
    <>
      <div className="row">
        <span className="k">
          {made.length} of {s.num_teams * s.roster_size} picks
        </span>
        <span className="grow" />
        <span className="seg" role="group" aria-label="Log order">
          <button className={order === "draft" ? "on" : ""} aria-pressed={order === "draft"} onClick={() => setOrder("draft")} title="Newest pick first">
            Draft order
          </button>
          <button className={order === "team" ? "on" : ""} aria-pressed={order === "team"} onClick={() => setOrder("team")} title="Teams in draft-position order, each team's picks in order">
            By team
          </button>
        </span>
        <button className="small" onClick={d.undo} disabled={!realPicks} title="Undo the last pick (z); keeper picks behind it come off with it">
          Undo last <kbd>z</kbd>
        </button>
      </div>
      {items.length === 0 && <p className="muted" style={{ margin: 0 }}>No picks yet.</p>}
      {order === "draft" ? (
        <ol className="picklog">
          {ahead.length > 0 && (
            <li className="to-come ahead">
              <button className="link" onClick={() => setShowAhead((v) => !v)} aria-expanded={showAhead}>
                {showAhead ? "▾" : "▸"} {ahead.length} {ahead.length === 1 ? "keeper" : "keepers"} to come
              </button>
              <span style={{ marginLeft: "auto" }}>from #{ahead[ahead.length - 1].overall}</span>
            </li>
          )}
          {showAhead && ahead.map((item) => <LogLine key={item.key} item={item} gap={gaps.get(item.overall)} />)}
          {rows.map((item) => (
            <LogLine key={item.key} item={item} gap={gaps.get(item.overall)} />
          ))}
        </ol>
      ) : (
        <ol className="picklog by-team">
          {byTeam(items, teams).map((g) => (
            <Fragment key={g.team}>
              <li className={`team-head${g.mine ? " mine" : ""}`}>
                <span>{g.team}</span>
                <span className="muted" style={{ marginLeft: "auto" }}>
                  {g.made} {g.made === 1 ? "pick" : "picks"}
                </span>
              </li>
              {g.items.map((item) => (
                <LogLine key={item.key} item={item} gap={gaps.get(item.overall)} byTeam />
              ))}
            </Fragment>
          ))}
        </ol>
      )}
      <details className="keeper-disclosure" open={editOpen} onToggle={(e) => setEditOpen(e.currentTarget.open)}>
        <summary className="k">Edit keepers · {s.keepers.length}</summary>
        <SessionKeepers list={false} />
      </details>
    </>
  );
}

/** One row: the slot, the K mark, a gap's mark, the player, and the team (in draft order) or
 * the overall (by team). A keeper still to come is muted. */
function LogLine({ item, gap, byTeam = false }: { item: LogItem; gap?: GapPick; byTeam?: boolean }) {
  const cls = [item.mine ? "mine" : "", item.toCome ? "to-come" : ""].filter(Boolean).join(" ");
  return (
    <li className={cls || undefined} title={item.toCome ? "keeper: his pick is logged when the draft reaches it" : undefined}>
      <span className="slot">
        {item.round}.{String(item.position).padStart(2, "0")}
      </span>
      {item.keeper && (
        <span className="kmark" title="keeper">
          K
        </span>
      )}
      {!item.toCome && gap && <GapMark gap={gap} />}
      <span>{item.name}</span>
      {item.toCome && <span className="dim tag-to-come">to come</span>}
      <span className="muted" style={{ marginLeft: "auto" }}>
        {byTeam ? `#${item.overall}` : item.team}
      </span>
    </li>
  );
}
