import type { ReactNode } from "react";
import { ProgressIcon } from "./icons";
import Wordmark from "./Wordmark";

/** The app bar's lead (#270), on the landing, a league page, Progress and the Queue: the
 * wordmark, the update indicator immediately right of it, then the Progress button (icon only).
 * They stay together when a phone's bar wraps. On Progress itself the button marks the page.
 * A page's own icons follow the button (the league page's Yahoo link, #278). */
export default function AppBarLead({ onHome, status, onProgress, here, children }: { onHome?: () => void; status: ReactNode; onProgress?: () => void; here?: boolean; children?: ReactNode }) {
  return (
    <span className="bar-lead">
      <Wordmark onHome={onHome} />
      {status}
      <button
        className={`icon${here ? " on" : ""}`}
        onClick={here ? undefined : onProgress}
        aria-label="Progress"
        aria-current={here ? "page" : undefined}
        title={here ? "Progress: the hill-climb over the season (this page)" : "Progress: the hill-climb over the season (p)"}
      >
        <ProgressIcon />
      </button>
      {children}
    </span>
  );
}
