import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, LEAGUE_FROM_ADP, LEAGUE_SURVIVAL_DEFAULT, SPREAD, type LeagueSummary, type Objective, type SessionCreateBody, type SessionSummary, type SurvivalMode } from "../api";
import { blendLabel, draftsAhead, draftWhen, leagueSurvivalText } from "../format";
import { createWithCurveFallback } from "../sessionRequest";
import Info from "./Info";
import { erroredRow, isMine, KeeperEditor, keeperDraft, keepersIn, nameOptions, type KeeperDraft } from "./Keepers";
import { SeenRooms, useSeenRooms } from "./YahooSync";

/** A survival choice in the strategy's one-line summary. */
const SURVIVAL_SHORT: Record<SurvivalMode, string> = {
  none: "ADP formula",
  simulate: "simulated drafts",
  league: "this league's drafts by ADP",
  file: "a saved survival table",
};

/** The curve select's value for the league's own drafted rosters (curve=league). */
const LEAGUE_ROSTERS = "@league-rosters";

interface Props {
  onCreated: (session: SessionSummary) => void;
  /** The league the form starts on (a draft card's Set up). */
  initialLeague?: string;
}

/** The New draft form (#108: short): a league with a draft ahead or a draft set up by hand, the
 * input files folded into one line, and the strategy in a disclosure. */
