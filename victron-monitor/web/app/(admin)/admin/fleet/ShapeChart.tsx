'use client';

// The interactive Today/7-day-avg/30-day-avg chart with per-series
// checkboxes, shared by the fleet-wide rollup (`page.tsx`, summed across
// every `siteIds` entry) and the per-site drill-down (`[site_id]/page.tsx`,
// one entry). Built from the mockup validated with Oscar directly (Fleet
// Dashboard Phase 2.5) — same range/checkbox interaction, now backed by
// `GET /api/admin/pipeline/vrm-fleet/site-shape`'s real on-demand VRM data
// instead of baked-in illustrative numbers.
//
// One component for both call sites rather than two near-duplicates: the
// only real difference between "one site's shape" and "the fleet's shape"
// is how many site_ids get summed, which this component already has to do
// generically (a single-element array sums to itself).
import { useEffect, useMemo, useState } from 'react';
import styles from './shape-chart.module.css';

type Range = 'today' | 'week' | 'month';
type SeriesKey = 'solar' | 'load' | 'grid' | 'battery';

type ShapeData = {
  solar: (number | null)[];
  load: (number | null)[];
  battery: (number | null)[];
  grid: (number | null)[];
};

const RANGES: { key: Range; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: '7-day avg' },
  { key: 'month', label: '30-day avg' },
];

const SERIES: { key: SeriesKey; label: string; color: string; fill?: string }[] = [
  { key: 'solar', label: 'Solar', color: 'var(--signal)', fill: 'rgba(var(--signal-rgb), 0.16)' },
  { key: 'load', label: 'Load', color: 'var(--paper-dim)' },
  { key: 'grid', label: 'Grid', color: 'var(--victron-glow)' },
  { key: 'battery', label: 'Battery', color: 'var(--good)', fill: 'rgba(var(--good-rgb), 0.14)' },
];

const W = 960;
const H = 240;
const ZERO_Y = 170;
const HEADROOM_ABOVE = ZERO_Y; // px available for positive values
const HEADROOM_BELOW = H - ZERO_Y; // px available for negative values (battery discharge, grid export)

function xFor(i: number) {
  return Math.round(i * (W / 23));
}

/** Scale is computed fresh per fetch from the ACTUAL data (with headroom),
 * not a hardcoded constant — a hardcoded scale clipped real fleet load
 * (found live: fleet load regularly exceeds the number this was first
 * shipped with). Positive and negative values get independent scales so a
 * small battery dip doesn't waste most of the chart's height, and solar's
 * real peak doesn't get clipped by a scale sized for battery instead.
 *
 * Takes only the CURRENTLY VISIBLE series' arrays, not every fetched
 * series — computing it from the full fetch regardless of which
 * checkboxes are on left the axis (and half the chart's height) reserved
 * for Battery/Grid's negative range even with both unchecked, the actual
 * default state. Toggling a series does reflow the scale as a result; kept
 * that way on purpose, matching "show me what's actually on screen" over
 * a perfectly stable axis nothing is using. */
function computeScale(visible: (number | null)[][]): { pxPerWPos: number; pxPerWNeg: number; topW: number; bottomW: number; hasNegative: boolean } {
  let maxPos = 0;
  let maxNeg = 0;
  for (const arr of visible) {
    for (const v of arr) {
      if (v === null) continue;
      if (v > maxPos) maxPos = v;
      if (-v > maxNeg) maxNeg = -v;
    }
  }
  // 20% headroom so a peak never touches the very top/bottom edge; a flat
  // all-zero series still gets a sane, non-infinite scale. `topW`/`bottomW`
  // are the actual W value sitting at the chart's top/bottom edge under
  // that headroom — what the y-axis labels below are built from, so the
  // axis always matches the scale exactly instead of being a second,
  // separately-guessed set of numbers.
  const topW = Math.max(maxPos * 1.2, 1);
  const bottomW = Math.max(maxNeg * 1.2, 1);
  const pxPerWPos = HEADROOM_ABOVE / topW;
  const pxPerWNeg = HEADROOM_BELOW / bottomW;
  return { pxPerWPos, pxPerWNeg, topW, bottomW, hasNegative: maxNeg > 0 };
}

function formatW(w: number): string {
  return Math.abs(w) >= 1000 ? `${(w / 1000).toFixed(1)}kW` : `${Math.round(w)}W`;
}

function yFor(v: number, scale: { pxPerWPos: number; pxPerWNeg: number }) {
  return v >= 0 ? ZERO_Y - v * scale.pxPerWPos : ZERO_Y - v * scale.pxPerWNeg;
}

