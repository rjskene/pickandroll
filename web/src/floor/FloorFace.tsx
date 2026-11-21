// The floor as the in-season page's second face (#461): its own row under the app's bar (all
// leagues or one, the Live chip, the clock), the Demo's transport row while the Demo runs, the
// stage, the day's gates under it (#472), and the panel naming what runs now. Live plays the week from the run logs, the live
// progress files and each day's queue (#462), polled every few seconds while a run or a pass is in
// flight and once a minute at rest; the Demo plays the sample week on the bent clock. Nothing here
// writes anything but the execute time, through the control the landing already has.
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import type { QueuePayload, SeasonSummary, StatusPayload } from "../api";
import ExecuteTime from "../components/ExecuteTime";
import { reducedMotion } from "../explain/useClock";
import { AGENTS, bentClock, centralDate, timeline } from "./model";
import type { Agent, Timeline } from "./model";
import { useQueries, useQuery } from "@tanstack/react-query";
import { livePoll, weekQueueDays } from "./live";
import { api as client } from "../api";
import { PRIVATE, sampleRoster, sampleWeek } from "./sample";
import { formatHash, termHash } from "../explain/nav";
import { TRACKS } from "../explain/tracks/index.ts";
import FloorStage from "./FloorStage";
import GateStrip from "./GateStrip";
import { gatesOf } from "./gates";
import { FLOW_EXPLAIN, W, clockText, dayLabel, sceneAt, sceneWidth, weekOf } from "./scene";
import type { LeagueRow } from "./scene";

export interface FloorControl {
  demo: boolean;
  one: string | null;
  league: string;
}

/** What the landing's keys drive on the face (keys.ts, ``FloorKeys``). */
export interface FloorApi {
  toggleView: () => void;
  toggleDemo: () => void;
  playPause: () => void;
  day: (delta: number) => void;
}

/** The Demo's week, built once: the timeline, its bent clock, live and start moments. */
function useSample() {
  return useMemo(() => {
    const w = sampleWeek();
    const tl = timeline({ runs: w.runs, queues: w.queues, seasons: w.seasons, now: w.liveAt });
    return { w, tl, clock: bentClock(tl) };
  }, []);
}

