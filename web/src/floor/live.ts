// The live floor's reads and how often it takes them (#462). Pure: the face's queries use these.
import type { QueuePayload, RoutineLivePayload } from "../api.ts";
import { weekOf } from "./scene.ts";

/** Poll every few seconds while a run or a pass is in flight, slowly at rest. (The queries stop
 * altogether while the page is hidden: react-query's interval does not run in the background.) */
export const POLL = { busy: 3_000, rest: 60_000 } as const;

/** Whether a run or a pass is in flight: a live file not yet stale (it is removed however its run
 * ends), or the queue's pass under way. */
export function inFlight(live: RoutineLivePayload | null | undefined, queue: Pick<QueuePayload, "active"> | null | undefined): boolean {
  return !!queue?.active || (live?.live ?? []).some((r) => !r.stale && r.progress !== null);
}

/** The interval for the floor's live reads. */
export const livePoll = (live: RoutineLivePayload | null | undefined, queue: Pick<QueuePayload, "active"> | null | undefined): number =>
  inFlight(live, queue) ? POLL.busy : POLL.rest;

/** The days of the Central week, up to and including the Central today, whose queues the live
 * floor reads itself: every one the page's own queue does not cover (#468). The page's queue is
 * the NBA day (Eastern), so from 23:00 to midnight Central it is already tomorrow's, and the
 * Central today is read here. Before the page's queue answers (``covered`` null) only the days
 * before today, so today is not read twice. */
export function weekQueueDays(today: string, covered: string | null): string[] {
  const week = weekOf(Date.parse(`${today}T18:00:00Z`));
  return covered === null ? week.filter((d) => d < today) : week.filter((d) => d <= today && d !== covered);
}
