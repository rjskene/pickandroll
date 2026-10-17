import type { SessionCreateBody } from "./api";

/** Whether a failed create is the league curve the server could not fit (its 400 reads
 * "curve=league: ..."), as the draft-day attach tells it (scripts/draft_day.py). */
export function isLeagueCurveError(message: string): boolean {
  return message.includes("curve=league");
}

/** Makes the session. A league curve the league's folder resolved (not one the user chose) that
 * the server cannot fit is dropped and the session made on the simulated curve, with the
 * server's reason (#74): the draft-day attach does the same, and the form never leaves the user
 * with a failed create over a default. */
export async function createWithCurveFallback<S>(
  create: (body: SessionCreateBody) => Promise<S>,
  body: SessionCreateBody,
  curveResolved: boolean,
): Promise<{ session: S; curveNote: string | null }> {
  try {
    return { session: await create(body), curveNote: null };
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    if (!curveResolved || body.curve !== "league" || !isLeagueCurveError(message)) throw e;
    const simulated: SessionCreateBody = { ...body };
    delete simulated.curve;
    return { session: await create(simulated), curveNote: message };
  }
}
