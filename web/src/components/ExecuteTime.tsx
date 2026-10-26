import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type QueuePayload } from "../api";

/** The day's execute time on the Central clock (#193), the user's own setting: no move executes
 * before it, nor within an hour of its queueing. The landing's Queue line and the Queue screen
 * (#194) both set it here. */
export default function ExecuteTime({ q }: { q: QueuePayload | undefined }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const set = useMutation({
    mutationFn: (t: string) => api.setExecuteTime(t),
    onSuccess: (v) => {
      queryClient.setQueryData(["queue"], v);
      void queryClient.invalidateQueries({ queryKey: ["movesView"] });
      setDraft(null);
    },
  });
  const current = q?.settings.execute_time;
  if (!current) return null;
  const shown = draft ?? current;
  return (
    <>
      <label className="small muted" title="the day's execute time on the Central clock: each move executes at it, or an hour after it is queued if later">
        execute at{" "}
        <input type="time" value={shown} onChange={(e) => setDraft(e.target.value)} disabled={set.isPending} aria-label="execute time, Central" /> CT
      </label>
      {draft != null && draft !== current && (
        <button className="small primary" disabled={set.isPending || !draft} onClick={() => set.mutate(draft)}>
          Set
        </button>
      )}
      {set.error && <span className="error small">{set.error.message}</span>}
    </>
  );
}
