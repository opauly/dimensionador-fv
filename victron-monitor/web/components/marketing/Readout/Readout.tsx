import { Eyebrow, Panel, Stat } from '@/components/ui';
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
      aria-label="Sample weekly report readout showing health score 84 out of 100, 429 kilowatt hours solar generated, and 96.1 percent grid independence"
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
    </Panel>
  );
}
