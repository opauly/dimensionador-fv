import { Eyebrow, Panel } from '@/components/ui';
import styles from './LiveDashboard.module.css';

// One illustrative row of the sample fleet panel below — deliberately NOT
// a stat-grid-plus-quote (that's Hero's own Readout shape; Oscar's own
// feedback, 2026-09-04, was that the two panels read as the same thing
// with different numbers). A site list is what a live dashboard actually
// looks like day to day — this one's rows are the same three fields
// admin/fleet's real table shows: connection status, health score, live
// PV reading.
type SampleSite = {
  name: string;
  status: 'online' | 'flagged';
  health: number;
  pv: string;
};

const SAMPLE_SITES: SampleSite[] = [
  { name: 'Casa Rodríguez', status: 'online', health: 94, pv: '2.1kW' },
  { name: 'Finca El Roble', status: 'online', health: 88, pv: '1.4kW' },
  { name: 'Bodega Central', status: 'flagged', health: 76, pv: '0.6kW' },
];

// Illustrative "shape" chart below the site list — an averaged DAILY curve
// (hours of one representative day, 12a-9p), not seven separate weekday
// points. This mirrors the real ShapeChart.tsx's own "week" range exactly:
// that range averages each hour across the last 7 days into one typical
// daily shape, it does not plot 7 distinct days side by side (Oscar's own
// correction, 2026-09-05).
const HOUR_LABELS = ['12a', '3a', '6a', '9a', '12p', '3p', '6p', '9p'] as const;
const PV_POINTS: readonly (readonly [number, number])[] = [
  [10, 130], [67, 130], [124, 125], [181, 75], [239, 30], [296, 40], [353, 105], [410, 130],
];
const LOAD_POINTS: readonly (readonly [number, number])[] = [
  [10, 80], [67, 90], [124, 85], [181, 70], [239, 65], [296, 68], [353, 50], [410, 75],
];
const BATTERY_POINTS: readonly (readonly [number, number])[] = [
  [10, 105], [67, 110], [124, 108], [181, 120], [239, 125], [296, 123], [353, 95], [410, 90],
];
const GRID_POINTS: readonly (readonly [number, number])[] = [
  [10, 115], [67, 120], [124, 123], [181, 130], [239, 130], [296, 130], [353, 118], [410, 120],
];

// Same horizontal-tangent cubic Bezier technique ShapeChart.tsx's own
// buildPaths() uses (admin/fleet/ShapeChart.tsx) — a plain point-to-point
// polyline reads as sharp zigzags; this rounds it off without overshooting
// past the points, matching the real dashboard's own line style exactly
// (Oscar's request, 2026-09-05: "soften the curves like we do in the real
// dashboard").
function smoothPath(points: readonly (readonly [number, number])[]): string {
  let path = `M ${points[0][0]} ${points[0][1]}`;
  for (let i = 0; i < points.length - 1; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    const cpx = (x0 + x1) / 2;
    path += ` C ${cpx} ${y0}, ${cpx} ${y1}, ${x1} ${y1}`;
  }
  return path;
}

