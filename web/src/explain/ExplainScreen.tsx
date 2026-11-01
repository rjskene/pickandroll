// The Explain screen (#282, #283): a walkthrough of the draft, the moves and the day, one step
// a screen. One bar on top holds the app's lead, the track control, "Read it all", the glossary,
// the keys and the ← / → arrows; the step rail beside the card doubles as the diagram of the
// whole (a chip row on a phone). The popouts (a step's worked example, a bullet's formula), and
// the place kept in the URL hash (#draft/3).
import { useCallback, useEffect, useRef, useState } from "react";
import { EXPLAIN_SHEET, explainKeys } from "../keys";
import { useHotkeys } from "../useKeys";
import AppBarLead from "../components/AppBarLead";
import KeySheet from "../components/KeySheet";
import { LeaguesIcon } from "../components/icons";
import { useLandingOrder } from "../components/landingOrder";
import { OverviewStatus } from "../components/StatusLight";
import { useNow } from "../components/YahooSync";
import { GlossaryProvider, GlossarySheet } from "./Glossary";
import { formatHash, move, nextLabel, parseHash } from "./nav";
import type { Place } from "./nav";
import { FORMULAS } from "./formulas";
import { PopProvider } from "./PopContext";
import type { Pop } from "./PopContext";
import { Drawer, ExampleBody, FormulaBody } from "./Popout";
import StepCard from "./StepCard";
import Rail from "./Rail";
import { TRACKS, trackById } from "./tracks/index.ts";

interface Props {
  onBack: () => void;
  onProgress: () => void;
}

