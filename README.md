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

Early scaffold. See `docs/DESIGN.md` for the plan and the model formulations.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,api]"
.venv/bin/pytest
```

Projection exports from paid services live in `data/` and are gitignored. Never commit them.
