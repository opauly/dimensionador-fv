import { Eyebrow, Panel, Stat } from '@/components/ui';
import styles from './LiveDashboard.module.css';

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
          aria-label="Sample live dashboard readout showing 12 of 12 sites online, average health score 91 out of 100, 88 percent self-sufficiency, and 1 active AI Insight"
        >
          <div className={styles.head}>
            <span className={styles.site}>
              SAMPLE FLEET <b>· LIVE VIEW</b>
            </span>
            <Eyebrow amber className={styles.liveEyebrow}>
              Live
            </Eyebrow>
          </div>
          <div className={styles.stats}>
            <Stat label="Sites online" value={12} unit="/12" good />
            <Stat label="Avg health score" value={91} unit="/100" good />
            <Stat label="Self-sufficiency" value={88} unit="%" />
            <Stat label="Active AI Insights" value={1} unit="flag" />
          </div>
          <p className={styles.narr}>
            &quot;1 site flagged for <b>quiet drift</b> — generating 18% below its own recent baseline.
            Everything else is within its normal range.&quot;
          </p>
        </Panel>
      </div>
    </section>
  );
}
