import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient, type UseMutationResult } from "@tanstack/react-query";
import { api, type LineupMode, type MovesView, type QueueEntry, type QueuePayload, type SeasonView } from "../api";
import { bidLabel, gainLabel, movesExecutorText, movesLiveText, passLine, passTitle, playersById, queueFlagWord, queueFloorLine, queueMoveText, queueStateText, queueStateTone } from "../season";
import ModeSwitch from "./ModeSwitch";
import { useNow } from "./YahooSync";

/** The single switch's confirm line on live, the Queue card's and each Queue screen chip's. */
export const LIVE_CONFIRM = "Live claims each move due on Yahoo's add page with its bid.";
const CAPS = [0, 1, 2, 3, 4, 5];

/** The Queue card (#171): the moves executor in this league, its mode (live behind a second
 * click, and only once the dry run has passed) and the user's cap on the day's moves; today's
 * queue, each move with its bid, when it executes and the veto (strike it, or its bid alone for a
 * $0 claim); the moves not queued with why; and today's passes. */
export default function QueueCard({ league, s }: { league: string; s: SeasonView }) {
  const queryClient = useQueryClient();
  const key = ["movesView", league];
  const q = useQuery({ queryKey: key, queryFn: () => api.movesView(league), refetchInterval: 60_000, retry: false });
  const now = useNow(30_000);
  const set = useMutation({
    mutationFn: ({ mode, cap }: { mode: LineupMode; cap: number | null }) => api.setMovesMode(league, mode, cap),
    onSuccess: (v) => {
      queryClient.setQueryData(key, v);
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });
  const strike = useMutation({
    mutationFn: ({ id, bid_only, undo }: { id: string; bid_only: boolean; undo: boolean }) => api.strike(id, { bid_only, undo }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: key });
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
    },
  });
  const byId = useMemo(() => playersById(s), [s]);
  const name = (id: number) => byId.get(id)?.name ?? `player ${id}`;
  if (q.error) return <p className="error small">{q.error.message}</p>;
  const v = q.data;
  if (!v) return <p className="dim small">Reading the queue…</p>;
  const queued = v.entries.filter((e) => e.queued);
  const left = v.entries.filter((e) => !e.queued);
  return (
    <>
      <div className="block">
        <div className="sv-head">
          <span className="k">Moves executor</span>
          <span className="grow" />
          {!v.mode.private && (
            <>
              <label className="small muted" title="the most moves the queue takes a day in this league; the knob's unless you set one">
                cap{" "}
                <select
                  value={v.mode.cap ?? ""}
                  disabled={set.isPending}
                  onChange={(e) => set.mutate({ mode: v.mode.mode, cap: e.target.value === "" ? null : Number(e.target.value) })}
                >
                  <option value="">the knob's{v.row?.cap_from === "the knob" && v.row.cap != null ? ` (${v.row.cap})` : ""}</option>
                  {CAPS.map((n) => (
                    <option key={n} value={n}>
                      {n} a day
                    </option>
                  ))}
                </select>
              </label>
              <ModeSwitch
                mode={v.mode.mode}
                liveOk={v.live.ok}
                liveTitle={movesLiveText(v.live)}
                confirm={LIVE_CONFIRM}
                confirmButton="Switch to live"
                pending={set.isPending}
                label="Moves executor"
                onPick={(mode) => set.mutate({ mode, cap: v.mode.cap })}
              />
            </>
          )}
        </div>
        <p className={`lv-note ${v.stop ? "bad" : "muted"}`}>{movesExecutorText(v)}</p>
        {set.error && <p className="error lv-note">{set.error.message}</p>}
        {!v.mode.private && v.mode.mode !== "live" && <p className="dim lv-note">{movesLiveText(v.live)}</p>}
      </div>
      {!v.mode.private && <Today v={v} queued={queued} left={left} now={now} name={name} strike={strike} />}
    </>
  );
}

