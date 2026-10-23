import type { CalibrationBucket, ProgressPayload } from "../api";
import { pct } from "../format";
import { bucketsOver, POOLED, rangeSum, recordLabel, scopeSentences, scopeWeeks } from "../progress";
import { ordinal } from "../season";
import ProgressChart from "./ProgressChart";
import { knobMarkers, NothingScored, ScopeHead, Sentences, Tile, viewRange, weekDates } from "./ProgressParts";

// The Odds view and the Odds card (#129): the odds the decision log held against the results,
// the matchup odds by their Brier score (0.25 a coin flip, lower better) and the category odds
// by bucket, each bucket's share won against the odds it said.

const COIN_FLIP = 0.25;
/** A bucket's gap under this many points reads as on its odds. */
const ON_ODDS = 0.05;

/** The category odds' buckets, the surest first: the odds said, the categories, the share won
 * and the gap. */
export function BucketTable({ buckets }: { buckets: CalibrationBucket[] }) {
  const rows = [...buckets].reverse();
  if (!rows.some((b) => b.count > 0)) return <p className="dim small">No category odds scored yet.</p>;
  return (
    <table className="season-table pg-buckets">
      <thead>
        <tr>
          <th title="the odds of winning a category, as the decision log held them before the week">Odds said</th>
          <th className="num" title="the categories in the bucket">
            Cats
          </th>
          <th className="num" title="the share of them won, a tie as half">
            Hit
          </th>
          <th className="num" title="the share won less the mean odds said, in points">
            Δ
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((b) => {
          const gap = b.won != null && b.odds != null ? b.won - b.odds : null;
          return (
            <tr key={b.from} title={b.odds != null ? `mean odds ${pct(b.odds)}` : undefined}>
              <td>
                {Math.round(b.from * 100)} – {Math.round(b.to * 100)}%
              </td>
              <td className="num">{b.count}</td>
              <td className="num">{b.won == null ? "" : pct(b.won)}</td>
              <td className={`num ${gap == null || Math.abs(gap) < ON_ODDS ? "dim" : gap > 0 ? "good" : "bad"}`}>{gap == null ? "" : `${gap >= 0 ? "+" : "−"}${Math.abs(Math.round(gap * 100))}`}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

const brierTitle = "the matchup odds' Brier score: the mean squared gap between the odds of winning and the result, a tie half a win; 0.25 is a coin flip, lower is better";

export function OddsView({
  p,
  scope,
  onScope,
  range,
  setRange,
  onChange,
}: {
  p: ProgressPayload;
  scope: string;
  onScope: (scope: string) => void;
  range: [number, number] | null;
  setRange: (r: [number, number] | null) => void;
  onChange: (id: string) => void;
}) {
  const { bounds, from, to, step } = viewRange(p, scope, range, setRange);
  const weeks = bounds ? scopeWeeks(p, scope, from, to) : [];
  const sum = rangeSum(weeks);
  const buckets = bucketsOver(p.pooled.weeks, from, to);
  const cats = buckets.reduce((a, b) => a + b.count, 0);
  const hit = cats ? buckets.reduce((a, b) => a + (b.won ?? 0) * b.count, 0) / cats : null;
  const said = cats ? buckets.reduce((a, b) => a + (b.odds ?? 0) * b.count, 0) / cats : null;
  const say = scopeSentences(p.sentences, scope).filter((s) => s.topic === "odds");
  const over = from === to ? `wk ${from}` : `wks ${from}–${to}`;
  return (
    <div className="season-view progress-view">
      <ScopeHead p={p} title="Odds against results" scope={scope} onScope={onScope} bounds={bounds} from={from} to={to} setRange={setRange} onStep={step} />
      {!bounds ? (
        <NothingScored scope={scope} />
      ) : (
        <>
          <div className="pg-tiles">
            <Tile k="brier" v={sum.brier == null ? "—" : sum.brier.toFixed(2)} title={brierTitle}>
              over {over} · {sum.projected} matchup{sum.projected === 1 ? "" : "s"} · last week {sum.brierLast == null ? "—" : sum.brierLast.toFixed(2)}
            </Tile>
            <Tile k="matchups" v={recordLabel(sum.record)} title="matchups won, lost and tied against the odds of winning them summed">
              {sum.expected.toFixed(1)} expected over {sum.projected} with odds
            </Tile>
            <Tile k="categories" v={hit == null ? "—" : pct(hit)} title="the categories won, a tie as half, against the mean odds said, the public leagues pooled">
              {said == null ? "no category odds scored" : `won of ${cats} · the odds said ${pct(said)} · public, pooled`}
            </Tile>
          </div>
          {say.length > 0 && <Sentences say={say} />}
          <ProgressChart
            weeks={weeks.map((w) => w.week)}
            series={[{ key: "brier", label: "Brier", tone: "actual", values: weeks.map((w) => w.brier) }]}
            markers={knobMarkers(p, from, to, onChange)}
            markerKey="knob change · click for its sheet"
            reference={{ value: COIN_FLIP, label: "coin flip" }}
            fmt={(v) => v.toFixed(2)}
            label={`The matchup odds' Brier score by week, weeks ${from} to ${to}; lower is better`}
            tip={(i) => {
              const w = weeks[i];
              return (
                <>
                  <div className="muted">
                    week {w.week} · {weekDates(w)}
                  </div>
                  <div className="v">{w.brier == null ? "no odds" : `Brier ${w.brier.toFixed(2)}`}</div>
                  <div>
                    {recordLabel(w.record)} · {w.expected.toFixed(1)} expected
                  </div>
                  {scope === POOLED &&
                    w.lines.map((l) => (
                      <div key={l.league} className="dim">
                        {l.league} · {l.outcome ?? "—"}
                        {l.expected != null ? ` at ${pct(l.expected)}` : ""}
                        {l.rank != null ? ` · ${ordinal(l.rank)}` : ""}
                      </div>
                    ))}
                </>
              );
            }}
          />
          <div className="pg-odds">
            <div className="row">
              <span className="k">Category odds by bucket · wks {from}–{to}</span>
              {scope !== POOLED && <span className="dim small">the public leagues pooled: a league alone holds too few categories to read</span>}
            </div>
            <BucketTable buckets={buckets} />
          </div>
        </>
      )}
    </div>
  );
}

/** The Odds card: the season's calibration, the public leagues pooled. */
export function OddsCard({ p }: { p: ProgressPayload }) {
  const c = p.pooled.calibration;
  const say = scopeSentences(p.sentences, POOLED).filter((s) => s.topic === "odds");
  return (
    <div className="pg-league">
      <div className="pg-tiles">
        <Tile k="brier" v={c.brier == null ? "—" : c.brier.toFixed(2)} title={brierTitle}>
          {c.brier == null ? "no odds scored" : `season · ${c.weeks} matchup${c.weeks === 1 ? "" : "s"} · 0.25 is a coin flip, lower is better`}
        </Tile>
      </div>
      <BucketTable buckets={c.buckets} />
      {say.length > 0 ? <Sentences say={say} /> : c.buckets.some((b) => b.count > 0) && <p className="dim small">Nothing to say beyond the numbers: each bucket within its noise of its odds.</p>}
    </div>
  );
}
