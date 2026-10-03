// YAHOO SYNC in the header and the footer: the state of the room this session follows, read
// from the room summary (refreshed by the session stream) and the extension's heartbeat.
import { useEffect, useState } from "react";
import type { RoomEventEntry, RoomStatus, RoomSummary } from "../api";
import { useDraft } from "../draft";

/** The extension beats every 15 s; two missed beats and the room is called silent. */
export const SILENT_AFTER_S = 40;

export type SyncKey = "disconnected" | "connecting" | "silent" | "mismatch" | "mirroring" | "autopilot" | "finished";

export interface SyncState {
  key: SyncKey;
  label: string;
  /** Pill modifier: hot for autopilot, bad for a problem, good while mirroring. */
  tone: "" | "hot" | "bad" | "good";
  title: string;
}

/** Seconds that tick on their own, for ages shown between summary refreshes. */
export function useNow(everyMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(id);
  }, [everyMs]);
  return now;
}

/** Seconds since the extension's last heartbeat, or null before the first. The API and the
 * browser share this machine's clock. */
export function heartbeatAge(room: RoomSummary, now: number): number | null {
  const recv = room.heartbeat?.recv;
  if (typeof recv === "string") {
    const at = Date.parse(recv);
    if (!Number.isNaN(at)) return Math.max(0, (now - at) / 1000);
  }
  return room.heartbeat_age_s;
}

export function syncState(room: RoomStatus | undefined, now: number): SyncState {
  if (!room?.attached) {
    return { key: "disconnected", label: "YAHOO SYNC", tone: "", title: "No Yahoo draft room attached: picks are entered here by hand. Open the sync card." };
  }
  const where = `room ${room.draft_id}, slot ${room.slot}`;
  if (room.complete) return { key: "finished", label: "ROOM FINISHED", tone: "", title: `${where}: the draft is complete` };
  if (room.teams_mismatch !== null) {
    return { key: "mismatch", label: "SYNC · TEAM COUNT", tone: "bad", title: `${where} has ${room.teams_mismatch} teams but the session has ${room.num_teams}: mirror only` };
  }
  const age = heartbeatAge(room, now);
  // Armed or not stays in the label while the extension is unheard from.
  const head = room.mode === "autopilot" ? "AUTOPILOT" : "SYNC";
  if (age === null) return { key: "connecting", label: `${head} · CONNECTING`, tone: "", title: `${where}: waiting for the extension in the draft tab` };
  if (age > SILENT_AFTER_S) {
    return { key: "silent", label: `${head} · NO SIGNAL`, tone: "bad", title: `${where}: no word from the extension for ${Math.round(age)} s. Is the draft tab open?` };
  }
  if (room.mode === "autopilot") {
    return { key: "autopilot", label: "AUTOPILOT", tone: "hot", title: `${where}: armed, the extension drafts the plan's pick on my turn unless I pick first` };
  }
  return { key: "mirroring", label: "SYNC · MIRRORING", tone: "good", title: `${where}: the room's picks are copied here; nothing is drafted for me` };
}

/** The header's YAHOO SYNC button: its state at a glance, and a click opens the sync card. */
export function SyncButton() {
  const d = useDraft();
  const now = useNow();
  const state = syncState(d.room, now);
  return (
    <button className={`pill clickable sync-pill ${state.tone}`} onClick={() => d.openCard("sync")} title={`${state.title} (8)`}>
      {state.label}
    </button>
  );
}

export function lagSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`;
}

/** Median of the recent room-to-session lags, in ms. */
export function medianLag(room: RoomSummary): number | null {
  const lags = room.recent_lags.map((x) => x.lag_ms).sort((a, b) => a - b);
  if (!lags.length) return null;
  return lags[Math.max(0, Math.ceil(0.5 * lags.length) - 1)];
}

/** The footer's feed note for an attached room. */
export function RoomFeed({ room }: { room: RoomSummary }) {
  const now = useNow();
  const state = syncState(room, now);
  const last = room.recent_lags.at(-1);
  return (
    <span className={state.tone === "bad" ? "bad" : "good"} title={state.title}>
      Yahoo room {room.draft_id} · {room.complete ? "finished" : room.mode === "autopilot" ? "autopilot" : "mirroring"}
      {last ? ` · last pick in ${lagSeconds(last.lag_ms)}` : ""}
    </span>
  );
}

/** A client event in a line: what the extension did or saw. */
export function describeEvent(e: RoomEventEntry, nameOf: (overall: number) => string | undefined): string {
  const at = typeof e.overall === "number" ? `#${e.overall}` : "";
  const str = (k: string) => (typeof e[k] === "string" || typeof e[k] === "number" ? String(e[k]) : "");
  switch (e.type) {
    case "control":
      return `control ${str("state")}${str("reason") ? ` (${str("reason")})` : ""}`;
    case "turn_start":
      return `my turn ${at} starts${str("clock_s") ? `, ${str("clock_s")} s on the clock` : ""}`;
    case "draft_attempt":
      return `${at} attempt ${str("attempt")} by ${str("method")}: ${str("name") || str("yid")}`;
    case "pick_landed": {
      const name = typeof e.overall === "number" ? nameOf(e.overall) : undefined;
      const ms = typeof e.ms_from_turn === "number" ? `, ${lagSeconds(e.ms_from_turn)} into the turn` : "";
      return `${at} landed ${name ?? str("yid")} (${str("how") || "?"})${ms}`;
    }
    case "intervention":
      return `intervention ${at} ${str("what") || str("kind")}`.trim();
    case "note":
      return `${str("what")}${at ? ` ${at}` : ""}${str("msg") ? `: ${str("msg")}` : ""}`;
    default:
      return e.type;
  }
}

export function eventTime(e: RoomEventEntry): string {
  const raw = e.recv ?? e.t;
  const at = typeof raw === "number" ? new Date(raw) : typeof raw === "string" ? new Date(raw) : null;
  if (!at || Number.isNaN(at.getTime())) return "";
  return at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
