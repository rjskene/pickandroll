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

/** The days of the week strip before today, whose queues the live floor reads once (today's is
 * the page's own queue). */
export const pastDays = (today: string): string[] => weekOf(Date.parse(`${today}T18:00:00Z`)).filter((d) => d < today);
