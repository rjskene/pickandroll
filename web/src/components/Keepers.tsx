// Keepers (docs/KEEPERS.md §3): the editor the setup screen and the log card share, and the
// session's keeper table on the log card. A keeper takes his team's pick in the round he costs;
// the API logs that pick when the draft reaches it and nobody else can draft him.
import { useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, snakeOverall, type KeeperIn, type ProjectedPlayer } from "../api";
import { useDraft } from "../draft";
import { Close } from "./icons";

/** One row of the editor. `player` is what the input shows; `player_id` is kept while it still
 * names the player chosen from the list or loaded from the session's table. */
export interface KeeperDraft {
  key: number;
  on: boolean;
  /** The team's draft position; null is mine. */
  position: number | null;
  round: number;
  player: string;
  player_id: string | null;
  /** Where the row came from (a file's line), shown on hover. */
  label?: string;
  /** His pick is already in the session's log. */
  applied?: boolean;
}

let nextKey = 1;
export function keeperDraft(row: Partial<KeeperDraft>): KeeperDraft {
  return { key: nextKey++, on: true, position: null, round: 1, player: "", player_id: null, ...row };
}

/** Typeahead values to player ids: a name once, or "name · team" where two players share it. */
export function nameOptions(players: ProjectedPlayer[]): Map<string, string> {
  const count = new Map<string, number>();
  for (const p of players) count.set(p.name, (count.get(p.name) ?? 0) + 1);
  const out = new Map<string, string>();
  for (const p of players) out.set((count.get(p.name) ?? 0) > 1 ? `${p.name} · ${p.team}` : p.name, p.player_id);
  return out;
}

/** The rows that are ticked, as the API takes them: by id where known, else by name. */
export function keepersIn(rows: KeeperDraft[], options: Map<string, string>): KeeperIn[] {
  return rows
    .filter((r) => r.on)
    .map((r) => {
      const id = r.player_id ?? options.get(r.player.trim()) ?? null;
      return id ? { position: r.position, round: r.round, player_id: id } : { position: r.position, round: r.round, player: r.player.trim() || null };
    });
}

/** `slot, round, player` lines, as copied from the Yahoo draft board: slot is the team's draft
 * position (`me` for mine), round `7` or `R7`; commas or tabs between. The lines that do not
 * read come back in `failed`, for the paste box to keep. */
export function parseKeeperLines(text: string, numTeams: number): { rows: KeeperDraft[]; errors: string[]; failed: string[] } {
  const rows: KeeperDraft[] = [];
  const errors: string[] = [];
  const failed: string[] = [];
  text.split(/\r?\n/).forEach((line) => {
    if (!line.trim()) return;
    const [slot = "", rnd = "", ...rest] = line.split(/\t|,/).map((x) => x.trim());
    const name = rest.join(", ").trim();
    const position = /^(me|mine)$/i.test(slot) ? null : Number(slot);
    const round = Number(rnd.replace(/^r(?:ound|d)?\s*/i, ""));
    const error =
      position !== null && !(Number.isInteger(position) && position >= 1 && position <= numTeams)
        ? `slot ${slot || "(empty)"} is not me or 1-${numTeams}`
        : !Number.isInteger(round) || round < 1
          ? `round ${rnd || "(empty)"} is not a number`
          : !name
            ? "no player"
            : null;
    if (error) {
      errors.push(`${line.trim()}: ${error}`);
      failed.push(line);
    } else {
      rows.push(keeperDraft({ position, round, player: name }));
    }
  });
  return { rows, errors, failed };
}

/** A row of mine: no team, or the team at my pick (the API takes position == my pick as mine). */
export function isMine(row: Pick<KeeperDraft, "position">, myPosition: number): boolean {
  return row.position === null || row.position === myPosition;
}