/** The scene's width for the stage's content box (#470), kept as the box resizes. */
function useSceneWidth(): [RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [w, setW] = useState(W);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => setW(sceneWidth(e.contentRect.width, e.contentRect.height)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** The Demo's clock: wall seconds on requestAnimationFrame at a speed; still under reduced motion. */
function useWall(end: number, start: number, on: boolean) {
  const reduced = useMemo(reducedMotion, []);
  const [wall, setWall] = useState(start);
  const [playing, setPlaying] = useState(!reduced);
  const [speed, setSpeed] = useState(1);
  const at = useRef(start);
  const set = useCallback((v: number) => {
    at.current = Math.max(0, Math.min(end, v));
    setWall(at.current);
  }, [end]);
  useEffect(() => {
    if (!on || !playing || reduced) return;
    let raf = 0;
    let last = 0;
    const tick = (ms: number) => {
      if (last) {
        const v = at.current + ((ms - last) / 1000) * speed;
        set(v >= end ? 0 : v);
      }
      last = ms;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [on, playing, reduced, speed, end, set]);
  return { wall, set, playing: playing && !reduced, setPlaying, speed, setSpeed, reduced };
}

export default function FloorFace({
  seasons,
  queue,
  status,
  now,
  control,
  setControl,
  onOpenLeague,
  onMoves,
  onQueue,
  onHistory,
  onStatus,
  onExplainStep,
  api,
}: {
  seasons: SeasonSummary[];
  queue: QueuePayload | undefined;
  status: StatusPayload | undefined;
  now: number;
  control: FloorControl;
  setControl: (c: FloorControl) => void;
  onOpenLeague: (league: string) => void;
  onMoves: (league: string) => void;
  onQueue: () => void;
  onHistory: () => void;
  onStatus: () => void;
  onExplainStep: (hash: string) => void;
  /** Set to what the keys drive while the face is drawn. */
  api: RefObject<FloorApi | null>;
}) {
  const sample = useSample();
  const [stageRef, sceneW] = useSceneWidth();
  // Under reduced motion the Demo is a still frame: the live moment, Friday mid-claim.
  const still = useMemo(reducedMotion, []);
  const demoStart = sample.clock.toWall(still ? sample.w.liveAt : sample.w.demoAt);
  const clk = useWall(sample.clock.wallEnd, demoStart, control.demo);
  const [execOpen, setExecOpen] = useState(false);
  // Live: the day picked on the week strip for the gates (#472); none is today's.
  const [picked, setPicked] = useState<string | null>(null);
  // The frame time, for the chewing and the spin: the Demo's clock, else the second; none when still.
  const frame = still ? 0 : control.demo ? clk.wall : now / 1000;

  // Live: the week's run logs, the run in flight, and the queue of every day of the Central week to
  // today that the page's own queue (the NBA day, polled with these) does not cover.
  const today = centralDate(now);
  const live = useQuery({ queryKey: ["routine-live"], queryFn: client.routineLive, enabled: !control.demo, refetchInterval: (q) => livePoll(q.state.data, queue) });
  const runs = useQuery({ queryKey: ["routine-runs", today], queryFn: () => client.routineRuns(today, 7), enabled: !control.demo, refetchInterval: livePoll(live.data, queue) });
  const past = useQueries({
    // The Central today read here (23:00 to midnight, #468) keeps the floor's pace; earlier days once.
    queries: weekQueueDays(today, queue?.date ?? null).map((d) => ({
      queryKey: ["queue-day", d],
      queryFn: () => client.queue(d),
      enabled: !control.demo,
      staleTime: d === today ? 0 : 30 * 60_000,
      refetchInterval: d === today ? livePoll(live.data, queue) : false,
      retry: false,
    })),
    combine: (rs) => rs.map((r) => r.data),
  });
  const liveTl: Timeline = useMemo(
    () => timeline({ runs: runs.data, live: live.data, queues: [...past, queue], seasons, status, now }),
    [runs.data, live.data, past, queue, seasons, status, now],
  );
  const tl = control.demo ? sample.tl : liveTl;
  const t = control.demo ? sample.clock.toTime(clk.wall) : now;
  const age = control.demo ? (x: number) => clk.wall - sample.clock.toWall(x) : (x: number) => (now - x) / 1000;

  const leagues: LeagueRow[] = useMemo(() => {
    if (control.demo) {
      const week = weekOf(t);
      return sample.w.seasons.map((s) => ({
        league: s.league,
        mine: s.league === PRIVATE,
        adds: { used: sample.tl.entries.filter((e) => e.league === s.league && e.outcome === "claimed" && e.outcomeAt !== null && e.outcomeAt <= t && week.includes(e.date)).length, limit: 4 },
        budget: s.league === PRIVATE ? null : 80,
      }));
    }
    // /seasons can take a while to answer: until it does, the day's queue names the leagues, the
    // private league first as the landing pins it.
    if (!seasons.length) {
      // (the newest queue that names any: from 23:00 Central the page's is tomorrow's, still empty)
      const named = [queue, ...[...past].reverse()].find((q) => q?.leagues.length);
      const rows = (named?.leagues ?? []).map((l) => ({ league: l.league, mine: l.status === "private", adds: null, budget: l.budget ?? null }));
      return [...rows.filter((l) => l.mine), ...rows.filter((l) => !l.mine)];
    }
    return seasons.map((s) => ({ league: s.league, mine: !s.public, adds: s.adds ? { used: s.adds.used, limit: s.adds.limit } : null, budget: s.funds?.dollars ?? null }));
  }, [control.demo, sample, seasons, queue, past, t]);
  const names = leagues.map((l) => l.league);
  const one = control.one && names.includes(control.one) ? control.one : null;
  const dayQueue = control.demo ? sample.w.queues.find((q) => q.date === centralDate(t)) : queue;
  // One league's roster: the Demo's invented one, or the league's as read.
  const season = useQuery({ queryKey: ["season", one], queryFn: () => client.season(one ?? ""), enabled: !!one && !control.demo, staleTime: 60_000 });
  const roster = useMemo(
    () => (!one ? null : control.demo ? sampleRoster(one) : (season.data?.roster.map((r) => ({ slot: r.slot, name: r.player.name })) ?? null)),
    [one, control.demo, season.data],
  );
  // The gates' day: the picked one live (inside the week), else the moment's.
  const gateDay = !control.demo && picked && picked !== today && weekOf(t).includes(picked) ? picked : centralDate(t);
  const gates = useMemo(() => gatesOf(tl, gateDay, t), [tl, gateDay, t]);
  const scene = sceneAt({
    tl,
    t,
    age,
    now: frame,
    leagues,
    one,
    w: sceneW,
    executeTime: dayQueue?.settings.in_force ?? "--:--",
    roster,
    claims: control.demo,
    day: control.demo ? null : gateDay,
  });

  const startDemo = (date?: string) => {
    const at = date ? sample.w.runs.by_day.find((d) => d.date === date)?.runs[still ? "morning" : "signin"]?.started_at : null;
    clk.set(at ? sample.clock.toWall(Date.parse(at)) - 0.5 : demoStart);
    clk.setPlaying(true);
    setControl({ ...control, demo: true });
  };
  const toLive = () => {
    setPicked(null);
    setControl({ ...control, demo: false });
  };
  const pick = (league: string | null) => setControl({ ...control, one: league, league: league ?? control.league });
  const firstLeague = control.league && names.includes(control.league) ? control.league : (names[0] ?? null);
  const keysApi: FloorApi = {
    toggleView: () => pick(one ? null : firstLeague),
    toggleDemo: () => (control.demo ? toLive() : startDemo()),
    playPause: () => (control.demo ? clk.setPlaying(!clk.playing) : startDemo()),
    day: (delta) => {
      const week = weekOf(t);
      const k = week.indexOf(centralDate(t));
      startDemo(week[(k + delta + 7) % 7]);
    },
  };
  const latest = useRef(keysApi);
  useEffect(() => {
    latest.current = keysApi;
  });
  useEffect(() => {
    api.current = {
      toggleView: () => latest.current.toggleView(),
      toggleDemo: () => latest.current.toggleDemo(),
      playPause: () => latest.current.playPause(),
      day: (d) => latest.current.day(d),
    };
    return () => {
      api.current = null;
    };
  }, [api]);

  return (
    <div className="floor">
      <div className="floorbar">
        <span className="fl-clock">
          {clockText(t)}
          <small>CT</small>
        </span>
        <span className="seg" role="group" aria-label="Leagues on the floor">
          <button className={one ? "" : "on"} aria-pressed={!one} onClick={() => pick(null)}>
            All leagues
          </button>
          <button className={one ? "on" : ""} aria-pressed={!!one} onClick={() => pick(firstLeague)} title="one league: a filter on the floor, the docks become its card (v)">
            One league
          </button>
        </span>
        <select aria-label="The league on the floor" value={one ?? (names.includes(control.league) ? control.league : names[0] ?? "")} onChange={(e) => pick(e.target.value)}>
          {leagues.map((l) => (
            <option key={l.league} value={l.league}>
              {l.league}
              {l.mine ? " · suggestions only" : ""}
            </option>
          ))}
        </select>
        <span className="grow" />
        <button
          className={`livechip${control.demo ? " demo" : " on"}`}
          onClick={() => (control.demo ? toLive() : startDemo())}
          title={control.demo ? "Demo: a simulated week on sample data. Click to go back to live (d)" : "Live: today at rest from the queue. Click to run the Demo, a simulated week on sample data (d)"}
        >
          {control.demo ? "Demo" : (
            <>
              <i />
              Live
            </>
          )}
        </button>
      </div>
      {control.demo && (
        <div className="transport">
          <button className="small primary" onClick={() => clk.setPlaying(!clk.playing)} disabled={clk.reduced} title="Space">
            {clk.playing ? "Pause" : "Play"}
          </button>
          <span className="seg" role="group" aria-label="Speed">
            {[1, 3, 8].map((v) => (
              <button key={v} className={clk.speed === v ? "on" : ""} aria-pressed={clk.speed === v} onClick={() => clk.setSpeed(v)}>
                {v}×
              </button>
            ))}
          </span>
          <span className="fl-days">
            {weekOf(t).map((d) => (
              <button key={d} className={`small${d === centralDate(t) ? " on" : ""}`} onClick={() => startDemo(d)}>
                {dayLabel(d).slice(0, 3)}
              </button>
            ))}
          </span>
          <input type="range" min={0} max={1000} value={Math.round((clk.wall / sample.clock.wallEnd) * 1000)} onChange={(e) => clk.set((Number(e.target.value) / 1000) * sample.clock.wallEnd)} aria-label="The Demo's clock" />
          <span className="dim">demo · sample week · runs slowed, idle hours skipped · not your leagues' real moves</span>
        </div>
      )}
      {execOpen && (
        <div className="transport">
          <span className="k">Execute time</span>
          <ExecuteTime q={queue} />
          <span className="grow" />
          <button className="small" onClick={() => setExecOpen(false)}>
            Close
          </button>
        </div>
      )}
      <div className="fl-legend">
        {(["scout", "solver", "setter", "starter", "mover", "orchestrator"] as Agent[]).map((r) => (
          <button key={r} type="button" className="fl-term" onClick={() => onExplainStep(termHash(r))} title={`${AGENTS[r].label} in Explain's glossary`}>
            <i className={`sw c-${r}`} />
            {AGENTS[r].label}: {AGENTS[r].does}
          </button>
        ))}
        <span>
          <i className="sw ring" />a queued entry
        </span>
        <span>
          <i className="sw hold" />
          held by a rule
        </span>
        <span className="dim">a dock opens its league · the hub the Queue · the ledger History · a stage's number its step in Explain, its title or a name the glossary</span>
      </div>
      <div className="fl-stage" ref={stageRef}>
        <FloorStage
          s={scene}
          one={one}
          h={{
            // Live, a day picks the gates' day (#472); in the Demo it moves the bent clock there.
            onDay: (d) => (control.demo ? startDemo(d) : setPicked(d === today ? null : d)),
            onDock: onOpenLeague,
            onLamp: onMoves,
            onHub: onQueue,
            onGateClock: () => setExecOpen((o) => !o),
            onLedger: onHistory,
            onStation: onStatus,
            onStage: (k) => {
              const { track, step } = FLOW_EXPLAIN[k];
              const i = TRACKS.find((x) => x.id === track)?.steps.findIndex((x) => x.id === step) ?? 0;
              onExplainStep(formatHash({ track, step: Math.max(0, i) }, TRACKS));
            },
            onTerm: (id) => onExplainStep(termHash(id)),
            onAll: () => pick(null),
          }}
        />
      </div>
      <GateStrip day={gates} onToday={!control.demo && gateDay !== today ? () => setPicked(null) : null} />
      <div className="fl-now">
        <div className="what">
          <b className={scene.now.agent ? `c-${scene.now.agent}` : "muted"}>{scene.now.title}</b> <span className="muted">{scene.now.when}</span>
          <p>{scene.now.line}</p>
        </div>
        <div className="steps">
          {scene.now.steps.map((x, k) => (
            <span key={k} className={`chip ${x.state} c-${x.agent}`} title={x.detail}>
              <i />
              {x.name}
            </span>
          ))}
        </div>
        <div className="unit">
          <span className="k">In progress</span>
          {scene.now.unit ? (
            <>
              <div className="big">{scene.now.unit.big}</div>
              <div className="sub muted">{scene.now.unit.sub}</div>
              <div className="bar">
                <span className={scene.now.agent ? `c-${scene.now.agent}` : ""} style={{ width: `${(scene.now.unit.p * 100).toFixed(0)}%` }} />
              </div>
            </>
          ) : (
            <div className="sub muted">no action</div>
          )}
        </div>
      </div>
    </div>
  );
}