/** Splits into contiguous non-null runs (a gap in the data breaks the line
 * rather than lying about a value in between), then draws each run as a
 * softened curve — a plain point-to-point polyline turns real, noisy
 * hourly data into sharp zigzags; horizontal-tangent cubic Beziers between
 * each pair of points round that off without overshooting past the real
 * values, matching the smoother look the mockup's hand-picked illustrative
 * numbers happened to have for free. */
function buildPaths(arr: (number | null)[], scale: { pxPerWPos: number; pxPerWNeg: number }, withFill: boolean): { linePath: string; fillPath: string } {
  const runs: [number, number][][] = [];
  let current: [number, number][] = [];
  for (let i = 0; i < arr.length; i++) {
    const v = arr[i];
    if (v === null) {
      if (current.length >= 2) runs.push(current);
      current = [];
      continue;
    }
    current.push([xFor(i), yFor(v, scale)]);
  }
  if (current.length >= 2) runs.push(current);

  let linePath = '';
  let fillPath = '';
  for (const run of runs) {
    let seg = `M ${run[0][0]} ${run[0][1]}`;
    for (let i = 0; i < run.length - 1; i++) {
      const [x0, y0] = run[i];
      const [x1, y1] = run[i + 1];
      const cpx = (x0 + x1) / 2;
      seg += ` C ${cpx} ${y0}, ${cpx} ${y1}, ${x1} ${y1}`;
    }
    linePath += seg + ' ';
    if (withFill) {
      const [lastX] = run[run.length - 1];
      const [firstX] = run[0];
      fillPath += `${seg} L ${lastX} ${ZERO_Y} L ${firstX} ${ZERO_Y} Z `;
    }
  }
  return { linePath: linePath.trim(), fillPath: fillPath.trim() };
}

function sumSeries(all: (number | null)[][]): (number | null)[] {
  const out: (number | null)[] = [];
  for (let h = 0; h < 24; h++) {
    let sum = 0;
    let any = false;
    for (const arr of all) {
      const v = arr[h];
      if (v !== null) {
        sum += v;
        any = true;
      }
    }
    out.push(any ? Math.round(sum * 10) / 10 : null);
  }
  return out;
}

type Ready = { data: ShapeData; gridAvailableCount: number };