/** The row an API error names (`keepers[i] …` counts the ticked rows), by its key. */
export function erroredRow(rows: KeeperDraft[], message: string | undefined): number | null {
  const m = message?.match(/keepers\[(\d+)\]/);
  return m ? (rows.filter((r) => r.on)[Number(m[1])]?.key ?? null) : null;
}

interface EditorProps {
  rows: KeeperDraft[];
  onChange: (rows: KeeperDraft[]) => void;
  numTeams: number;
  myPosition: number;
  rounds: number;
  options: Map<string, string>;
  errorKey?: number | null;
  /** A row whose pick is in the log stays as it is (only the room's record can change it). */
  locked?: (row: KeeperDraft) => boolean;
}

export function KeeperEditor({ rows, onChange, numTeams, myPosition, rounds, options, errorKey, locked }: EditorProps) {
  const listId = useId();
  const mine = (r: KeeperDraft) => isMine(r, myPosition);
  const [paste, setPaste] = useState<string | null>(null);
  const [pasteErrors, setPasteErrors] = useState<string[]>([]);
  const set = (key: number, patch: Partial<KeeperDraft>) => onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const addPasted = () => {
    const parsed = parseKeeperLines(paste ?? "", numTeams);
    setPasteErrors(parsed.errors);
    if (parsed.rows.length) onChange([...rows, ...parsed.rows]);
    // The lines added leave the box; the ones that did not read stay to be fixed.
    setPaste(parsed.failed.length ? parsed.failed.join("\n") : null);
  };
  return (
    <div className="keeper-editor">
      <datalist id={listId}>
        {[...options.keys()].map((v) => (
          <option key={v} value={v} />
        ))}
      </datalist>
      {rows.length > 0 && (
        <table className="keepers">
          <thead>
            <tr>
              <th title="kept: unticked rows are left out"></th>
              <th>Team</th>
              <th>Round</th>
              <th>Player</th>
              <th className="num" title="the overall pick he takes">Pick</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const lock = locked?.(r) ?? false;
              const overall = snakeOverall(numTeams, r.position ?? myPosition, r.round);
              return (
                <tr key={r.key} className={[r.on ? "" : "off", r.key === errorKey ? "err" : ""].filter(Boolean).join(" ")} title={lock ? "in the log: only the room's record can change it" : r.label}>
                  <td>
                    <input type="checkbox" checked={r.on} disabled={lock} aria-label="kept" onChange={(e) => set(r.key, { on: e.target.checked })} />
                  </td>
                  <td>
                    {/* The team at my pick is me (the API reads it so): no "Team N" beside "Me". */}
                    <select value={mine(r) ? 0 : (r.position ?? 0)} disabled={lock} aria-label="team" onChange={(e) => set(r.key, { position: Number(e.target.value) || null })}>
                      <option value={0}>Me</option>
                      {Array.from({ length: numTeams }, (_, i) => i + 1)
                        .filter((n) => n !== myPosition)
                        .map((n) => (
                          <option key={n} value={n}>
                            Team {n}
                          </option>
                        ))}
                    </select>
                  </td>
                  <td>
                    <input type="number" min={1} max={rounds} value={r.round} disabled={lock} aria-label="round" style={{ width: 54 }} onChange={(e) => set(r.key, { round: Number(e.target.value) })} />
                  </td>
                  <td>
                    <input
                      list={listId}
                      value={r.player}
                      disabled={lock}
                      aria-label="player"
                      placeholder="player"
                      spellCheck={false}
                      onChange={(e) => set(r.key, { player: e.target.value, player_id: options.get(e.target.value) ?? null })}
                    />
                  </td>
                  <td className="num dim">{overall >= 1 && overall <= numTeams * rounds ? `#${overall}` : ""}</td>
                  <td>
                    {!lock && (
                      <button className="icon" aria-label="Remove the keeper" title="Remove" onClick={() => onChange(rows.filter((x) => x.key !== r.key))}>
                        <Close />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="row" style={{ justifyContent: "flex-start" }}>
        <button className="small" onClick={() => onChange([...rows, keeperDraft({})])}>
          + keeper
        </button>
        <button className="small" onClick={() => setPaste(paste === null ? "" : null)}>
          {paste === null ? "paste lines" : "close paste"}
        </button>
      </div>
      {paste !== null && (
        <>
          <textarea rows={4} value={paste} spellCheck={false} placeholder={"slot, round, player: one keeper per line\nme, 7, …\n3, R1, …"} onChange={(e) => setPaste(e.target.value)} />
          <div className="row">
            <span className="muted" style={{ fontSize: 12 }}>
              slot is the team's draft position (me for mine); commas or tabs
            </span>
            <button className="small" onClick={addPasted} disabled={!paste.trim()}>
              Add
            </button>
          </div>
          {pasteErrors.map((e) => (
            <p key={e} className="error" style={{ margin: 0, fontSize: 12 }}>
              {e}
            </p>
          ))}
        </>
      )}
    </div>
  );
}

/** The session's keeper table on the log card, with an editor for draft night: the order is
 * drawn and the other teams' keepers show on the Yahoo board. */
export function SessionKeepers() {
  const d = useDraft();
  const s = d.session;
  const queryClient = useQueryClient();
  const board = useQuery({ queryKey: ["board", s.id], queryFn: () => api.board(s.id) });
  const options = useMemo(() => nameOptions(board.data?.players ?? []), [board.data]);
  const [editing, setEditing] = useState<KeeperDraft[] | null>(null);
  const realPicks = s.picks_made - s.keepers.filter((k) => k.applied).length;
  const save = useMutation({
    mutationFn: (rows: KeeperDraft[]) => api.setKeepers(s.id, keepersIn(rows, options)),
    onSuccess: () => {
      setEditing(null);
      for (const key of ["session", "board", "picks", "teams"]) queryClient.invalidateQueries({ queryKey: [key, s.id] });
    },
  });
  const start = () => {
    save.reset();
    setEditing(s.keepers.map((k) => keeperDraft({ position: k.mine ? null : k.position, round: k.round, player: k.name, player_id: k.player_id, applied: k.applied })));
  };
  return (
    <div className="block">
      <div className="row">
        <span className="k">Keepers · {s.keepers.length}</span>
        <span className="grow" />
        {editing === null ? (
          <button className="small" onClick={start} title="Add or change keepers for the picks not yet reached">
            {s.keepers.length ? "Edit" : "Add keepers"}
          </button>
        ) : (
          <>
            <button className="small" onClick={() => setEditing(null)} disabled={save.isPending}>
              Cancel
            </button>
            <button className="small primary" onClick={() => save.mutate(editing)} disabled={save.isPending}>
              Save
            </button>
          </>
        )}
      </div>
      {editing !== null ? (
        <>
          <KeeperEditor
            rows={editing}
            onChange={setEditing}
            numTeams={s.num_teams}
            myPosition={s.my_position}
            rounds={s.roster_size}
            options={options}
            errorKey={erroredRow(editing, save.error?.message)}
            locked={(r) => !!r.applied && realPicks > 0}
          />
          {save.error && <p className="error">{save.error.message}</p>}
        </>
      ) : (
        s.keepers.length > 0 && (
          <ol className="picklog">
            {s.keepers.map((k) => (
              <li key={k.overall} className={k.mine ? "mine" : ""} title={k.applied ? "his pick is in the log" : "his pick is logged when the draft reaches it"}>
                <span className="slot">#{k.overall}</span>
                <span className="kmark">K</span>
                <span>{k.name}</span>
                <span className="muted">R{k.round}</span>
                <span className="muted" style={{ marginLeft: "auto" }}>
                  {k.team}
                </span>
                <span className={k.applied ? "good" : "dim"} style={{ fontSize: 11 }}>
                  {k.applied ? "in" : "to come"}
                </span>
              </li>
            ))}
          </ol>
        )
      )}
    </div>
  );
}
