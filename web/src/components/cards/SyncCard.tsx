// Card 8, YAHOO SYNC: attach the Yahoo draft room open in Chrome, watch the sync, switch
// between mirror and autopilot, pin the names the room uses that the projections lack, and
// after the draft read how the picks went. The board's own pick controls stay live throughout:
// a pick made by hand, here or in Yahoo, always stands.
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unmatchedStandins, type FidelityRow, type RoomAttachBody, type RoomMode, type RoomSummary, type SeenRoom } from "../../api";
import { useDraft } from "../../draft";
import { SILENT_AFTER_S, SeenRooms, describeEvent, eventTime, heartbeatAge, lagSeconds, medianLag, syncState, useNow, useSeenRooms } from "../YahooSync";

const armedKey = (sessionId: string) => `pickandroll.armed.${sessionId}`;

/** Arming asks once per session; the answer is kept in this browser. */
function armedBefore(sessionId: string): boolean {
  try {
    return localStorage.getItem(armedKey(sessionId)) === "1";
  } catch {
    return false;
  }
}

function rememberArmed(sessionId: string) {
  try {
    localStorage.setItem(armedKey(sessionId), "1");
  } catch {
    /* asked again next time */
  }
}

export default function SyncCard() {
  const d = useDraft();
  if (!d.room) return <p className="muted">Reading the room…</p>;
  if (!d.room.attached) return <AttachForm />;
  return <Attached room={d.room} />;
}

function AttachForm() {
  const d = useDraft();
  const s = d.session;
  const queryClient = useQueryClient();
  const [draftId, setDraftId] = useState("");
  const [slot, setSlot] = useState(s.my_position);
  const [teams, setTeams] = useState<number | null>(s.num_teams); // null: the field is empty
  // The room's team count is known when the room reported it or the user typed it; until then
  // the field only echoes the session's, and the attach's team check gets null, not that echo.
  // A cleared field is unknown again (null), never 0.
  const [teamsKnown, setTeamsKnown] = useState(false);
  const roomTeams = teamsKnown ? teams : null;
  const seen = useSeenRooms();
  const attach = useMutation({
    mutationFn: (body: RoomAttachBody) => api.attachRoom(s.id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["room", s.id] });
      queryClient.invalidateQueries({ queryKey: ["session", s.id] });
    },
  });
  return (
    <div className="block">
      <span className="k">Attach a Yahoo draft room</span>
      <p className="muted">
        Open the draft room in Chrome with the pickandroll extension. Once attached, the room's picks arrive here as they are made and the plan follows them.
        Mirror is the default: nothing is drafted for you until you arm autopilot. The board's pick controls stay yours either way.
      </p>
      <SeenRooms
        rooms={seen.data ?? []}
        action="Attach"
        onPick={(r: SeenRoom) => {
          // With the slot shown the room attaches as it stands, checked against its own team
          // count; without it the form is filled in for the slot.
          setDraftId(r.draft_id);
          if (r.room_teams) {
            setTeams(r.room_teams);
            setTeamsKnown(true);
          }
          if (r.slot) {
            setSlot(r.slot);
            attach.mutate({ draft_id: r.draft_id, slot: r.slot, room_teams: r.room_teams ?? roomTeams });
          }
        }}
      />
      <div className="sync-form">
        <label>
          <span className="k">Draft id</span>
          <input value={draftId} onChange={(e) => setDraftId(e.target.value)} placeholder="from the room's address" spellCheck={false} />
        </label>
        <label title="your draft position in the room">
          <span className="k">My slot</span>
          <input type="number" min={1} max={teams ?? undefined} value={slot} onChange={(e) => setSlot(+e.target.value)} />
        </label>
        <label title="the number of teams the room shows; an attach that disagrees with this session is refused">
          <span className="k">Teams in the room</span>
          <input
            type="number"
            min={2}
            max={20}
            value={teams ?? ""}
            onChange={(e) => {
              setTeams(e.target.value === "" ? null : +e.target.value);
              setTeamsKnown(true);
            }}
          />
        </label>
        <button className="primary" onClick={() => attach.mutate({ draft_id: draftId.trim(), slot, room_teams: roomTeams })} disabled={!draftId.trim() || attach.isPending}>
          {attach.isPending ? "Attaching…" : "Attach"}
        </button>
      </div>
      {teams !== null && teams !== s.num_teams && (
        <p className="banner">
          This session is set up for {s.num_teams} teams. A room with {teams} needs a new session with {teams} teams: every plan here would be for the wrong picks.
        </p>
      )}
      {attach.error && <p className="error">{attach.error.message}</p>}
    </div>
  );
}

