import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type LeagueSummary, type RoomSummary } from "../api";
import { DRAFT_SEASON_DAYS, draftDay, draftsAhead, finishedDrafts, LAYOUTS, pageFor, type Layout } from "../format";
import DraftSeason from "./DraftSeason";
import DraftsDrawer, { type DrawerView } from "./DraftsDrawer";
import LeagueGrid from "./LeagueGrid";
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
  error,
}: {
  onOpenLeague: (league: string) => void;
  onOpenSession: (id: string) => void;
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
  const seasons = useQuery({ queryKey: ["seasons"], queryFn: api.seasons });
  const now = useNow(30_000);
  const [drawer, setDrawer] = useState<DrawerView | null>(null);
  // The New draft form's league from a draft card's Set up; the key starts the form over.
  const [setup, setSetupState] = useState<{ key: number; league?: string }>({ key: 0 });
  const onSetUp = (league: string) => {
    setSetupState((x) => ({ key: x.key + 1, league }));
    setDrawer("new");
  };
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const ready = leagues.data !== undefined || leagues.isError;
  const page = pageFor(layout, leagues.data ?? [], rooms.data ?? [], now);
  const soon = draftsAhead(leagues.data ?? [], rooms.data ?? [], now).filter((l) => l.draft_time && Date.parse(l.draft_time) < now + DRAFT_SEASON_DAYS * 86_400_000);
  const read = (seasons.data ?? []).filter((s) => s.has_snapshot && !s.error);
  const week = read.find((s) => s.week != null);
  const status =
    page === "draft"
      ? `draft season · ${soon.length || "no"} draft${soon.length === 1 ? "" : "s"} in the next ${DRAFT_SEASON_DAYS} days`
      : `${read.length} league${read.length === 1 ? "" : "s"} in season${week ? ` · week ${week.week}${week.end_week ? ` of ${week.end_week}` : ""}` : ""}`;
  return (
    <main className="shell">
      <header className="topbar">
        <div className="wordmark">
          PICK<span>&amp;</span>ROLL
        </div>
        {ready && <span className="muted">{status}</span>}
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
          <LeagueGrid onOpen={onOpenLeague} />
          <DraftsFold leagues={leagues.data ?? []} rooms={rooms.data ?? []} now={now} onDrafts={() => setDrawer("drafts")} onNew={() => setDrawer("new")} />
        </div>
      )}
      {drawer && page === "season" && (
        <DraftsDrawer view={drawer} setView={setDrawer} setup={setup} onSetUp={onSetUp} onClose={closeDrawer} onOpenSession={onOpenSession} now={now} />
      )}
    </main>
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
