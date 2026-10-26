import type { BestMove, SeasonSummary, StatusPayload } from "../api";
import {
  addsLeft,
  addsNote,
  ageLabel,
  bestLine,
  bestNamer,
  flagCounts,
  gainLabel,
  isRefreshing,
  isStale,
  placeLabel,
  placeTone,
  refreshNote,
  roomNote,
  scoreLabel,
  setLine,
  setSummary,
  weekLabel,
} from "../season";
import { recsReason, when } from "../seasonStatus";
import { Chevron } from "./icons";
import { StatusDot } from "./StatusLight";

/** What a league's block does: open its page (on a view), solve today's moves, read Yahoo again,
 * open its freshness sheet, and open or close its panel. */
export interface BlockActions {
  onOpen: () => void;
  onLineup: () => void;
  onSolve: () => void;
  onRefresh: () => void;
  onStatus: () => void;
  onToggle: () => void;
}

export interface BlockProps extends BlockActions {
  s: SeasonSummary;
  now: number;
  best: BestMove | undefined;
  lookError: Error | null;
  solving: boolean;
  solveError: string | null;
  refreshing: boolean;
  status: StatusPayload | undefined;
  open: boolean;
}

const formatOf = (s: SeasonSummary) => (s.scoring === "points" ? "H2H points" : "H2H categories");

/** A league in the landing table (#191): row 1 the facts in the header's columns, row 2 the
 * format, my team, the week, the recommended set in a line and why the recommendations are not
 * up to date; the chevron opens the panel under them. The private league is pinned: an accent
 * border on the `--mine` tint. */
export function LeagueBlock(props: BlockProps) {
  const { s, now, best, status, open, onOpen, onRefresh, onStatus, onToggle, refreshing } = props;
  const title = s.name ?? `League ${s.league}`;
  const pinned = s.public === false;
  const running = isRefreshing(s) || refreshing;
  const failed = s.refresh?.status === "failed";
  const readNote = refreshNote(s.refresh) || `read ${ageLabel(s.updated_at, now)}`;
  const reason = recsReason(status, s.league);
  const panel = `lt-panel-${s.league}`;
  const sub = [
    `${formatOf(s)}${pinned ? " · private" : ""}`,
    s.my_team?.name,
    s.week != null ? weekLabel(s).toLowerCase() : null,
    best?.status === "solved" ? setSummary(best) : null,
  ].filter(Boolean);
  return (
    <article className={`lt-block${pinned ? " pinned" : ""}`} aria-label={title}>
      <div className="lt-main">
        <button
          className="icon lt-chev"
          aria-expanded={open}
          aria-controls={panel}
          aria-label={`${open ? "Close" : "Open"} the recommended set and facts of ${title}`}
          onClick={onToggle}
        >
          <Chevron dir={open ? "down" : "right"} />
        </button>
        <span className="lt-name">
          <button className="link" onClick={onOpen} title="Open its league page">
            {title}
          </button>
          {pinned && <span className="tag accent">private</span>}
        </span>
        <span className="lt-score">
          <span className="big" title={s.scoring === "points" ? "this week's points so far, mine first" : "categories won so far this week, mine first"}>
            {scoreLabel(s)}
          </span>
          <small>{s.opponent ? `vs ${s.opponent.name}` : "no opponent read"}</small>
        </span>
        <span className={placeTone(s)}>{placeLabel(s)}</span>
        <span className={s.adds?.limit == null ? "muted" : ""} title={s.adds ? addsNote(s.adds) : undefined}>
          {addsLeft(s.adds)}
        </span>
        <span className={s.flags?.["must-add"] || s.flags?.add ? "accent" : "muted"} title={s.flags_error ?? "the waiver pool's breakout flags, by level"}>
          {s.flags_error ? "flags did not read" : flagCounts(s.flags)}
        </span>
        <BestCells {...props} />
        <span className="lt-read">
          <StatusDot p={status} league={s.league} onOpen={onStatus} word={false} />
          <span className={failed ? "bad" : running ? "accent" : isStale(s.updated_at, now) ? "dim" : "muted"} title={s.refresh?.error ?? s.updated_at ?? undefined}>
            {readNote}
          </span>
        </span>
        <span className="lt-acts">
          {s.public && !running && (
            <button className="link" onClick={onRefresh} title="Read the league's public Yahoo pages again (about 20 s)">
              refresh
            </button>
          )}
          <SolveButton {...props} />
        </span>
        <div className="lt-sub">
          {sub.map((x) => (
            <span key={x}>{x}</span>
          ))}
          {reason && <span className="accent">{reason}</span>}
        </div>
      </div>
      {open && <LeagueDetail {...props} id={panel} readNote={readNote} reason={reason} />}
    </article>
  );
}

/** Solve, only while today's moves are not solved: a solved league's answer is current for its
 * inputs, and a newer read makes it unsolved again. */
function SolveButton({ s, best, solving, onSolve }: BlockProps) {
  if (!s.my_team || solving || best?.status !== "not_solved") return null;
  return (
    <button className="small" onClick={onSolve} title="Solve today's moves for this league (a few seconds)">
      Solve
    </button>
  );
}