function Attached({ room }: { room: RoomSummary }) {
  return (
    <>
      <Status room={room} />
      {room.teams_mismatch !== null && (
        <p className="banner">
          The room has {room.teams_mismatch} teams but this session was set up for {room.num_teams}: every plan is for the wrong picks. The room was put in mirror
          and cannot be armed. Detach it and start a session with {room.teams_mismatch} teams.
        </p>
      )}
      <ModeSwitch room={room} />
      <Problems room={room} />
      <Pins room={room} />
      <Events />
      <FidelityTable room={room} />
      <Detach room={room} />
    </>
  );
}

function Status({ room }: { room: RoomSummary }) {
  const d = useDraft();
  const now = useNow();
  const fresh = !!d.result && !d.busy;
  const state = syncState(room, now);
  const age = heartbeatAge(room, now);
  const behind = Math.max(0, room.room_picks - room.picks_applied);
  const last = room.recent_lags.at(-1);
  const median = medianLag(room);
  const beat = room.heartbeat;
  return (
    <div className="hero">
      <div className="row">
        <span className="k">
          Room {room.draft_id} · slot {room.slot} · {room.num_teams} teams
        </span>
        <span className="grow" />
        <span className={`pill ${state.tone}`} title={state.title}>
          {state.label}
        </span>
      </div>
      <div className="stats">
        <div className="stat" title="room picks the session has not applied yet">
          <span className="k">Behind</span>
          <span className={`v ${behind ? "accent" : "good"}`}>{behind ? `${behind} picks` : "in sync"}</span>
        </div>
        <div className="stat" title={`room message to session pick; the latest: ${room.recent_lags.slice(-6).map((x) => `#${x.overall} ${lagSeconds(x.lag_ms)}`).join(", ") || "none yet"}`}>
          <span className="k">Lag</span>
          <span className={`v ${last && last.lag_ms > 2000 ? "bad" : ""}`}>{last ? lagSeconds(last.lag_ms) : "—"}</span>
        </div>
        <div className="stat" title="the plan was solved on the board as it stands now">
          <span className="k">{room.my_next_pick ? `Plan for #${room.my_next_pick}` : "Plan"}</span>
          <span className={`v ${fresh ? "good" : "accent"}`}>{room.my_next_pick === null ? "done" : fresh ? "ready" : "solving"}</span>
        </div>
        <div className="stat" title="the extension in the draft tab beats every 15 s">
          <span className="k">Extension</span>
          <span className={`v ${age === null ? "accent" : age > SILENT_AFTER_S ? "bad" : ""}`}>{age === null ? "waiting" : `${Math.round(age)} s ago`}</span>
        </div>
      </div>
      <div className="muted" style={{ fontSize: 12 }}>
        {room.room_picks} room picks · {room.picks_applied} on the board · synced through #{room.synced_through}
        {median !== null ? ` · median lag ${lagSeconds(median)}` : ""}
        {room.on_the_clock ? " · you are on the clock" : ""}
        {room.resumed ? " · resumed from the log" : ""}
      </div>
      {room.waiting_for !== null && <p className="banner accent">Waiting for pick #{room.waiting_for} from the room: the picks after it are held until it arrives.</p>}
      {beat?.vis === "hidden" && <p className="banner accent">The draft tab is in the background. Chrome may slow it; keep it visible during the draft.</p>}
      {beat?.autodraft === true && <p className="banner accent">Yahoo's own autodraft is on in the room.</p>}
    </div>
  );
}

/** When autopilot may click, in seconds left on the 30 s clock (the API's floor is 12 s: the
 * drafter's row clicks need room before its 6 s backstop). */
const ACT_AT_S = [25, 20, 15, 12];

function ModeSwitch({ room }: { room: RoomSummary }) {
  const d = useDraft();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const setMode = useMutation({
    mutationFn: (mode: RoomMode) => api.setRoomMode(room.draft_id, { mode }),
    onSuccess: (_r, mode) => {
      if (mode === "autopilot") rememberArmed(d.session.id);
      setConfirming(false);
      queryClient.invalidateQueries({ queryKey: ["room", d.session.id] });
    },
  });
  const choose = (mode: RoomMode) => {
    if (mode === room.mode) return;
    setMode.reset();
    if (mode === "autopilot" && !armedBefore(d.session.id)) setConfirming(true);
    else setMode.mutate(mode);
  };
  const setAct = useMutation({
    // The timing alone: a cached mode resent with it could re-arm a room just set to mirror.
    mutationFn: (act_at_s: number | null) => api.setRoomMode(room.draft_id, { act_at_s }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["room", d.session.id] }),
  });
  const locked = room.complete || setMode.isPending;
  const act = room.act_at_s;
  const acts = [...new Set([...ACT_AT_S, ...(act === null ? [] : [act])])].sort((a, b) => b - a);
  return (
    <div className="block">
      <div className="row">
        <span className="k">Mode</span>
        <span className="grow" />
        <span className="seg" role="group" aria-label="Sync mode">
          <button className={room.mode === "mirror" ? "on" : ""} onClick={() => choose("mirror")} disabled={locked} aria-pressed={room.mode === "mirror"}>
            Mirror
          </button>
          <button className={room.mode === "autopilot" ? "on" : ""} onClick={() => choose("autopilot")} disabled={locked} aria-pressed={room.mode === "autopilot"}>
            Autopilot
          </button>
        </span>
      </div>
      <div className="row">
        <span className="k">Autopilot clicks</span>
        <span className="grow" />
        <select
          value={act ?? ""}
          onChange={(e) => setAct.mutate(e.target.value ? Number(e.target.value) : null)}
          disabled={room.complete || setAct.isPending}
          aria-label="When autopilot clicks"
          title="Waiting leaves you time to pick first, in Yahoo or with Draft in Yahoo"
        >
          <option value="">at once</option>
          {acts.map((s) => (
            <option key={s} value={s}>
              at {s} s left
            </option>
          ))}
        </select>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        {room.mode === "autopilot"
          ? `Armed: when your turn comes, the extension drafts the plan's pick in Yahoo${act === null ? "" : ` once the clock is down to ${act} s`}. A pick you make first, in Yahoo or with Draft in Yahoo, stands.`
          : "Mirror: the room's picks are copied here and nothing is drafted for you. Pick in Yahoo, or here and then in Yahoo."}
      </p>
      {confirming && (
        <div className="banner accent">
          <p>
            Arm autopilot for room {room.draft_id}? The extension will draft for you in Yahoo on each of your turns, taking the plan's pick, unless you pick first.
            Switch back to Mirror at any time.
          </p>
          <div className="row" style={{ justifyContent: "flex-start", marginTop: 8 }}>
            <button className="primary small" onClick={() => setMode.mutate("autopilot")} disabled={setMode.isPending}>
              Arm autopilot
            </button>
            <button className="small" onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {setMode.error && <p className="error">{setMode.error.message}</p>}
      {setAct.error && <p className="error">{setAct.error.message}</p>}
    </div>
  );
}

function Problems({ room }: { room: RoomSummary }) {
  if (!room.unresolved.length && !room.conflicts.length) return null;
  return (
    <div className="block">
      <span className="k bad">Room picks not applied</span>
      {room.unresolved.map((u) => (
        <div key={`u${u.overall}`} className="bad" style={{ fontSize: 12 }}>
          #{u.overall} {u.label ?? "?"} {u.team ? `(${u.team})` : ""}: no Yahoo player by that name; later picks wait for it
        </div>
      ))}
      {room.conflicts.map((c, i) => (
        <div key={`c${i}`} className="bad" style={{ fontSize: 12 }}>
          #{String(c.overall)} reported as two players ({String(c.kept)} kept, {String(c.reported)} reported)
        </div>
      ))}
    </div>
  );
}

/** Yahoo names with no projection, the room's stand-ins first, each with a picker that pins it. */
function Pins({ room }: { room: RoomSummary }) {
  const d = useDraft();
  const board = useQuery({ queryKey: ["board", d.session.id], queryFn: () => api.board(d.session.id) });
  const picks = useQuery({ queryKey: ["picks", d.session.id], queryFn: () => api.picks(d.session.id) });
  const [all, setAll] = useState(false);
  // A gap's stand-in has no Yahoo name to pin: its keeper is named on the log card.
  const standins = unmatchedStandins(room);
  if (!standins.length && !room.unmatched_yahoo.length) return null;
  // The stand-in holds the room pick's place on the board: its name is that pick's.
  const placed = new Map((picks.data ?? []).map((p) => [p.overall, p.name]));
  const loose = new Set(room.unmatched_projection.map((p) => p.player_id));
  const others = (board.data?.players ?? []).filter((p) => !p.taken && !loose.has(p.player_id)).sort((a, b) => a.name.localeCompare(b.name));
  const standing = new Set(standins.map((x) => x.yid));
  // Stand-ins are on the board now; the rest only matter if the room drafts them, so a few show.
  const waiting = room.unmatched_yahoo.filter((u) => !standing.has(u.yahoo_player_id));
  const shown = all ? waiting : waiting.slice(0, 3);
  // One list for every row's picker: the projected players with no Yahoo id first (the likeliest
  // match), then the rest of the board, each by a label unique enough to type.
  const choices = new Map<string, string>();
  for (const p of [...room.unmatched_projection, ...others]) {
    const label = p.team ? `${p.name} (${p.team})` : p.name;
    if (!choices.has(label)) choices.set(label, p.player_id);
  }
  return (
    <div className="block">
      <div className="row">
        <span className="k">Names to pin</span>
        <span className="muted" style={{ fontSize: 11 }}>
          kept in data/aliases.json for later rooms too
        </span>
      </div>
      <p className="muted" style={{ fontSize: 12 }}>
        Yahoo players the projections do not match. A room pick of one holds its place on the board with a stand-in until it is pinned.
      </p>
      <datalist id="pin-choices">
        {[...choices.keys()].map((label) => (
          <option key={label} value={label} />
        ))}
      </datalist>
      <table className="pins">
        <tbody>
          {standins.map((x) => (
            <PinRow key={`s${x.overall}`} room={room} yid={x.yid} name={x.name} note={`#${x.overall}, held by ${placed.get(x.overall) ?? x.as}`} choices={choices} />
          ))}
          {shown.map((u) => (
            <PinRow key={u.yahoo_player_id} room={room} yid={u.yahoo_player_id} name={u.name} note={[u.team, u.adp !== null ? `ADP ${u.adp.toFixed(0)}` : ""].filter(Boolean).join(" · ")} choices={choices} />
          ))}
        </tbody>
      </table>
      {waiting.length > shown.length && (
        <button className="link" style={{ fontSize: 12, alignSelf: "flex-start" }} onClick={() => setAll(true)}>
          {waiting.length - shown.length} more by ADP
        </button>
      )}
    </div>
  );
}

function PinRow({ room, yid, name, note, choices }: { room: RoomSummary; yid: string; name: string; note: string; choices: Map<string, string> }) {
  const d = useDraft();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const pid = choices.get(text.trim()) ?? null;
  const pin = useMutation({
    mutationFn: (playerId: string) => api.pinAlias(room.draft_id, { yahoo_player_id: yid, player_id: playerId }),
    onSuccess: () => {
      for (const key of ["room", "board", "picks", "session"]) queryClient.invalidateQueries({ queryKey: [key, d.session.id] });
    },
  });
  return (
    <tr>
      <td>
        <div>{name}</div>
        <div className="muted" style={{ fontSize: 11 }}>
          {note}
        </div>
        {pin.error && <div className="error">{pin.error.message}</div>}
      </td>
      <td>
        <input
          list="pin-choices"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && pid) pin.mutate(pid);
          }}
          placeholder="pin to…"
          aria-label={`Projection for ${name}`}
          spellCheck={false}
          style={{ width: 170 }}
        />
      </td>
      <td>
        <button className="small" disabled={!pid || pin.isPending} onClick={() => pid && pin.mutate(pid)} title={pid ? `pin ${name} to ${text.trim()}` : "choose a player from the list"}>
          Pin
        </button>
      </td>
    </tr>
  );
}

function Events() {
  const d = useDraft();
  const picks = useQuery({ queryKey: ["picks", d.session.id], queryFn: () => api.picks(d.session.id) });
  const byOverall = new Map((picks.data ?? []).map((p) => [p.overall, p.name]));
  const rows = d.roomEvents.slice(-15).reverse();
  return (
    <div className="block">
      <div className="row">
        <span className="k">From the room</span>
        <span className="muted" style={{ fontSize: 11 }}>
          the extension's latest, since this page opened
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="muted" style={{ fontSize: 12 }}>
          Nothing yet.
        </p>
      ) : (
        <ul className="events">
          {rows.map((e, i) => (
            <li key={`${e.recv ?? ""}${i}`}>
              <span className="when">{eventTime(e)}</span>
              <span>{describeEvent(e, (k) => byOverall.get(k))}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const LABEL_TONE: Record<string, string> = { compliant: "good", manual: "tie" };

function ms(x: number | null): string {
  return x === null ? "—" : lagSeconds(x);
}

/** After the draft (or on demand during it): each of my picks against the plan at its turn. */
function FidelityTable({ room }: { room: RoomSummary }) {
  const [asked, setAsked] = useState(false);
  const show = room.complete || asked;
  const card = useQuery({
    queryKey: ["fidelity", room.draft_id, room.room_picks],
    queryFn: () => api.fidelity(room.draft_id),
    enabled: show,
  });
  if (!show) {
    return (
      <div className="block">
        <div className="row">
          <span className="k">My picks against the plan</span>
          <button className="small" onClick={() => setAsked(true)}>
            Show so far
          </button>
        </div>
      </div>
    );
  }
  const f = card.data;
  const lag = f?.guardrails.G2;
  return (
    <div className="block">
      <div className="row">
        <span className="k">My picks against the plan</span>
        {f && (
          <span className="muted" style={{ fontSize: 11 }}>
            {f.compliance.compliant} of {f.compliance.denominator} as planned · {f.compliance.manual} by hand
          </span>
        )}
      </div>
      {card.error && <p className="error">{card.error.message}</p>}
      {f && (
        <>
          <div className="fidelity-wrap">
            <table className="fidelity">
              <thead>
                <tr>
                  <th className="num">#</th>
                  <th title="the plan's top candidate when my turn started">Plan</th>
                  <th>Picked</th>
                  <th>Match</th>
                  <th className="num" title="where the pick stood in the candidates acted on">Rank</th>
                  <th className="num" title="turn start to the pick landing">Turn</th>
                  <th className="num" title="room to session">Lag</th>
                </tr>
              </thead>
              <tbody>
                {f.rows.map((r: FidelityRow) => (
                  <tr key={r.overall}>
                    <td className="num">{r.overall}</td>
                    <td>{r.ref_name ?? "—"}</td>
                    <td className={r.actual_name && r.actual_name === r.ref_name ? "strong" : ""}>{r.actual_name ?? r.actual_yid ?? "—"}</td>
                    <td>
                      <span className={`tag ${LABEL_TONE[r.label] ?? "bad"}`}>{r.label}</span>
                    </td>
                    <td className="num">{r.actual_rank ?? "—"}</td>
                    <td className="num">{ms(r.turn_to_land_ms)}</td>
                    <td className="num">{ms(r.lag_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {lag && (
            <div className="muted" style={{ fontSize: 12 }}>
              Room-to-session lag over {lag.n} picks: p50 {ms(lag.p50)} · p95 {ms(lag.p95)} · max {ms(lag.max)} (targets 1 s, 2 s, 5 s)
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Detach({ room }: { room: RoomSummary }) {
  const d = useDraft();
  const queryClient = useQueryClient();
  const detach = useMutation({
    mutationFn: () => api.detachRoom(room.draft_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["room", d.session.id] }),
  });
  return (
    <div className="block">
      <div className="row">
        <span className="muted" style={{ fontSize: 12 }}>
          Detaching stops the sync; the picks so far stay. Attaching the same draft id again picks up from the log.
        </span>
        <button className="small" onClick={() => detach.mutate()} disabled={detach.isPending}>
          Detach
        </button>
      </div>
      {detach.error && <p className="error">{detach.error.message}</p>}
    </div>
  );
}