export function ShapeChart({ siteIds, title, cardSub }: { siteIds: string[]; title: string; cardSub: string }) {
  const [range, setRange] = useState<Range>('today');
  const [checked, setChecked] = useState<Record<SeriesKey, boolean>>({ solar: true, load: true, grid: false, battery: false });
  // `ready` is the last successfully loaded data — kept on screen across a
  // range switch instead of being cleared, so a slow refetch (real VRM
  // calls over a 7/30-day window, summed across every site) doesn't blank
  // the chart. `status` tracks the in-flight fetch separately, so there's
  // still visible feedback that a click registered — the earlier version's
  // "just leave the old chart up" design had NO indicator at all during a
  // refetch, which is indistinguishable from Today/7-day/30-day simply not
  // working when a fetch takes more than an instant.
  const [ready, setReady] = useState<Ready | null>(null);
  const [status, setStatus] = useState<'loading' | 'idle' | 'error'>('loading');

  useEffect(() => {
    let cancelled = false;

    // Deferred into a microtask rather than called directly at the top of
    // the effect body — calling setState synchronously there is a
    // react-hooks/set-state-in-effect violation; wrapping it in a `.then()`
    // continuation is the same "callback fires when something changes"
    // shape the rule expects, just fired as soon as possible instead of on
    // network completion.
    Promise.resolve().then(() => {
      if (!cancelled) setStatus('loading');
    });

    Promise.all(
      siteIds.map((siteId) =>
        fetch(`/api/admin/pipeline/vrm-fleet/site-shape?siteId=${encodeURIComponent(siteId)}&range=${range}`)
          .then((r) => (r.ok ? (r.json() as Promise<ShapeData>) : Promise.reject(new Error('fetch failed'))))
      )
    )
      .then((results) => {
        if (cancelled) return;
        setReady({
          data: {
            solar: sumSeries(results.map((r) => r.solar)),
            load: sumSeries(results.map((r) => r.load)),
            battery: sumSeries(results.map((r) => r.battery)),
            grid: sumSeries(results.map((r) => r.grid)),
          },
          gridAvailableCount: results.filter((r) => r.grid.some((v) => v !== null)).length,
        });
        setStatus('idle');
      })
      .catch(() => {
        if (cancelled) return;
        setStatus('error');
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- siteIds is a prop that doesn't change identity per-render in practice (caller passes a stable array)
  }, [range]);

  const gridAvailableCount = ready?.gridAvailableCount ?? null;
  const gridDisabled = gridAvailableCount === 0;
  const gridLabel = gridAvailableCount === null
    ? 'Grid'
    : `Grid ${siteIds.length > 1 ? `(${gridAvailableCount} of ${siteIds.length} metered)` : gridAvailableCount === 0 ? '(no meter)' : ''}`;

  const visibleSeries = useMemo(
    () => (ready ? SERIES.filter((s) => checked[s.key] && !(s.key === 'grid' && gridDisabled)) : []),
    [ready, checked, gridDisabled]
  );

  const scale = useMemo(
    () => (ready ? computeScale(visibleSeries.map((s) => ready.data[s.key])) : null),
    [ready, visibleSeries]
  );

  const paths = useMemo(() => {
    if (!ready || !scale) return [];
    return visibleSeries.map((s) => ({
      ...s,
      ...buildPaths(ready.data[s.key], scale, Boolean(s.fill)),
    }));
  }, [ready, scale, visibleSeries]);

  return (
    <div className={styles.card}>
      <h2>{title}</h2>
      <div className={styles.cardSub}>{cardSub}</div>

      <div className={styles.controls}>
        <div className={styles.rangeToggle} role="tablist">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              className={r.key === range ? styles.rangeBtnActive : styles.rangeBtn}
              onClick={() => setRange(r.key)}
            >
              {r.label}
            </button>
          ))}
        </div>
        <div className={styles.seriesChecks}>
          {SERIES.map((s) => {
            const isGrid = s.key === 'grid';
            const disabled = isGrid && gridDisabled;
            return (
              <label key={s.key} className={disabled ? styles.checkDisabled : undefined}>
                <input
                  type="checkbox"
                  checked={checked[s.key]}
                  disabled={disabled}
                  onChange={(e) => setChecked((prev) => ({ ...prev, [s.key]: e.target.checked }))}
                />
                <i style={{ background: s.color }} />
                {isGrid ? gridLabel : s.label}
              </label>
            );
          })}
        </div>
      </div>

      <div className={styles.chartWrap}>
        {status === 'loading' && !ready && <div className={styles.status}>Loading real VRM data…</div>}
        {status === 'error' && !ready && <div className={styles.status}>Could not load this chart right now.</div>}
        {ready && scale && (
          <>
            {status === 'loading' && <div className={styles.updating}>Updating…</div>}
            {status === 'error' && <div className={styles.updating}>Couldn&apos;t refresh — showing the last loaded data.</div>}
            <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
              <line x1="0" y1={ZERO_Y} x2={W} y2={ZERO_Y} stroke="var(--line)" strokeWidth={1.2} />
              {[6, 12, 18].map((h) => (
                <line key={h} x1={xFor(h)} y1={0} x2={xFor(h)} y2={H} stroke="var(--line)" strokeWidth={1} strokeDasharray="2 4" />
              ))}
              {/* Y-axis gridlines behind the data, matching the scale
                  exactly since both come from the same computeScale() call
                  — never a separately-guessed set of numbers that could
                  drift out of sync with where the lines actually are. */}
              <line x1="0" y1={4} x2={W} y2={4} stroke="var(--line)" strokeWidth={1} strokeDasharray="2 4" opacity={0.5} />
              {scale.hasNegative && (
                <line x1="0" y1={H - 4} x2={W} y2={H - 4} stroke="var(--line)" strokeWidth={1} strokeDasharray="2 4" opacity={0.5} />
              )}
              {paths.map(
                (p) =>
                  p.linePath && (
                    <g key={p.key}>
                      {p.fillPath && <path d={p.fillPath} fill={p.fill} stroke="none" />}
                      <path d={p.linePath} fill="none" stroke={p.color} strokeWidth={2.5} strokeLinecap="round" />
                    </g>
                  )
              )}
              {/* Labels drawn last (on top of the data) so a line passing
                  near the left edge never covers the axis text. */}
              <text x={6} y={13} fontSize={11} fill="var(--paper-dim)" fontFamily="var(--font-mono)" style={{ paintOrder: 'stroke' }} stroke="var(--panel)" strokeWidth={3}>
                {formatW(scale.topW)}
              </text>
              <text x={6} y={ZERO_Y - 5} fontSize={11} fill="var(--paper-dim)" fontFamily="var(--font-mono)" style={{ paintOrder: 'stroke' }} stroke="var(--panel)" strokeWidth={3}>
                0
              </text>
              {scale.hasNegative && (
                <text x={6} y={H - 8} fontSize={11} fill="var(--paper-dim)" fontFamily="var(--font-mono)" style={{ paintOrder: 'stroke' }} stroke="var(--panel)" strokeWidth={3}>
                  -{formatW(scale.bottomW)}
                </text>
              )}
            </svg>
          </>
        )}
      </div>
      <div className={styles.axis}>
        <span>00:00</span>
        <span>06:00</span>
        <span>12:00</span>
        <span>18:00</span>
        <span>23:00</span>
      </div>
    </div>
  );
}
