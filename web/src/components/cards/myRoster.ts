import { useQuery } from "@tanstack/react-query";
import { api } from "../../api";
import { useDraft } from "../../draft";

export interface MyRosterRow {
  overall: number;
  player_id: string;
  name: string;
  round: number;
  /** A keeper: his pick is logged from the keeper table. */
  kept: boolean;
  /** A keeper of mine whose slot the draft has not reached yet. */
  toCome: boolean;
}

/** My roster in draft order, from the pick log and my keepers still to come: what the cards
 * show once nothing is solved again (my picks are made, or the draft is complete). */
export function useMyRoster(): MyRosterRow[] | undefined {
  const s = useDraft().session;
  const picks = useQuery({ queryKey: ["picks", s.id], queryFn: () => api.picks(s.id) });
  if (!picks.data) return undefined;
  const mine = new Set(s.my_roster);
  const rows: MyRosterRow[] = picks.data
    .filter((p) => mine.has(p.player_id))
    .map((p) => ({ overall: p.overall, player_id: p.player_id, name: p.name, round: p.round, kept: p.keeper, toCome: false }));
  for (const k of s.keepers) {
    if (k.mine && !k.applied) rows.push({ overall: k.overall, player_id: k.player_id, name: k.name, round: k.round, kept: true, toCome: true });
  }
  return rows.sort((a, b) => a.overall - b.overall);
}
