import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type QueuePayload } from "../api";

/** The day's execute time on the Central clock (#193), the user's own setting: no move executes
 * before it, nor within an hour of its queueing. Sunday's own beside it (#209): Sunday's claims
 * clear on Monday, and set late they wait for the evening's solve; empty, Sunday keeps the day's.
 * The landing's Queue line and the Queue screen (#194) both set them here. */
export default function ExecuteTime({ q }: { q: QueuePayload | undefined }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const [sundayDraft, setSundayDraft] = useState<string | null>(null);
  const done = (v: QueuePayload) => {
    queryClient.setQueryData(["queue"], v);
    void queryClient.invalidateQueries({ queryKey: ["movesView"] });
  };
  const set = useMutation({
    mutationFn: (t: string) => api.setExecuteTime(t),
    onSuccess: (v) => {
      done(v);
      setDraft(null);
    },
  });
  const setSunday = useMutation({
    mutationFn: (t: string | null) => api.setSundayExecuteTime(t),
    onSuccess: (v) => {
      done(v);
      setSundayDraft(null);
    },
  });
  const current = q?.settings.execute_time;
  if (!current) return null;
  const shown = draft ?? current;
  const sunday = q?.settings.sunday_execute_time ?? null;
  const sundayShown = sundayDraft ?? sunday ?? "";
  const busy = set.isPending || setSunday.isPending;
  return (
    <>
      <label className="small muted" title="the day's execute time on the Central clock: each move executes at it, or an hour after it is queued if later">
        execute at{" "}
        <input type="time" value={shown} onChange={(e) => setDraft(e.target.value)} disabled={busy} aria-label="execute time, Central" /> CT
      </label>
      {draft != null && draft !== current && (
        <button className="small primary" disabled={busy || !draft} onClick={() => set.mutate(draft)}>
          Set
        </button>
      )}
      <label className="small muted" title="Sunday's own execute time on the Central clock: Sunday's claims clear on Monday, so set late they wait for the evening's solve; empty, Sunday keeps the day's">
        Sunday{" "}
        <input type="time" value={sundayShown} onChange={(e) => setSundayDraft(e.target.value)} disabled={busy} aria-label="Sunday's execute time, Central" />
        {sunday ? " CT" : ` (the day's ${current})`}
      </label>
      {sundayDraft != null && sundayDraft !== "" && sundayDraft !== sunday && (
        <button className="small primary" disabled={busy} onClick={() => setSunday.mutate(sundayDraft)}>
          Set
        </button>
      )}
      {sunday && (
        <button className="small" disabled={busy} onClick={() => setSunday.mutate(null)} title="Sunday keeps the day's execute time">
          Clear
        </button>
      )}
      {set.error && <span className="error small">{set.error.message}</span>}
      {setSunday.error && <span className="error small">{setSunday.error.message}</span>}
    </>
  );
}