export default function SessionSetup({ onCreated, initialLeague }: Props) {
  const queryClient = useQueryClient();
  const projections = useQuery({ queryKey: ["projections"], queryFn: api.projections });
  const survivalFiles = useQuery({ queryKey: ["files", "survival"], queryFn: () => api.files("survival") });
  const leagueFiles = useQuery({ queryKey: ["files", "league"], queryFn: () => api.files("league") });
  const curveFiles = useQuery({ queryKey: ["files", "curve"], queryFn: () => api.files("curve") });
  const adpFiles = useQuery({ queryKey: ["files", "adp"], queryFn: () => api.files("adp") });
  const keeperFiles = useQuery({ queryKey: ["files", "keepers"], queryFn: () => api.files("keepers") });
  const leagueFolders = useQuery({ queryKey: ["leagues"], queryFn: api.leagues });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: api.rooms });
  // Only the leagues whose draft is still ahead: a finished draft has nothing to set up.
  const ahead = draftsAhead(leagueFolders.data ?? [], rooms.data ?? [], Date.now());
  // A league folder (#67): its session takes the teams, roster, scoring, players file and
  // survival from data/leagues/<id>/ and its format's archive, as the draft-day attach does.
  const [leagueId, setLeagueId] = useState(initialLeague ?? "");
  // The input files fold into one line until "change" opens them; the strategy into its summary.
  const [inputsOpen, setInputsOpen] = useState(false);
  const [strategyOpen, setStrategyOpen] = useState(false);
  const [file, setFile] = useState("");
  const [positionsFile, setPositionsFile] = useState("");
  const [adpFile, setAdpFile] = useState("");
  const [numTeams, setNumTeams] = useState(12);
  const [position, setPosition] = useState(1);
  const [myTeam, setMyTeam] = useState("me");
  const [bench, setBench] = useState(3);
  const [objective, setObjective] = useState<Objective>("win");
  const [sigmaScale, setSigmaScale] = useState(1);
  // null until the user picks: the league's resolved curve, else the simulated one.
  const [curveFile, setCurveFile] = useState<string | null>(null);
  // null until the user picks: the form then shows, and leaves to the server, its default.
  const [survivalChoice, setSurvival] = useState<SurvivalMode | null>(null);
  const [survivalSims, setSurvivalSims] = useState(300);
  const [survivalFile, setSurvivalFile] = useState("");
  const [leagueFile, setLeagueFile] = useState("");
  const [solveAhead, setSolveAhead] = useState(true);
  const [timeLimit, setTimeLimit] = useState(20);
  const [roomId, setRoomId] = useState("");
  // The room's own team count when the extension has shown it: the attach is checked against it.
  const [roomTeams, setRoomTeams] = useState<number | null>(null);
  const seen = useSeenRooms();
  // A session made whose room did not attach, or that fell back to the simulated curve: the
  // reasons, and the way on to the draft.
  const [made, setMade] = useState<{ session: SessionSummary; attachError: string | null; curveNote: string | null } | null>(null);
  // Keepers: rows from a file in data/ (mine unticked until I decide), added by hand or pasted.
  const [keepersOpen, setKeepersOpen] = useState(false);
  const [keeperFile, setKeeperFile] = useState("");
  const [keepers, setKeepers] = useState<KeeperDraft[]>([]);
  const projectionFile = file || projections.data?.[0]?.file || "";
  const names = useQuery({
    queryKey: ["projection-players", projectionFile],
    queryFn: () => api.projectionPlayers(projectionFile),
    enabled: keepersOpen && !!projectionFile,
    staleTime: Infinity,
  });
  const options = useMemo(() => nameOptions(names.data ?? []), [names.data]);
  const loadKeepers = useMutation({
    mutationFn: api.keepersFile,
    onSuccess: (r) =>
      setKeepers(
        r.rows.map((row) =>
          // My rows (no team, or the team at my pick) come unticked until I decide.
          keeperDraft({ on: !isMine(row, position), position: row.position, round: row.round, player: row.player ?? row.player_id ?? "", player_id: row.player_id ?? null, label: row.label }),
        ),
      ),
  });
  const keptCount = keepers.filter((k) => k.on).length;
  const league: LeagueSummary | undefined = leagueId ? ahead.find((l) => l.league === leagueId && l.resolved) : undefined;
  const resolved = league?.resolved ?? null;
  const teams = resolved ? (league?.num_teams ?? 12) : numTeams;
  // The server's default: a league's resolved survival; by hand, the home league's own table
  // when data/ holds it, else a simulation.
  const hasDefaultTable = !!leagueFiles.data?.some((f) => f.file === LEAGUE_SURVIVAL_DEFAULT);
  const survival: SurvivalMode = survivalChoice ?? (resolved ? resolved.survival : hasDefaultTable ? "league" : "simulate");
  // The default table, else one league table is the table; with several the user picks one (an
  // overall-space table listed beside the keeper-adjusted one must never be taken by default).
  const leagueTable =
    leagueFile || (hasDefaultTable ? LEAGUE_SURVIVAL_DEFAULT : leagueFiles.data?.length === 1 ? leagueFiles.data[0].file : "");
  // A league's table is its folder's or its format's: only a draft set up by hand picks one.
  const pickTable = !resolved && survival === "league";
  const needsTable = pickTable && !leagueTable;
  // Untouched, the request names no survival: the server resolves it, and says why when the
  // league table cannot serve the draft (too few picks for the teams, say) and it simulates.
  const survivalChosen = survivalChoice !== null || (!resolved && leagueFile !== "");
  const curve = curveFile ?? (resolved?.curve === "league" ? LEAGUE_ROSTERS : "");
  const leagueCurve = objective === "win" && curve === LEAGUE_ROSTERS;

  const create = useMutation({
    mutationFn: async () => {
      const body: SessionCreateBody = {
        projection_file: projectionFile,
        // A league's fields are left out: a field sent, even null, wins over its folder's.
        ...(league
          ? { league: league.league }
          : { num_teams: numTeams, bench, positions_file: positionsFile || null, adp_file: adpFile || null }),
        my_position: position,
        my_team: myTeam,
        objective,
        sigma_scale: sigmaScale,
        // "league" is the league's own drafted rosters; anything else names a curve file.
        curve_file: curve && curve !== LEAGUE_ROSTERS ? curve : null,
        ...(leagueCurve ? { curve: "league" as const } : {}),
        ...(survivalChosen
          ? {
              survival,
              survival_file:
                survival === "file"
                  ? survivalFile || survivalFiles.data?.[0]?.file || null
                  : survival === "league"
                    ? leagueTable || null
                    : null,
            }
          : {}),
        survival_sims: survivalSims,
        solve_ahead: solveAhead,
        time_limit: timeLimit,
        keepers: keepersOpen ? keepersIn(keepers, options) : [],
      };
      // The league curve the folder resolved falls back to the simulated one when it cannot be
      // fit (the draft-day attach's rule); one the user chose fails as it is.
      const { session, curveNote } = await createWithCurveFallback(api.createSession, body, leagueCurve && curveFile === null);
      if (!roomId.trim()) return { session, attachError: null, curveNote };
      try {
        await api.attachRoom(session.id, { draft_id: roomId.trim(), slot: position, room_teams: roomTeams });
        return { session, attachError: null, curveNote };
      } catch (e) {
        return { session, attachError: e instanceof Error ? e.message : String(e), curveNote };
      }
    },
    onMutate: () => setMade(null),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      if (result.attachError || result.curveNote) setMade(result);
      else onCreated(result.session);
    },
  });
  const files = projections.data ?? [];
  const hasDefaultAdp = (adpFiles.data ?? []).some((f) => f.file === "adp.csv");
  const strategyLine = [
    objective === "win" ? `categories won${sigmaScale !== 1 ? ` (spread ×${sigmaScale})` : ""}` : "sum of z",
    ...(objective === "win" ? [curve === LEAGUE_ROSTERS ? "the league's drafted rosters" : curve || (league?.scoring === "points" ? "flat points curve" : "simulated curve")] : []),
    survivalChoice === null && resolved ? "the league's survival" : SURVIVAL_SHORT[survival],
  ].join(" · ");
  const inputsLine = [
    projectionFile || "no projections in data/",
    resolved
      ? resolved.adp_file
        ? `ADP, positions and rank: ${resolved.adp_file}`
        : "no Yahoo players file"
      : `positions: ${positionsFile || "data/positions.csv if present"} · ADP: ${adpFile || (hasDefaultAdp ? "data/adp.csv" : "value rank")}`,
  ].join(" · ");
  const perDraft = 1.2;
  const workers = 8;
  const simMinutes = (survivalSims * perDraft) / workers / 60;

  return (
    <section className="panel setup">
      <h2>NEW DRAFT</h2>
      {ahead.length > 0 ? (
        <label>
          <span className="k">
            League <span className="muted">(optional)</span>
            <Info title="league">
              <b>A Yahoo league in data/leagues/: its folder sets the draft up.</b>
              <span>The teams, roster and scoring come from its settings.json; ADP, positions and Yahoo's rank from its yahoo_players.json. Survival comes from the league's own table, else its format's table fit from this season's earlier drafts, else a simulation against this board; another league's table never serves it.</span>
              <span>The league curve is chosen once its format's table has the drafted rosters, as the draft-day attach does; when it cannot be fit the draft goes on with the simulated one and says why.</span>
            </Info>
          </span>
          <select
            value={league && ahead.includes(league) ? leagueId : ""}
            onChange={(e) => {
              setLeagueId(e.target.value);
              // A league's survival and curve are its own: what was picked by hand starts over.
              setSurvival(null);
              setLeagueFile("");
              setCurveFile(null);
            }}
          >
            <option value="">none: set the draft up by hand</option>
            {ahead.map((l) => (
              <option key={l.league} value={l.league} disabled={!l.resolved} title={l.error ?? undefined}>
                {l.league} · {l.scoring === "points" ? "H2H points" : "H2H categories"} · {draftWhen(l.draft_time, Date.now())}
                {l.error ? " (its folder does not read)" : ""}
              </option>
            ))}
          </select>
          <span className="muted" style={{ fontSize: 12 }}>
            only the leagues with a draft ahead, or by hand
          </span>
        </label>
      ) : (
        <p className="muted" style={{ margin: 0, fontSize: 12 }}>
          No league has a draft ahead: set the draft up by hand.
        </p>
      )}
      {resolved && (
        <p className="muted" style={{ margin: "-4px 0 0", fontSize: 12 }}>
          {teams} teams, {resolved.rounds ?? "?"} rounds, {league!.scoring === "points" ? "H2H points: one category, fantasy points by the league's weights" : "H2H categories: the league's categories"}. Survival: {leagueSurvivalText(resolved)}.
        </p>
      )}
      <div className="chosen">
        <span className="k">Inputs</span>
        <span>{inputsLine}</span>
        <span className="grow" />
        <button className="link" onClick={() => setInputsOpen((o) => !o)} aria-expanded={inputsOpen}>
          {inputsOpen ? "done" : "change"}
        </button>
      </div>
      {inputsOpen && (
        <>
          <label>
            <span className="k">Projections</span>
            <select value={file || files[0]?.file || ""} onChange={(e) => setFile(e.target.value)}>
              {files.map((p) => (
                <option key={p.file} value={p.file}>
                  {p.file}
                </option>
              ))}
            </select>
          </label>
          {!resolved && (
            <>
              <label>
                <span className="k">Positions from <span className="muted">(optional)</span></span>
                <select value={positionsFile} onChange={(e) => setPositionsFile(e.target.value)}>
                  <option value="">none, use data/positions.csv if present</option>
                  {files.map((p) => (
                    <option key={p.file} value={p.file}>
                      {p.file}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="k">ADP from <span className="muted">(optional, Yahoo replaces it)</span></span>
                <select value={adpFile} onChange={(e) => setAdpFile(e.target.value)}>
                  <option value="">{hasDefaultAdp ? "data/adp.csv" : "none: rank by projected value"}</option>
                  {(adpFiles.data ?? [])
                    .filter((f) => f.file !== "adp.csv")
                    .map((f) => (
                      <option key={f.file} value={f.file}>
                        {f.file}
                      </option>
                    ))}
                  {files.map((p) => (
                    <option key={p.file} value={p.file}>
                      {p.file}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
        </>
      )}
      {resolved && !resolved.adp_file && (
        <p className="warn">
          League {league!.league} has no yahoo_players.json: the board's ADP will be Basketball Monster's value rank. Fetch it with scripts/draft_day.py refresh {league!.league}.
        </p>
      )}
      {!resolved && !adpFile && !hasDefaultAdp && (
        <p className="warn">
          No ADP file in data/. The board's ADP will be Basketball Monster's value rank, which puts specialists far later than real drafts do.
          Save one as data/adp.csv with columns player,adp (a FantasyPros export works too).
        </p>
      )}
      <div className="row">
        <label>
          <span className="k">Teams</span>
          <input type="number" min={2} max={20} value={teams} disabled={!!resolved} title={resolved ? "from the league's settings" : undefined} onChange={(e) => setNumTeams(+e.target.value)} />
        </label>
        <label>
          <span className="k">My pick</span>
          <input type="number" min={1} max={teams} value={position} onChange={(e) => setPosition(+e.target.value)} />
        </label>
        {resolved ? (
          <label title="from the league's roster">
            <span className="k">Rounds</span>
            <input type="number" value={resolved.rounds ?? ""} disabled />
          </label>
        ) : (
          <label>
            <span className="k">Bench</span>
            <input type="number" min={0} max={6} value={bench} onChange={(e) => setBench(+e.target.value)} />
          </label>
        )}
        <label style={{ flexGrow: 1 }}>
          <span className="k">My team name</span>
          <input value={myTeam} onChange={(e) => setMyTeam(e.target.value)} />
        </label>
      </div>

      <label>
        <span className="k">
          Yahoo draft room <span className="muted">(optional)</span>
          <Info title="YAHOO SYNC">
            <b>Attach the Yahoo draft room open in Chrome as the draft starts.</b>
            <span>The pickandroll extension in the draft tab sends the room's picks here as they are made, and the plan follows them. The room is attached in mirror for your pick above: nothing is drafted for you until you arm autopilot on the sync card (8).</span>
            <span>The draft id is in the room's address. You can also attach later from the sync card.</span>
          </Info>
        </span>
        <input
          value={roomId}
          onChange={(e) => {
            setRoomId(e.target.value);
            setRoomTeams(null);
          }}
          placeholder="draft id, or leave empty for manual entry"
          spellCheck={false}
        />
      </label>
      <SeenRooms
        rooms={(seen.data ?? []).filter((r) => r.draft_id !== roomId.trim())}
        action="Use"
        onPick={(r) => {
          setRoomId(r.draft_id);
          setRoomTeams(r.room_teams);
          if (r.room_teams) setNumTeams(r.room_teams);
          if (r.slot) setPosition(r.slot);
        }}
      />
      {roomId.trim() && roomTeams !== null && (
        <p className="muted" style={{ margin: "-4px 0 0", fontSize: 12 }}>
          Room {roomId.trim()} shows {roomTeams} teams{roomTeams !== teams ? `, not ${teams}: the attach will be refused` : ""}.
        </p>
      )}

      <label className="inline">
        <input type="checkbox" checked={keepersOpen} onChange={(e) => setKeepersOpen(e.target.checked)} />
        <span className="k">Keepers</span>
        <span className="muted">{keepersOpen && keptCount ? `${keptCount} kept` : "(keeper league)"}</span>
        <Info title="keepers">
          <b>Each keeper takes his team's pick in the round he costs.</b>
          <span>His pick is logged when the draft reaches it, nobody else can draft him, and the plan counts my keepers on my roster from the start.</span>
          <span>Rows from a keepers file in data/ (position,round,player; position me for mine) come with my own keepers unticked until I decide; a row for the team at my pick is mine too. On draft night, add the other teams' keepers here or later from the log card (6).</span>
        </Info>
      </label>
      {keepersOpen && (
        <>
          {(keeperFiles.data?.length ?? 0) > 0 && (
            <label>
              <span className="k">From a file in data/</span>
              <select
                value={keeperFile}
                onChange={(e) => {
                  setKeeperFile(e.target.value);
                  if (e.target.value) loadKeepers.mutate(e.target.value);
                  else setKeepers([]);
                }}
              >
                <option value="">none</option>
                {keeperFiles.data!.map((f) => (
                  <option key={f.file} value={f.file}>
                    {f.file}
                  </option>
                ))}
              </select>
            </label>
          )}
          {loadKeepers.error && <p className="error">{loadKeepers.error.message}</p>}
          <KeeperEditor
            rows={keepers}
            onChange={setKeepers}
            numTeams={teams}
            myPosition={position}
            // The league's roster, else the default Yahoo slots: ten starters and the bench.
            rounds={resolved?.rounds ?? 10 + bench}
            options={options}
            errorKey={erroredRow(keepers, create.error?.message)}
          />
        </>
      )}

      <details className="more" open={strategyOpen || needsTable} onToggle={(e) => setStrategyOpen(e.currentTarget.open)}>
        <summary>Strategy: {strategyLine}</summary>
        <div className="more-body">
          <div className="row">
            <label style={{ flexGrow: 1 }}>
              <span className="k">Objective</span>
              <select value={objective} onChange={(e) => setObjective(e.target.value as Objective)}>
                <option value="win">expected categories won (recommended)</option>
                <option value="sum">sum of z (the old planner, no punts)</option>
              </select>
            </label>
            {objective === "win" && (
              <label>
                <span className="k">
                  Spread ×
                  <Info title="spread multiplier" align="right">
                    <b>Multiplies each category's spread (σ) in the win curve.</b>
                    <span>1 = the league as simulated, no adjustment. Above 1 flattens the curve: a lead is trusted less and the plan moves toward plain sum of z. Below 1 steepens it: leads count as nearly won.</span>
                    <span>Sane range 0.75 to 2. In the study ×2 cost 0.2 matchups of 11 and ×0.5 cost 0.65.</span>
                  </Info>
                </span>
                <input type="number" min={0.25} max={5} step={0.25} value={sigmaScale} onChange={(e) => setSigmaScale(+e.target.value)} />
              </label>
            )}
          </div>
          {objective === "win" && (
            <label>
              <span className="k">
                League curve <span className="muted">(μ and σ per category)</span>
                <Info title="league curve">
                  <b>Per category: where the league's final totals land (μ) and how spread out they are (σ), in z.</b>
                  <span>A category counts for Φ((total − μ) / σ), the chance of beating a team drawn from the league. Expected categories won adds those up.</span>
                  <span>Sources: the built-in fit from 3000 simulated drafts; a refit from this session's own league simulation (choose "simulate this league" below); this league's own drafted rosters, each scored on its season's projections (the archive's picks.csv beside the league's survival table, with the standings in z units as a check); or a JSON file in data/. Spread × is applied on top.</span>
                </Info>
              </span>
              <select value={curve} onChange={(e) => setCurveFile(e.target.value)}>
                <option value="">
                  {league?.scoring === "points" ? "flat default for fantasy points" : "simulated league (3000 drafts, BBM 2026-09-21)"}
                  {survival === "simulate" ? ", refitted from the simulation below" : ""}
                </option>
                <option value={LEAGUE_ROSTERS}>
                  {resolved?.curve === "league" && resolved.curve_drafts != null
                    ? `the archive's drafted rosters (${blendLabel(resolved.curve_drafts)}, toward a simulated run; the league's default)`
                    : "this league's drafted rosters (archive, on these projections)"}
                </option>
                {(curveFiles.data ?? []).map((f) => (
                  <option key={f.file} value={f.file}>
                    {f.file}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            <span className="k">
              Survival odds
              <Info title="survival odds">
                <b>The chance a player is still on the board at each of your picks.</b>
                <span>The plan weights every future pick by them, so they decide who to take now and who can wait.</span>
                <span><b>ADP formula (instant):</b> a normal spread around each player's ADP. With no ADP file the ADP is a value rank, which puts specialists far later than real drafts do.</span>
                <span><b>Simulated drafts against this board:</b> runs full drafts with z-score, ADP and roster-model drafters (some punting) and counts how often each player survives to each pick. Catches specialists going early and position runs. About 1 s per draft per core. The curve's μ and σ are refitted from the same drafts.</span>
                <span><b>Saved table:</b> a CSV from an earlier simulation in data/.</span>
                <span><b>This league's drafts by ADP:</b> how often players at each keeper-adjusted ADP lasted to each pick in this league's past drafts (a CSV headed adp, picks…, undrafted), with the share never drafted at all. It answers from ADP {LEAGUE_FROM_ADP}; earlier players, whose survival is sharper than the table shows, and players past its last ADP use the ADP formula.</span>
                <span><b>Default:</b> this league's drafts when data/ holds {LEAGUE_SURVIVAL_DEFAULT}, else simulated drafts (and the session says why).</span>
                <span><b>Spread</b> {SPREAD.base} + {SPREAD.growth} × ADP, from the league's nine drafts: the ADP formula, the simulated drafters and the league table's fill-in all use it.</span>
                <span>With keepers, the ADP formula and the league's table count only the market: a player's ADP drops by the keepers ranked ahead of him, and keeper slots are not picks.</span>
              </Info>
            </span>
            <select
              value={resolved ? (survivalChoice ?? "") : survival}
              onChange={(e) => setSurvival(e.target.value ? (e.target.value as SurvivalMode) : null)}
            >
              {resolved && <option value="">the league's: {leagueSurvivalText(resolved)}</option>}
              <option value="none">ADP formula (instant)</option>
              <option value="simulate">simulated drafts against this board</option>
              {!resolved && !!leagueFiles.data?.length && <option value="league">this league's drafts by ADP (keeper-adjusted), normal model under ADP {LEAGUE_FROM_ADP}</option>}
              <option value="file" disabled={!survivalFiles.data?.length}>saved survival table in data/</option>
            </select>
          </label>
          {pickTable && (
            <label>
              <span className="k">League table</span>
              <select value={leagueTable} onChange={(e) => setLeagueFile(e.target.value)} className={needsTable ? "bad" : ""}>
                {!leagueTable && (
                  <option value="" disabled>
                    choose one of {leagueFiles.data?.length ?? 0} tables
                  </option>
                )}
                {(leagueFiles.data ?? []).map((f) => (
                  <option key={f.file} value={f.file}>
                    {f.file}
                  </option>
                ))}
              </select>
            </label>
          )}
          {survival === "simulate" && (
            <div className="row">
              <label>
                <span className="k">Drafts</span>
                <input type="number" min={10} max={5000} step={50} value={survivalSims} onChange={(e) => setSurvivalSims(+e.target.value)} />
              </label>
              <span className="muted" style={{ alignSelf: "end", paddingBottom: 6 }}>
                about {simMinutes < 1 ? `${Math.max(10, Math.round(simMinutes * 60))} s` : `${simMinutes.toFixed(0)} min`} on {workers} cores; the draft screen opens at once and the table lands in the background.
                {objective === "win" ? " The curve's μ and σ are refitted from the same run." : ""}
              </span>
            </div>
          )}
          {survival === "file" && (
            <label>
              <span className="k">Survival table</span>
              <select value={survivalFile || survivalFiles.data?.[0]?.file || ""} onChange={(e) => setSurvivalFile(e.target.value)}>
                {(survivalFiles.data ?? []).map((f) => (
                  <option key={f.file} value={f.file}>
                    {f.file}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="row">
            <label className="inline" style={{ alignSelf: "end" }}>
              <input type="checkbox" checked={solveAhead} onChange={(e) => setSolveAhead(e.target.checked)} /> solve ahead of the clock (re-plan after every pick)
            </label>
            <label title="seconds per plan solve; the incumbent is kept when the limit is hit">
              <span className="k">Time limit (s)</span>
              <input type="number" min={1} max={600} value={timeLimit} onChange={(e) => setTimeLimit(+e.target.value)} />
            </label>
          </div>

        </div>
      </details>

      <button className="primary" onClick={() => create.mutate()} disabled={create.isPending || !files.length || needsTable} title={needsTable ? "choose the league table first" : undefined}>
        {create.isPending ? "Loading projections…" : "Start draft"}
      </button>
      {create.error && <p className="error">{String(create.error.message)}</p>}
      {made && (
        <div className="banner">
          {made.curveNote && (
            <p>
              Draft {made.session.id} was made on the simulated curve: the league curve could not be fit ({made.curveNote}).
            </p>
          )}
          {made.attachError && (
            <p>
              Draft {made.session.id} was made, but room {roomId.trim()} did not attach: {made.attachError}
            </p>
          )}
          {made.attachError && (
            <p className="muted" style={{ marginTop: 6 }}>
              Open the draft and attach from the sync card (8), or start over with other settings.
            </p>
          )}
          <div className="row" style={{ justifyContent: "flex-start", marginTop: 8 }}>
            <button className="small" onClick={() => onCreated(made.session)}>
              {made.attachError ? "Open the draft anyway" : "Open the draft"}
            </button>
          </div>
        </div>
      )}
      {files.length === 0 && <p className="muted">Drop a Basketball Monster export into data/.</p>}
    </section>
  );
}
