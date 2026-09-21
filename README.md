# pickandroll

Fantasy basketball draft optimizer for 9-category head-to-head leagues.

The name is the algorithm. A **pick** is a mixed-integer program: choose the roster that maximizes
value under position, punt and league constraints. The **roll** is the rolling horizon: after every
pick in the live draft the board changes, so the plan is re-solved from the new state and only the
next pick is acted on.

## Pieces

| Piece | Where | Job |
| --- | --- | --- |
| Core | `src/pickandroll/{projections,draft,optim,availability}` | Pure computation. Projection schema, z-scores, MILP models, availability curves. No I/O. |
| Sources | `src/pickandroll/sources` | Basketball Monster projections (primary), Yahoo Fantasy league and live draft feed, CSV import. |
| App | `src/pickandroll/api` and `web/` | FastAPI backend with a live event stream, and the draft-day web UI. |

The core never imports from sources or api. Sources never import from api.

## Status

Working end to end on local data: projections load, the board and recommendations render, picks
(manual or from a Yahoo live draft) re-solve the roster in well under a second. See
`docs/DESIGN.md` for the model formulations and measured solve times.

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

Data pulls:

```bash
.venv/bin/python scripts/yahoo_auth.py       # one-time OAuth, lists your leagues
.venv/bin/python scripts/bbm_fetch.py --ros  # Basketball Monster exports into data/ (log in on first run)
```

Projection exports from paid services live in `data/` and are gitignored. Never commit them.
