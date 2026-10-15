import type { KeeperRow, PickRow } from "../../api";

/** A row of the pick log: a pick made, or a keeper whose pick the draft has not reached yet. */
export interface LogItem {
  key: string;
  overall: number;
  round: number;
  position: number;
  team: string;
  player_id: string;
  name: string;
  /** A keeper still to come: logged when the draft reaches his slot. */
  toCome: boolean;
  /** The K mark: a keeper's pick, or a kept player whose pick was reconciled elsewhere. */
  keeper: boolean;
  mine: boolean;
}

/** Every pick made and every keeper still to come, in overall order. A pick is marked kept
 * when the log says so or when its player is in the keeper table. */
export function logItems(picks: PickRow[], keepers: KeeperRow[], myTeam: string): LogItem[] {
  const kept = new Set(keepers.map((k) => k.player_id));
  const made: LogItem[] = picks.map((p) => ({
    key: `pick-${p.overall}`,
    overall: p.overall,
    round: p.round,
    position: p.position,
    team: p.team,
    player_id: p.player_id,
    name: p.name,
    toCome: false,
    keeper: p.keeper || kept.has(p.player_id),
    mine: p.team === myTeam,
  }));
  const toCome: LogItem[] = keepers
    .filter((k) => !k.applied)
    .map((k) => ({
      key: `keeper-${k.overall}-${k.player_id}`,
      overall: k.overall,
      round: k.round,
      position: k.position,
      team: k.team,
      player_id: k.player_id,
      name: k.name,
      toCome: true,
      keeper: true,
      mine: k.mine,
    }));
  // At one overall a pick made comes before a keeper still to come there.
  return [...made, ...toCome].sort((a, b) => a.overall - b.overall || Number(a.toCome) - Number(b.toCome));
}

/** Draft order, newest first. Keepers to come within the next round (overall up to
 * ``nextOverall + numTeams``) sit above the picks made at their overall; the ones further
 * ahead are held back in ``ahead`` (newest first too), so the latest picks stay at the top. */
export function draftOrder(items: LogItem[], nextOverall: number, numTeams: number): { ahead: LogItem[]; rows: LogItem[] } {
  const far = (i: LogItem) => i.toCome && i.overall > nextOverall + numTeams;
  return { ahead: items.filter(far).reverse(), rows: items.filter((i) => !far(i)).reverse() };
}

export interface TeamGroup {
  team: string;
  mine: boolean;
  /** Picks made, keepers to come left out. */
  made: number;
  items: LogItem[];
}

/** By team: the teams in draft-position order (``teams``, position 1 first), then any other
 * team in the log by its first pick; each team's rows in overall order. Teams without a row
 * are left out. */
export function byTeam(items: LogItem[], teams: string[]): TeamGroup[] {
  const groups = new Map<string, TeamGroup>();
  for (const team of teams) groups.set(team, { team, mine: false, made: 0, items: [] });
  for (const item of items) {
    const group = groups.get(item.team) ?? { team: item.team, mine: false, made: 0, items: [] };
    groups.set(item.team, group);
    group.items.push(item);
    group.mine ||= item.mine;
    if (!item.toCome) group.made += 1;
  }
  return [...groups.values()].filter((g) => g.items.length > 0);
}
