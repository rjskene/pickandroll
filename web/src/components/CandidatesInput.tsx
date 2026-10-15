import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useDraft } from "../draft";

const MIN = 1;
const MAX = 30;

/** How many candidates the solver prices exactly, and in a room how many at my own turn. The
 * counts live on the server, so the background and room solves use them too. They stay
 * editable while a solve runs: a change applies from the next solve. */
export default function CandidatesInput({ label = "candidates" }: { label?: string }) {
  const d = useDraft();
  const s = d.session;
  const p = s.solve_params;
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: (patch: { n?: number; turn_n?: number | null }) => api.setSolveParams(s.id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["session", s.id] }),
  });
  return (
    <span className="candidates-input">
      <Count label={label} value={p.n} onCommit={(n) => save.mutate({ n })} title="candidates priced exactly on every solve" />
      {p.turn_n !== null && (
        <Count
          label="at my turn"
          value={p.turn_n}
          onCommit={(turn_n) => save.mutate({ turn_n })}
          title="candidates priced when my pick is on the clock: the room keeps that solve short for its clock"
        />
      )}
      <span className={d.solving ? "hint on" : "hint"}>applies to next solve</span>
      {save.isError && <span className="bad">{save.error.message}</span>}
    </span>
  );
}

/** A number field that follows the server's value and sends a change once typing pauses (or
 * on blur), so "12" is not sent as "1" first. */
function Count({ label, value, onCommit, title }: { label: string; value: number; onCommit: (v: number) => void; title: string }) {
  const [text, setText] = useState(String(value));
  const commit = useRef(onCommit);
  commit.current = onCommit;
  // The server's value wins whenever it changes: after this field's own save, or another client's.
  useEffect(() => setText(String(value)), [value]);
  const parsed = Number(text);
  const valid = text.trim() !== "" && Number.isInteger(parsed) && parsed >= MIN && parsed <= MAX;
  useEffect(() => {
    if (!valid || parsed === value) return;
    const t = setTimeout(() => commit.current(parsed), 500);
    return () => clearTimeout(t);
  }, [valid, parsed, value]);
  const onBlur = () => {
    if (!valid) setText(String(value));
    else if (parsed !== value) commit.current(parsed);
  };
  return (
    <label title={title}>
      {label}{" "}
      <input type="number" min={MIN} max={MAX} value={text} className={valid ? undefined : "invalid"} onChange={(e) => setText(e.target.value)} onBlur={onBlur} />
    </label>
  );
}