export default function ExplainScreen({ onBack, onProgress }: Props) {
  const landing = useLandingOrder();
  const leagues = [...landing.rows.pinned, ...landing.rows.rest];
  const now = useNow(30_000);
  const [place, setPlace] = useState<Place>(() => parseHash(location.hash, TRACKS));
  const [all, setAll] = useState(false);
  const [gloss, setGloss] = useState<{ open: boolean; term: string | null }>({ open: false, term: null });
  const [sheetOpen, setSheetOpen] = useState(false);
  const [pop, setPop] = useState<Pop | null>(null);
  // The last popout opened, so its sheet keeps its content while it slides out.
  const [shownPop, setShownPop] = useState<Pop | null>(null);
  const body = useRef<HTMLDivElement>(null);
  const track = trackById(place.track) ?? TRACKS[0];
  const step = track.steps[Math.min(place.step, track.steps.length - 1)];

  // The place lives in the hash, so a reload lands on the same step and the browser's back
  // button walks the steps.
  useEffect(() => {
    if (location.hash !== formatHash(place)) history.replaceState(null, "", formatHash(place));
  }, [place]);
  useEffect(() => {
    const on = () => {
      setPop(null);
      setPlace(parseHash(location.hash, TRACKS));
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  // A move to another step closes a popout: it belongs to the step it was opened on. Scrolling in
  // Read it all moves the rail, not this, so a popout stays open while the page scrolls.
  const go = useCallback(
    (p: Place) => {
      setPop(null);
      setPlace(p);
      const t = trackById(p.track);
      const s = t?.steps[p.step];
      if (all && s) document.getElementById(`ex-${p.track}-${s.id}`)?.scrollIntoView({ block: "start" });
      else body.current?.scrollTo({ top: 0 });
    },
    [all],
  );
  const prev = useCallback(() => go(move(place, -1, TRACKS)), [go, place]);
  const next = useCallback(() => go(move(place, 1, TRACKS)), [go, place]);
  const label = nextLabel(place, TRACKS);
  const done = label === "Done";
  const onNext = done ? onBack : next;
  const first = place.track === TRACKS[0].id && place.step === 0;

  // Read it all: the rail follows the card under the top of the page.
  useEffect(() => {
    if (!all || !body.current || typeof IntersectionObserver === "undefined") return;
    const cards = [...body.current.querySelectorAll<HTMLElement>(".ex-step")];
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          const i = cards.indexOf(e.target as HTMLElement);
          if (i >= 0) setPlace((p) => (p.step === i ? p : { ...p, step: i }));
        }
      },
      { root: body.current, rootMargin: "0px 0px -60% 0px", threshold: 0 },
    );
    cards.forEach((c) => io.observe(c));
    return () => io.disconnect();
  }, [all, track]);

  // One sheet at a time: a popout closes the glossary, the glossary closes a popout.
  const openTerm = useCallback((id: string) => {
    setPop(null);
    setGloss({ open: true, term: id });
  }, []);
  const closeGlossary = useCallback(() => setGloss((g) => ({ ...g, open: false })), []);
  const toggleGlossary = useCallback(() => {
    setPop(null);
    setGloss((g) => ({ ...g, open: !g.open }));
  }, []);
  const openPop = useCallback((p: Pop) => {
    setGloss((g) => ({ ...g, open: false }));
    setPop(p);
    setShownPop(p);
  }, []);
  const closePop = useCallback(() => setPop(null), []);
  // e: the current step's example, or closed when it is the one open.
  const toggleExample = useCallback(() => {
    if (!step?.example) return;
    const mine = pop?.kind === "example" && pop.track === track.id && pop.step === step.id;
    if (mine) setPop(null);
    else openPop({ kind: "example", track: track.id, step: step.id });
  }, [openPop, pop, step, track.id]);
  const toggleAll = useCallback(() => setAll((a) => !a), []);
  useHotkeys(
    explainKeys({ prev, next, back: onBack, glossaryOpen: gloss.open, closeGlossary, toggleGlossary, popOpen: pop !== null, closePop, toggleExample, toggleAll, sheetOpen, setSheetOpen }),
  );
  const popStep = shownPop?.kind === "example" ? trackById(shownPop.track)?.steps.find((s) => s.id === shownPop.step) : undefined;
  const popFormula = shownPop?.kind === "formula" ? FORMULAS[shownPop.id] : undefined;
  const popView = shownPop ? (shownPop.kind === "formula" ? `formula:${shownPop.id}` : `example:${shownPop.track}:${shownPop.step}`) : "";

  const shown = all ? track.steps : step ? [step] : [];
  return (
    <main className="shell">
      <header className="topbar season-top ex-bar">
        <AppBarLead onHome={onBack} status={<OverviewStatus leagues={leagues} now={now} />} onProgress={onProgress} explainHere />
        <span className="seg ex-tracks" role="group" aria-label="Track">
          {TRACKS.map((t) => (
            <button key={t.id} className={t.id === track.id ? "on" : ""} aria-pressed={t.id === track.id} onClick={() => go({ track: t.id, step: 0 })} title={t.title}>
              <span className="ex-long">{t.title}</span>
              <span className="ex-short">{t.short}</span>
            </button>
          ))}
        </span>
        <span className="grow" />
        <span className="ex-break" aria-hidden />
        <label className={`switch ex-all${all ? " on" : ""}`} title="Every step of the track on one page (a)">
          <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> <span className="ex-long">Read it all</span>
          <span className="ex-short">All</span> <kbd>a</kbd>
        </label>
        <button className="ex-gloss" onClick={toggleGlossary} title="The glossary (g)">
          Glossary <kbd>g</kbd>
        </button>
        <button className="ex-keys" onClick={() => setSheetOpen(true)} title="Keyboard shortcuts (?)">
          Keys <kbd>?</kbd>
        </button>
        <span className="ex-nav" role="group" aria-label="Steps">
          <button onClick={prev} disabled={first} aria-label="The step before" title="The step before (←)">
            ←
          </button>
          <span className="ex-count" aria-live="polite">
            {place.step + 1} of {track.labels.length}
          </span>
          <button className="primary" onClick={onNext} aria-label={done ? "Done: back to all leagues" : label.replace(/ →$/, "")} title={done ? "Done: back to all leagues" : `${label.replace(/ →$/, "")} (→)`}>
            {done ? "Done" : "→"}
          </button>
        </span>
        <button className="icon ex-home" onClick={onBack} aria-label="All leagues" title="All leagues (Esc)">
          <LeaguesIcon />
        </button>
      </header>
      <GlossaryProvider onOpen={openTerm}>
        <PopProvider onOpen={openPop}>
          <div className="ex-body">
            <Rail track={track} step={place.step} onGo={(i) => go({ track: track.id, step: i })} />
            <div className="ex-scroll" ref={body}>
              <div className={`ex-stage${all ? " all" : ""}`}>
                {shown.map((s, k) => (
                  <StepCard key={s.id} track={track} step={s} index={all ? k : place.step} />
                ))}
              </div>
            </div>
          </div>
          <Drawer open={pop !== null} view={popView} label={popFormula ? "Formula" : "Example"} title={popFormula ? "FORMULA" : "EXAMPLE"} sub={popFormula ? popFormula.name : popStep?.title} onClose={closePop}>
            {popFormula ? <FormulaBody formula={popFormula} /> : popStep?.example && <ExampleBody example={popStep.example} />}
          </Drawer>
        </PopProvider>
      </GlossaryProvider>
      <GlossarySheet open={gloss.open} term={gloss.term} onClose={closeGlossary} />
      <KeySheet sheet={EXPLAIN_SHEET} open={sheetOpen} onClose={() => setSheetOpen(false)} />
    </main>
  );
}
