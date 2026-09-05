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
        </Panel>
      </div>
    </section>
  );
}