// The dashboard existed on this page only as a single bullet inside
// Pricing's Growth card — everything else was written when reports were
// the only product. This section (2026-09-04) gives it the same
// text-column + Panel-readout treatment ReportPreview gives the report,
// placed right before Pricing since that's where the Growth/Fleet-only
// gate actually matters.
//
// The 4 AI Insight names/descriptions below are copied verbatim from the
// real in-app copy (`app/(portal)/app/dashboard/page.tsx`'s rollup-card
// `desc` text, `lib/i18n/strings.ts`'s `dashboard_anomaly_*` keys) — this
// page and the product must never describe the same feature two different
// ways. The readout panel's numbers are illustrative, same honesty
// convention as Hero's own `Readout` ("SAMPLE SITE" label, not a real
// customer) — there's no real `/app/dashboard` screenshot to show, and a
// public marketing page is the wrong place for real-looking customer data
// even if synthetic.
export function LiveDashboard() {
  return (
    <section id="dashboard" className="band">
      <div className={`wrap ${styles.grid}`}>
        <div>
          <Eyebrow>Live Dashboard</Eyebrow>
          <h2>
            The report tells you last week.
            <br />
            This shows you right now.
          </h2>
          <p style={{ marginTop: 16 }}>
            Real-time solar, load, battery, and grid readings — refreshed every ~15 minutes. A health score
            that&apos;s always current, not just once a week. And AI Insights: four deterministic checks
            against each site&apos;s own history, not a model.
          </p>
          <ul className={styles.insightList}>
            <li>
              <b>Unexpected silence</b>
              <span>A real zero during hours this site has historically produced</span>
            </li>
            <li>
              <b>Quiet drift</b>
              <span>Trending down vs. this site&apos;s own recent baseline</span>
            </li>
            <li>
              <b>Underperformance</b>
              <span>Below what this site&apos;s installed size should deliver</span>
            </li>
            <li>
              <b>Incomplete charging</b>
              <span>Battery hasn&apos;t reached full charge in 5+ of the last 7 days</span>
            </li>
          </ul>
          <span className={styles.badge}>
            <span className={styles.badgeDot} aria-hidden="true" />
            Included with Growth and Fleet — <a href="#pricing">Starter stays report-only</a>
          </span>
        </div>

        <Panel
          variant="readout"
          hairline
          role="img"
          aria-label="Sample fleet dashboard listing three sites: Casa Rodríguez online at health score 94, Finca El Roble online at 88, and Bodega Central flagged for quiet drift at 76, each with a live solar reading"
        >
          <div className={styles.head}>
            <span className={styles.site}>
              SAMPLE FLEET <b>· LIVE VIEW</b>
            </span>
            <Eyebrow amber className={styles.liveEyebrow}>
              Live
            </Eyebrow>
          </div>
          <div className={styles.summaryRow}>
            <span>
              <b className={styles.summaryGood}>12/12</b> sites online
            </span>
            <span>
              avg health <b className={styles.summaryGood}>91/100</b>
            </span>
          </div>
          <ul className={styles.siteList}>
            {SAMPLE_SITES.map((site) => (
              <li key={site.name} className={styles.siteRow}>
                <span className={`${styles.dot} ${site.status === 'flagged' ? styles.dotFlag : styles.dotOnline}`} aria-hidden="true" />
                <span className={styles.siteName}>{site.name}</span>
                <span className={site.status === 'flagged' ? styles.healthFlag : styles.health}>{site.health}</span>
                <span className={styles.pv}>{site.pv} PV</span>
              </li>
            ))}
          </ul>
          <p className={styles.narr}>
            <b>Bodega Central</b> flagged for quiet drift — generating 18% below its own recent baseline.
          </p>

          {/* Illustrative daily shape — the same 4 series ShapeChart.tsx
             plots on the real dashboard (admin/fleet/ShapeChart.tsx and its
             customer-facing counterpart), drawn as static SVG here rather
             than the real interactive component: this panel is presented as
             one still image of what the dashboard looks like, not a live
             widget, same as ReportPreview's own real-but-static PDF
             screenshot just above this section. Numbers are illustrative —
             see this file's own header comment on why. */}
          <div className={styles.chartBlock}>
            <div className={styles.chartHead}>Daily shape · 7-day average</div>
            <svg
              viewBox="0 0 420 150"
              className={styles.chartSvg}
              role="img"
              aria-label="Illustrative chart of the sample fleet's typical daily shape, averaged over the last 7 days: solar rising to a midday peak, load relatively flat with an evening peak, battery covering mornings and evenings, and a small grid draw at the edges of the day"
            >
              <line x1="10" y1="130" x2="410" y2="130" className={styles.chartBaseline} />
              <path d={smoothPath(BATTERY_POINTS)} className={styles.chartLineBattery} />
              <path d={smoothPath(GRID_POINTS)} className={styles.chartLineGrid} />
              <path d={smoothPath(LOAD_POINTS)} className={styles.chartLineLoad} />
              <path d={smoothPath(PV_POINTS)} className={styles.chartLinePv} />
              {HOUR_LABELS.map((label, i) => (
                <text key={label} x={10 + i * (400 / 7)} y="144" className={styles.chartAxisLabel}>
                  {label}
                </text>
              ))}
            </svg>
            <div className={styles.chartLegend}>
              <span><span className={`${styles.legendDot} ${styles.legendPv}`} aria-hidden="true" />PV</span>
              <span><span className={`${styles.legendDot} ${styles.legendLoad}`} aria-hidden="true" />Load</span>
              <span><span className={`${styles.legendDot} ${styles.legendBattery}`} aria-hidden="true" />Battery</span>
              <span><span className={`${styles.legendDot} ${styles.legendGrid}`} aria-hidden="true" />Grid</span>
            </div>
          </div>
        </Panel>
      </div>
    </section>
  );
}
