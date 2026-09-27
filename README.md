# pickandroll

Fantasy basketball draft optimizer for 9-category head-to-head leagues.

The name is the algorithm. A **pick** is a mixed-integer program: choose the roster that maximizes
the expected number of categories won under position and league constraints. The **roll** is the
rolling horizon: after every pick in the live draft the board changes, so the plan is re-solved
from the new state, in the background and ahead of the clock, and only the next pick is acted on.
A punt is an outcome the board forces, never a goal the user picks.

## Pieces

| Piece | Where | Job |
| --- | --- | --- |
| Core | `src/pickandroll/{projections,draft,optim,availability}` | Pure computation. Projection schema, z-scores, MILP models, availability curves. No I/O. |
| Sources | `src/pickandroll/sources` | Basketball Monster projections (primary), Yahoo Fantasy league and live draft feed, CSV import. |
| App | `src/pickandroll/api` and `web/` | FastAPI backend with a live event stream, and the draft-day web UI. |

The core never imports from sources or api. Sources never import from api.

## Status

Working end to end on local data: projections load, a session can simulate its league before the
draft for survival odds and the category curve, the background solver plans and prices every
alternative after each pick (about 20 s per round on the curve objective, under a second on the
sum), and the dashboard shows per-category win odds, marginal value and the league tally. See
`docs/DESIGN.md` for the model formulations, `docs/analysis/` for the simulation studies behind
the objective, and `docs/ROADMAP.md` for what is built and what is next.

## Setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,api,yahoo,bbm]"
.venv/bin/playwright install chromium        # only for Basketball Monster downloads
cd web && npm install
```

Secrets go in `.env` at the repo root (gitignored):

```
YAHOO_CONSUMER_KEY=...
YAHOO_CONSUMER_SECRET=...
YAHOO_LEAGUE_ID=...
```

## Running

```bash
.venv/bin/uvicorn pickandroll.api:app --reload          # API on :8000
cd web && npm run dev                                   # UI on :5173, proxies /api to :8000
.venv/bin/pytest                                        # tests
```

Draft-day inputs in `data/` (gitignored): a Basketball Monster export, optionally
`positions.csv`, and `adp.csv` with columns `player,adp` (a FantasyPros export with `Player`
and `AVG` also loads). Without an ADP file the board falls back to Basketball Monster's value
rank, which the UI flags: it places specialists far later than real drafts do.

Data pulls:

```bash
.venv/bin/python scripts/yahoo_auth.py       # one-time OAuth, lists your leagues
.venv/bin/python scripts/bbm_fetch.py --ros  # Basketball Monster exports into data/ (log in on first run)
```

Projection exports from paid services live in `data/` and are gitignored. Never commit them.
