import { useCallback, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type LeagueSummary, type ProgressPayload, type RoomSummary } from "../api";
import { DRAFT_SEASON_DAYS, draftDay, draftsAhead, finishedDrafts, LAYOUTS, pageFor, ROW_CONTROLS, rowClickOpens, type Layout } from "../format";
import { landingKeys, type SeasonViewId } from "../keys";
import { useHotkeys } from "../useKeys";
import DraftSeason from "./DraftSeason";
import DraftsDrawer, { type DrawerView } from "./DraftsDrawer";
import ExecuteTime from "./ExecuteTime";
import LeagueGrid from "./LeagueGrid";
import { useLandingOrder } from "./landingOrder";
import AppBarLead from "./AppBarLead";
import { OverviewStatus } from "./StatusLight";
import Wordmark from "./Wordmark";
import { POOLED, rangeSum, recordLabel, scopeWeeks } from "../progress";
import { queueFoldLine, queuePoll } from "../season";
import { useNow } from "./YahooSync";

const LAYOUT_KEY = "pickandroll.layout";

function savedLayout(): Layout {
  try {
    const v = localStorage.getItem(LAYOUT_KEY);
    return v === "season" || v === "draft" ? v : "auto";
  } catch {
    return "auto";
  }
}

/** The landing page (#108): a Layout control (auto, in season, draft season) over the
 * draft-season page or the in-season grid. Auto is the draft-season page while a league's
 * draft runs or is less than fourteen days away. */
export default function Landing({
  onOpenLeague,
  onOpenSession,
  onProgress,
  onQueue,
  error,
}: {
  onOpenLeague: (league: string, view?: SeasonViewId) => void;
  onOpenSession: (id: string) => void;
  onProgress: () => void;
  onQueue: () => void;
  error: Error | null;
}) {
  const [layout, setLayoutState] = useState<Layout>(savedLayout);
  const setLayout = (l: Layout) => {
    setLayoutState(l);
    try {
      localStorage.setItem(LAYOUT_KEY, l);
    } catch {
      // The choice is a convenience: without storage it is auto next time.
    }
  };
  const leagues = useQuery({ queryKey: ["leagues"], queryFn: api.leagues, refetchInterval: 30_000 });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: api.rooms, refetchInterval: 5000 });
  // The table's leagues in its order (#191), shared with the overview sheet's rows (#253).
  const landing = useLandingOrder();
  const shown = [...landing.rows.pinned, ...landing.rows.rest];
  const now = useNow(30_000);
  const [drawer, setDrawer] = useState<DrawerView | null>(null);
  // The New draft form's league from a draft card's Set up; the key starts the form over.
  const [setup, setSetupState] = useState<{ key: number; league?: string }>({ key: 0 });
  const onSetUp = (league: string) => {
    setSetupState((x) => ({ key: x.key + 1, league }));
    setDrawer("new");
  };
  const closeDrawer = useCallback(() => setDrawer(null), []);
  useHotkeys(landingKeys(drawer ? null : onQueue));
  const ready = leagues.data !== undefined || leagues.isError;
  const page = pageFor(layout, leagues.data ?? [], rooms.data ?? [], now);
  const soon = draftsAhead(leagues.data ?? [], rooms.data ?? [], now).filter((l) => l.draft_time && Date.parse(l.draft_time) < now + DRAFT_SEASON_DAYS * 86_400_000);
  // The draft-season page's bar is as it was; in season the table carries the week (#270).
  const status = `draft season · ${soon.length || "no"} draft${soon.length === 1 ? "" : "s"} in the next ${DRAFT_SEASON_DAYS} days`;
  return (
    <main className="shell">
      <header className="topbar">
        {page === "draft" ? (
          <>
            <Wordmark onHome={closeDrawer} />
            {ready && <span className="muted">{status}</span>}
          </>
        ) : (
          <AppBarLead onHome={closeDrawer} status={<OverviewStatus leagues={shown} now={now} />} onProgress={onProgress} />
        )}
        <span className="grow" />
        <span className="modeswitch">
          <span className="k">Layout</span>
          <span className="seg" role="group" aria-label="Layout">
            {LAYOUTS.map((l) => (
              <button key={l.id} className={layout === l.id ? "on" : ""} aria-pressed={layout === l.id} title={l.title} onClick={() => setLayout(l.id)}>
                {l.label}
              </button>
            ))}
          </span>
        </span>
      </header>
      {error && <p className="error" style={{ padding: "0 24px" }}>{error.message}</p>}
      {!ready ? (
        <p className="muted" style={{ padding: 24 }}>
          Reading the leagues…
        </p>
      ) : page === "draft" ? (
        <DraftSeason now={now} setup={setup} onSetUp={(league) => setSetupState((x) => ({ key: x.key + 1, league }))} onOpenSession={onOpenSession} onOpenLeague={onOpenLeague} />
      ) : (
        <div className="landing-grid">
          <LeagueGrid landing={landing} onOpen={onOpenLeague} />
          <ProgressFold onOpen={onProgress} />
          <QueueFold onOpen={onQueue} />
          <DraftsFold leagues={leagues.data ?? []} rooms={rooms.data ?? []} now={now} onDrafts={() => setDrawer("drafts")} onNew={() => setDrawer("new")} />
        </div>
      )}
      {drawer && page === "season" && (
        <DraftsDrawer view={drawer} setView={setDrawer} setup={setup} onSetUp={onSetUp} onClose={closeDrawer} onOpenSession={onOpenSession} now={now} />
      )}
    </main>
  );
}