export type Strike = UseMutationResult<QueuePayload, Error, { id: string; bid_only: boolean; undo: boolean }>;

/** The user's veto on a queued entry: strike it or undo, and for a waiver claim strike its bid
 * (a $0 claim) or bid it back; gone once the entry has an outcome. The Queue card and the Queue
 * screen (#194) both render it. */
export function Veto({ e, strike }: { e: QueueEntry; strike: Strike }) {
  if (e.outcome) return null;
  return (
    <>
      <button className="small" disabled={strike.isPending} onClick={() => strike.mutate({ id: e.id, bid_only: false, undo: e.struck })} title={e.struck ? "queue it again" : "veto this move: it is not executed"}>
        {e.struck ? "undo" : "strike"}
      </button>
      {!e.struck && e.availability !== "FA" && (
        <>
          {" "}
          <button className="small" disabled={strike.isPending} onClick={() => strike.mutate({ id: e.id, bid_only: true, undo: e.bid_struck })} title={e.bid_struck ? "bid the queue's amount again" : "keep the claim, for $0"}>
            {e.bid_struck ? "bid back" : "strike bid"}
          </button>
        </>
      )}
    </>
  );
}

function Today({ v, queued, left, now, name, strike }: { v: MovesView; queued: QueueEntry[]; left: QueueEntry[]; now: number; name: (id: number) => string; strike: Strike }) {
  const row = v.row;
  const time = v.settings.in_force;
  if (!row) return <p className="dim lv-note">No queue built today: the morning routine builds it from the day's solve; nothing executes before {time} CT.</p>;
  if (row.status !== "queued") return <p className="dim lv-note">{row.reason}</p>;
  const struckCount = queued.filter((e) => e.struck).length;
  return (
    <div className="block">
      <div className="row">
        <span className="k">Today</span>
        <span className="small muted" title="the veto window: a move executes no sooner than an hour after it is queued, and no sooner than the execute time (set on the landing page)">
          {queued.filter((e) => !e.struck).length} queued{struckCount ? ` · ${struckCount} struck` : ""} · cap {row.cap} ({row.cap_from}) · executes from {time} CT
        </span>
      </div>
      {queued.length === 0 && <p className="dim lv-note">Nothing queued today.</p>}
      {queued.map((e) => (
        <div key={e.id} className="row small">
          <span title={e.bid.reason}>
            {e.rank}. {queueMoveText(e, name)} · {gainLabel(e.gain)} · {bidLabel(e)}
            {queueFlagWord(e.flag) ? ` · ${queueFlagWord(e.flag)}` : ""}
          </span>
          <span>
            <span className={queueStateTone(e) || (e.struck ? "dim" : "muted")} title={passTitle(e) || undefined}>
              {queueStateText(e, now)}
            </span>
            {!e.outcome && " "}
            <Veto e={e} strike={strike} />
          </span>
        </div>
      ))}
      {strike.error && <p className="error lv-note">{strike.error.message}</p>}
      {left.length > 0 && (
        <>
          <span className="k">Not queued</span>
          {left.map((e) => (
            <p key={e.id} className="dim lv-note" title={e.floor.below ? queueFloorLine(row) : undefined}>
              {queueMoveText(e, name)} · {gainLabel(e.gain)}: {queueStateText(e, now)}
            </p>
          ))}
        </>
      )}
      <p className="dim lv-note">{queueFloorLine(row)}</p>
      {v.today.length === 0 ? (
        <p className="dim lv-note">{v.last ? `No pass today. Last: ${passLine(v.last, clockLabel)}.` : "No pass yet."}</p>
      ) : (
        v.today.map((r, i) => (
          <p key={i} className="muted lv-note">
            {passLine(r, clockLabel)}
          </p>
        ))
      )}
    </div>
  );
}

/** "9:02 AM": a pass's time on this machine's clock. */
function clockLabel(iso: string): string {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? iso : new Date(t).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}
