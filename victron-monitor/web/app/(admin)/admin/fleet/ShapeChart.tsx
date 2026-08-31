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
const ZERO_Y = 170;
// Fixed scale (not auto-fit to the fetched data's own max) so switching
// range/series doesn't rescale the y-axis under the reader on every click —
// 1450 W covers this fleet's real observed peaks (fleet load ~1.4kW) with
// headroom; a much larger fleet would want this configurable rather than
// hardcoded.
const PX_PER_W = 170 / 1450;

function xFor(i: number) {
  return Math.round(i * (W / 23));
}
function yFor(v: number) {
  return Math.round(ZERO_Y - v * PX_PER_W);
}
function pointsFor(arr: (number | null)[]): string | null {
  const pts: string[] = [];
  for (let i = 0; i < arr.length; i++) {
    const v = arr[i];
    if (v === null) continue;
    pts.push(`${xFor(i)},${yFor(v)}`);
  }
  return pts.length >= 2 ? pts.join(' ') : null;
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

// One tagged union instead of separate loading/error/data booleans+state —
// avoids ever needing to set "loading" synchronously at the top of the
// effect (a react-hooks/set-state-in-effect violation): the previous
// range's chart just stays on screen, unchanged, until the new range's
// fetch actually resolves, which reads better anyway (no flash back to a
// loading spinner on every toggle click).
type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: ShapeData; gridAvailableCount: number };

export function ShapeChart({ siteIds, title, cardSub }: { siteIds: string[]; title: string; cardSub: string }) {
  const [range, setRange] = useState<Range>('today');
  const [checked, setChecked] = useState<Record<SeriesKey, boolean>>({ solar: true, load: true, grid: false, battery: false });
  const [state, setState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;

    Promise.all(
      siteIds.map((siteId) =>
        fetch(`/api/admin/pipeline/vrm-fleet/site-shape?siteId=${encodeURIComponent(siteId)}&range=${range}`)
          .then((r) => (r.ok ? (r.json() as Promise<ShapeData>) : Promise.reject(new Error('fetch failed'))))
      )
    )
      .then((results) => {
        if (cancelled) return;
        setState({
          status: 'ready',
          data: {
            solar: sumSeries(results.map((r) => r.solar)),
            load: sumSeries(results.map((r) => r.load)),
            battery: sumSeries(results.map((r) => r.battery)),
            grid: sumSeries(results.map((r) => r.grid)),
          },
          gridAvailableCount: results.filter((r) => r.grid.some((v) => v !== null)).length,
        });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ status: 'error' });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- siteIds is a prop that doesn't change identity per-render in practice (caller passes a stable array)
  }, [range]);

  const gridAvailableCount = state.status === 'ready' ? state.gridAvailableCount : null;
  const gridDisabled = gridAvailableCount === 0;
  const gridLabel = gridAvailableCount === null
    ? 'Grid'
    : `Grid ${siteIds.length > 1 ? `(${gridAvailableCount} of ${siteIds.length} metered)` : gridAvailableCount === 0 ? '(no meter)' : ''}`;

  const paths = useMemo(() => {
    if (state.status !== 'ready') return [];
    return SERIES.filter((s) => checked[s.key] && !(s.key === 'grid' && gridDisabled)).map((s) => ({
      ...s,
      points: pointsFor(state.data[s.key]),
    }));
  }, [state, checked, gridDisabled]);

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
        {state.status === 'loading' && <div className={styles.status}>Loading real VRM data…</div>}
        {state.status === 'error' && <div className={styles.status}>Could not load this chart right now.</div>}
        {state.status === 'ready' && (
          <svg viewBox={`0 0 ${W} 240`} preserveAspectRatio="none">
            <line x1="0" y1={ZERO_Y} x2={W} y2={ZERO_Y} stroke="var(--line)" strokeWidth={1.2} />
            {[6, 12, 18].map((h) => (
              <line key={h} x1={xFor(h)} y1={0} x2={xFor(h)} y2={240} stroke="var(--line)" strokeWidth={1} strokeDasharray="2 4" />
            ))}
            {paths.map(
              (p) =>
                p.points && (
                  <g key={p.key}>
                    {p.fill && <polygon points={`${p.points} ${xFor(23)},${ZERO_Y} ${xFor(0)},${ZERO_Y}`} fill={p.fill} stroke="none" />}
                    <polyline points={p.points} fill="none" stroke={p.color} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
                  </g>
                )
            )}
          </svg>
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