/** A fold the whole of which opens its screen (#274): a click anywhere on it, except in one of
 * its controls or at the end of a text selection. Its button stays the keyboard's way in, so
 * the row itself is no tab stop. */
function OpenRow({ onOpen, children }: { onOpen: () => void; children: ReactNode }) {
  return (
    <div
      className="fold open-row"
      onClick={(e) => {
        const inControl = e.target instanceof Element && e.target.closest(ROW_CONTROLS) != null;
        if (rowClickOpens(inControl, window.getSelection()?.toString() ?? "")) onOpen();
      }}
    >
      {children}
    </div>
  );
}

/** The Progress screen (#129) in one line: the weeks scored, the public leagues' record
 * against expected, and the knob change pending. */
function ProgressFold({ onOpen }: { onOpen: () => void }) {
  const q = useQuery({ queryKey: ["progress"], queryFn: api.progress, refetchInterval: 600_000 });
  return (
    <OpenRow onOpen={onOpen}>
      <span className="k">Progress</span>
      <span className="muted">{q.data ? progressLine(q.data) : q.isError ? "not read" : "reading…"}</span>
      <span className="grow" />
      <button className="small" onClick={onOpen} title="the hill-climb over the season: every league against its expectation, the knob changes and the Monday notes">
        Progress
      </button>
    </OpenRow>
  );
}

function progressLine(p: ProgressPayload): string {
  if (!p.last_recorded) return "no week scored yet: the Monday recorder scores each week once it ends";
  const sum = rangeSum(scopeWeeks(p, POOLED));
  const pending = p.knobs.changes.find((c) => !c.verdict);
  return [
    `${p.last_recorded} week${p.last_recorded === 1 ? "" : "s"} scored`,
    sum.projected ? `public leagues ${recordLabel(sum.record)} against ${sum.expected.toFixed(1)} expected` : null,
    pending ? `${pending.id} pending` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The moves executor's queue today (#171) in one line, the day's execute time (#193) and the
 * Queue screen (#194), every league's entries and their veto in one view. */
function QueueFold({ onOpen }: { onOpen: () => void }) {
  const q = useQuery({ queryKey: ["queue"], queryFn: () => api.queue(), refetchInterval: (query) => queuePoll(query.state.data) });
  return (
    <OpenRow onOpen={onOpen}>
      <span className="k">Queue</span>
      <span className="muted">{q.data ? queueFoldLine(q.data) : q.isError ? "not read" : "reading…"}</span>
      <span className="grow" />
      <ExecuteTime q={q.data} />
      <button className="small" onClick={onOpen} title="every league's proposed moves today in one view, with the veto (q)">
        Queue
      </button>
    </OpenRow>
  );
}

/** In season the drafts fold into one line: what is ahead, live and finished, and the drawer. */
function DraftsFold({ leagues, rooms, now, onDrafts, onNew }: { leagues: LeagueSummary[]; rooms: RoomSummary[]; now: number; onDrafts: () => void; onNew: () => void }) {
  const ahead = draftsAhead(leagues, rooms, now);
  const live = rooms.filter((r) => !r.complete).length;
  const finished = finishedDrafts(leagues, rooms, now);
  const day = (l: LeagueSummary) => new Date(Date.parse(l.draft_time!)).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const dated = finished.filter((l) => l.draft_time);
  const parts = [
    ahead.length ? `${ahead.length} ahead, the next ${draftDay(ahead[0].draft_time)}` : "none ahead",
    ...(live ? [`${live} live`] : []),
    ...(finished.length ? [`${finished.length} finished${dated.length ? ` (${day(dated[dated.length - 1])} – ${day(dated[0])})` : ""}`] : []),
  ];
  return (
    <div className="fold">
      <span className="k">Drafts</span>
      <span className="muted">{parts.join(" · ")}</span>
      <span className="grow" />
      <button className="small" onClick={onDrafts}>
        Drafts
      </button>
      <button className="small primary" onClick={onNew}>
        New draft
      </button>
    </div>
  );
}
