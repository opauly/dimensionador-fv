import { Eyebrow, Gauge, Panel, Stat } from '@/components/ui';
import styles from './Readout.module.css';

// The hero's "instrument readout" module — landing_template.html's
// .readout, with real (synthetic) sample numbers standing in for a live
// site. Listed as its own component in PLAN_PHASE14.md §1.7 rather than
// folded into Hero, since it is exactly the shape the customer dashboard's
// KPI readout reuses later (Steps 4/6) — a real usage of the "extract
// components/ui/* from the marketing markup first" ordering that §1.7
// argues for.
export function Readout() {
  return (
    <Panel
      variant="readout"
      hairline
      role="img"
      aria-label="Sample weekly report readout showing health score 84 out of 100, 429 kilowatt hours solar generated, 96.1 percent grid independence, and live gauges for self-sufficiency, self-consumption, and depth of discharge"
    >
      <div className={styles.head}>
        <span className={styles.site}>
          SAMPLE SITE <b>· 7-DAY REPORT</b>
        </span>
        <Eyebrow amber className={styles.liveEyebrow}>
          Live
        </Eyebrow>
      </div>
      <div className={styles.stats}>
        <Stat label="Health score" value={84} unit="/100 · Good" good />
        <Stat label="Solar generated" value={429} unit="kWh" />
        <Stat label="Grid independence" value={96.1} unit="%" />
        <Stat label="Alarm episodes" value={3} unit="events" />
      </div>
      <p className={styles.narr}>
        &quot;The system produced <b>96.1% of what the home used</b> this week, with the battery covering every
        evening peak. Grid draw stayed under 17 kWh total…&quot;
      </p>

      {/* Added 2026-09-05 (Oscar's request, seeing the real per-site
         dashboard's own gauge card) — the readout was all report numbers;
         this row is what the LIVE half of the new "Your system, live"
         headline actually looks like. Same colors the real page uses:
         self-sufficiency/good, self-consumption/victron-glow, depth of
         discharge/signal (admin/fleet/[site_id]/page.tsx's own Gauge
         color choices). */}
      <div className={styles.gaugeRow}>
        <Gauge pct={96.3} color="var(--good)" label="Self-sufficiency" compact />
        <Gauge pct={91} color="var(--victron-glow)" label="Self-consumption" compact />
        <Gauge pct={42} color="var(--signal)" label="Depth of discharge" compact />
      </div>
    </Panel>
  );
}
