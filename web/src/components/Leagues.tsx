import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type LeagueSummary } from "../api";
import { armLabel, draftWhen } from "../format";

/** The league folders in data/leagues/ (#67) and the user's own pre-arm for each draft. Arming
 * is the user's click here, confirmed in a second click; no session or script arms a league
 * (CLAUDE.md, the 2026-10-16 exception). An armed league's room comes up in autopilot when the
 * draft-day runbook attaches it; an unarmed one runs in mirror and Yahoo autopicks its turns. */
export default function Leagues() {
  const queryClient = useQueryClient();
  const leagues = useQuery({ queryKey: ["leagues"], queryFn: api.leagues, refetchInterval: 30_000 });
  // The league whose arm is waiting on its confirming click.
  const [confirming, setConfirming] = useState<string | null>(null);
  const arm = useMutation({
    mutationFn: ({ league, armed }: { league: string; armed: boolean }) => api.armLeague(league, armed),
    onSettled: () => {
      setConfirming(null);
      void queryClient.invalidateQueries({ queryKey: ["leagues"] });
    },
  });
  if (!leagues.data?.length) return null;
  const now = Date.now();
  // Soonest draft first; a league with no draft time last.
  const when = (l: LeagueSummary) => (l.draft_time ? Date.parse(l.draft_time) : Infinity);
  const rows = [...leagues.data].sort((a, b) => when(a) - when(b));
  return (
    <div className="leagues">
      <div className="row">
        <strong>Leagues</strong>
        <span className="muted" style={{ fontSize: 11 }}>
          arm a draft to let pickandroll pick for you in it; unarmed, Yahoo autopicks your turns
        </span>
      </div>
      <table>
        <tbody>
          {rows.map((l) => (
            <tr key={l.league}>
              <td>{l.league}</td>
              <td className="dim">{l.scoring === "points" ? "H2H points" : "H2H categories"}</td>
              <td title={l.draft_time ?? undefined}>{draftWhen(l.draft_time, now)}</td>
              <td className="dim">{l.players_file ? "" : "no players file"}</td>
              <td>
                {l.armed ? (
                  <>
                    <span className="tag good" title={`armed ${l.armed.at}`}>
                      {armLabel(l.armed)}
                    </span>{" "}
                    <button disabled={arm.isPending} onClick={() => arm.mutate({ league: l.league, armed: false })}>
                      Disarm
                    </button>
                  </>
                ) : confirming === l.league ? (
                  <>
                    <button className="primary" disabled={arm.isPending} onClick={() => arm.mutate({ league: l.league, armed: true })}>
                      Confirm: arm {l.league}
                    </button>{" "}
                    <button onClick={() => setConfirming(null)}>Cancel</button>
                  </>
                ) : (
                  <button onClick={() => setConfirming(l.league)}>Arm draft</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {arm.isError && <p className="warn">{String(arm.error)}</p>}
    </div>
  );
}