/** The Best move and Gain columns: the best recommended move, or why there is none yet. */
function BestCells({ s, best, lookError, solving, solveError }: BlockProps) {
  const error = solveError ?? lookError?.message;
  const one = (text: string, className: string, title?: string) => (
    <>
      <span className={`lt-move ${className}`} title={title}>
        {text}
      </span>
      <span />
    </>
  );
  if (!s.my_team) return one("my team is not read", "dim");
  if (solving) return one("solving the moves… (a few seconds)", "dim");
  if (error) return one(error, "bad");
  if (!best) return one("looking for a solved move…", "dim");
  if (best.status === "not_solved") return one("not solved yet", "dim");
  if (!best.move) return one(bestLine(best), "dim", `over ${best.label}`);
  const unit = s.scoring === "points" ? "matchups won" : "categories won";
  return (
    <>
      <span className="lt-move" title={`over ${best.label}`}>
        {bestLine(best)}
      </span>
      <span className="good lt-gain" title={`expected ${unit} the move adds over ${best.label}`}>
        {gainLabel(best.move.gain)}
      </span>
    </>
  );
}

/** The panel under a league's rows: the whole recommended set, each move with its gain on the
 * best move's horizon and its basis (#187), the room; the facts and the league's buttons. It
 * never solves: its Solve is the row's, shown only when today's moves are not solved. */
function LeagueDetail(props: BlockProps & { id: string; readNote: string; reason: string | null }) {
  const { s, now, id, readNote, reason, onOpen, onLineup, onRefresh } = props;
  const running = isRefreshing(s) || props.refreshing;
  const yahoo = [`${readNote}${s.public ? "" : " via the extension"}`, s.updated_at ? `(${when(s.updated_at, new Date(now))})` : null].filter(Boolean).join(" ");
  return (
    <div className="lt-detail" id={id}>
      <div className="lt-set">
        <span className="k">Recommended set</span>
        <SetLines {...props} />
      </div>
      <div className="lt-facts">
        <dl>
          <dt className="k">Format</dt>
          <dd>
            {formatOf(s)} · {s.public ? "public" : "private"}
          </dd>
          <dt className="k">Team</dt>
          <dd>{s.my_team?.name ?? "not read"}</dd>
          <dt className="k">Week</dt>
          <dd>{weekLabel(s)}</dd>
          <dt className="k">Flags</dt>
          <dd>{s.flags_error ? "flags did not read" : `${flagCounts(s.flags) || "none"} in the waiver pool`}</dd>
          <dt className="k">Yahoo</dt>
          <dd>
            {yahoo}
            {reason && <span className="accent"> · {reason}</span>}
          </dd>
        </dl>
        <div className="lt-btns">
          <button className="small primary" onClick={onOpen}>
            Open league
          </button>
          <button className="small" onClick={onLineup} title="Open the league page on its Lineup view">
            Lineup
          </button>
          <SolveButton {...props} />
          {s.public && (
            <button className="link" disabled={running} onClick={onRefresh} title="Read the league's public Yahoo pages again (about 20 s)">
              {running ? refreshNote(s.refresh) || "refreshing…" : "refresh"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function SetLines({ s, best, lookError, solving, solveError }: BlockProps) {
  const error = solveError ?? lookError?.message;
  if (!s.my_team) return <span className="dim">my team is not read</span>;
  if (solving) return <span className="dim">solving the moves… (a few seconds)</span>;
  if (error) return <span className="bad">{error}</span>;
  if (!best) return <span className="dim">looking for a solved move…</span>;
  if (best.status === "not_solved") return <span className="dim">not solved yet: Solve finds today's set</span>;
  const name = bestNamer(best);
  return (
    <>
      <span className="muted">{setSummary(best)}</span>
      {best.set ? (
        best.set.length > 0 && (
          <div className="lt-lines">
            {best.set.map((m) => {
              const line = setLine(m, name);
              return (
                <div key={`${m.add}-${m.drop}`} className="lt-line">
                  <span>{line.text}</span>
                  <span className="good">{gainLabel(m.gain)}</span>
                  <span className="muted" title={line.basis.title}>
                    {line.kind}
                  </span>
                </div>
              );
            })}
          </div>
        )
      ) : best.move ? (
        <div className="lt-lines">
          <div className="lt-line">
            <span>{bestLine(best)}</span>
            <span className="good">{gainLabel(best.move.gain)}</span>
            <span className="dim">the best of them</span>
          </div>
        </div>
      ) : null}
      {best.room && <span className="muted">Room: {roomNote(best.room, name)}</span>}
    </>
  );
}

/** A league with a read error or no snapshot: one row with its error or "not read yet" and,
 * for a public league, the read-it-now link. */
export function UnreadBlock({
  s,
  status,
  refreshing,
  onRefresh,
  onStatus,
}: Pick<BlockProps, "s" | "status" | "refreshing" | "onRefresh" | "onStatus">) {
  const title = s.name ?? `League ${s.league}`;
  return (
    <article className={`lt-block unread${s.public === false ? " pinned" : ""}`} aria-label={title}>
      <div className="lt-main">
        <span />
        <span className="lt-name">
          <span className="name">{title}</span>
          {s.public === false && <span className="tag accent">private</span>}
        </span>
        <span className="lt-wide">
          {s.error ? (
            <span className="bad">{s.error}</span>
          ) : (
            <span className="dim">{s.public ? "not read yet" : "not read yet: open its pages in Chrome with the extension"}</span>
          )}
        </span>
        <span className="lt-read">
          <StatusDot p={status} league={s.league} onOpen={onStatus} word={false} />
        </span>
        <span className="lt-acts">
          {s.public && !s.error && (
            <button className="link" disabled={isRefreshing(s) || refreshing} onClick={onRefresh}>
              {isRefreshing(s) ? refreshNote(s.refresh) : "read it now"}
            </button>
          )}
        </span>
        <div className="lt-sub">
          <span>
            {formatOf(s)}
            {s.public === false ? " · private" : ""}
          </span>
        </div>
      </div>
    </article>
  );
}
