// The glossary (#283): one line per term, opened from any `dfn` in the walkthrough and listed
// in full at the end of the screen. Ids are what the bullets' `[id]` markup names.
import type { Term } from "./types";

export const GLOSSARY: Term[] = [
  { id: "projection-set", term: "Projection set", def: "One source's table, a player per row: games, minutes, counting totals, makes and attempts; totals over the horizon." },
  { id: "pool", term: "Draft pool", def: "The players z-scores are taken against: the top teams × roster size by total, chosen iteratively." },
  { id: "z-score", term: "Z-score", def: "A category total in pool spreads above the pool mean; turnovers negated; percentages as impact." },
  { id: "adp", term: "ADP", def: "Average draft position, from Yahoo's player list or a file; the centre of the availability formula, shifted by the league's bias." },
  { id: "survival", term: "Survival", def: "The chance a player is still on the board at pick k, read from now; the formula, a simulated table, or the league's own record." },
  { id: "curve", term: "Curve", def: "Per category, the mean and spread of team totals across the league; simulated by default, fitted from rosters when there is an archive." },
  { id: "ecw", term: "Expected categories won", def: "The sum over categories of the odds of winning each; the draft objective on season totals, the in-season measure on weekly totals." },
  { id: "marginal", term: "Marginal value", def: "Categories won per extra z-point in a category: the slope of Φ at the roster's lead; prices deviations to first order." },
  { id: "horizon-plan", term: "Rolling-horizon plan", def: "One player per remaining pick, each weighted by the chance he lasts to that pick; only the first pick is acted on." },
  { id: "price", term: "Price", def: "Objective lost when a candidate is forced to be the next pick: the cost of taking him now, waiting risk included." },
  { id: "tie", term: "Tie", def: "Candidates within 0.05 categories of the best; shown as a group in ADP order." },
  { id: "keeper", term: "Keeper", def: "A pick decided before the draft (team position, round, player), appended when its slot comes." },
  { id: "keeper-adp", term: "Keeper-adjusted ADP", def: "A player's ADP moved up by the keepers ranked ahead of him; the space the league drafts in and the table is read in." },
  { id: "mirror", term: "Mirror", def: "The room's picks land in the session and the room is the truth; nothing is drafted for the user." },
  { id: "armed", term: "Armed", def: "The user's own arming of the seat; on the turn the tab clicks the recommended row after a fresh solve." },
  { id: "act-at", term: "Act-at", def: "Seconds left on the clock at which an armed turn clicks, 12 to 30, unless the user picks first." },
  { id: "blend", term: "Blend", def: "Per-game rates mixed from the projection source's and Yahoo's lines at the knob file's weight." },
  { id: "season-first", term: "Season first", def: "Never drop a great player for one week: both horizons' gains shown, the season horizon beside." },
  { id: "protected", term: "Protected", def: "Net positive, not beaten by the best add by the floor, and back this season: never a drop." },
  { id: "floor", term: "Protection floor", def: "How far the best add must beat a player before he is droppable; a knob the hill-climb may tune." },
  { id: "guard", term: "Season guard", def: "A recommended set's rest-of-season value sums to zero or more; what it held back is shown." },
  { id: "faab", term: "FAAB", def: "Free agent acquisition budget: a sealed bid on a waiver player, the highest wins, the budget lasts the season." },
  { id: "priority", term: "Priority claim", def: "A waiver decided by order, not money; odds (1 − q)^(p − 1) with an assumed rival rate, outside the objective." },
  { id: "queue", term: "Queue", def: "The day's entries per armed league, built from the decision log, each with its bid, its reason and the time it becomes due." },
  { id: "execute-time", term: "Execute time", def: "The day's earliest execution, 07:00 Central by default; an entry is due at the later of it and an hour after it was queued." },
  { id: "veto-window", term: "Veto window", def: "The hour after an entry is queued, and the time to the execute time: not due, and the user may strike it; a lineup needs none." },
  { id: "clear-date", term: "Clear date", def: "The day a waiver player becomes available; the claim is decided at Yahoo's early run that day and the daily reads won or lost." },
  { id: "strike", term: "Strike", def: "The user's veto on an entry or its bid alone, until it executes; a struck bid is a $0 claim." },
  { id: "dry-run", term: "Dry run", def: "The executor logs what it would click, with the page it saw, and clicks nothing." },
  { id: "live-guard", term: "Live guard", def: "Enough dry-run days in the log (lineups: seven, two fully checked), no stop file, the user's click; read again on every live run." },
];

export const termById = (id: string): Term | undefined => GLOSSARY.find((t) => t.id === id);
