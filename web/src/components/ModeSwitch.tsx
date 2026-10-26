import { useState } from "react";
import type { LineupMode } from "../api";
import { MODE_WORDS } from "../season";

const MODES: LineupMode[] = ["off", "dry_run", "live"];

/** The moves executor's mode control (#171, #205): off · dry run · live, live behind a second
 * click on its confirm line and only where ``liveOk``. One component for the Queue card, the Queue
 * screen's head (every league; ``mode`` null when they differ) and each league chip, so the words
 * and the guard's hover are the same in all three. */
export default function ModeSwitch({
  mode,
  liveOk,
  liveTitle,
  confirm,
  confirmButton,
  pending,
  label,
  onPick,
}: {
  mode: LineupMode | null;
  liveOk: boolean;
  liveTitle: string;
  confirm: string;
  confirmButton: string;
  pending: boolean;
  label: string;
  onPick: (mode: LineupMode) => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const pick = (m: LineupMode) => {
    if (m === mode) return;
    if (m === "live" && !confirming) return setConfirming(true);
    setConfirming(false);
    onPick(m);
  };
  return (
    <div className="mode-switch">
      <div className="seg small" role="tablist" aria-label={label}>
        {MODES.map((m) => (
          <button
            key={m}
            role="tab"
            aria-selected={m === mode}
            className={m === mode ? "on" : undefined}
            disabled={pending || (m === "live" && !liveOk && mode !== "live")}
            title={m === "live" ? liveTitle : undefined}
            onClick={() => pick(m)}
          >
            {MODE_WORDS[m]}
          </button>
        ))}
      </div>
      {confirming && (
        <p className="lv-note accent">
          {confirm}{" "}
          <button className="small" onClick={() => pick("live")} disabled={pending}>
            {confirmButton}
          </button>{" "}
          <button className="small" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </p>
      )}
    </div>
  );
}
