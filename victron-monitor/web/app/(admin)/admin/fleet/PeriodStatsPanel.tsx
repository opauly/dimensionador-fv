'use client';

// This week / This month toggle for the per-site drill-down's stats panel.
// No fetch on toggle — unlike ShapeChart's Today/7-day/30-day (real VRM API
// calls, genuinely expensive to redo per click), both windows here are
// cheap SQL sums already computed server-side in
// `lib/server/db/admin.ts:getFleetOverview()` and handed down as props;
// switching is just picking which of the two to render.
import { useState } from 'react';
import type { BatteryStress, PeriodIndicators } from '@/lib/server/db/fleetOverviewCore';
import styles from './[site_id]/site.module.css';

type Period = 'week' | 'month';

// Same 3-tier-plus-"no data" wording `weekly_report.py` uses on the PDF
// (English side — admin is English-only by product decision).
function stressLabel(stress: BatteryStress): string {
  if (stress === 'high_stress') return 'High stress';
  if (stress === 'working_hard') return 'Working hard';
  if (stress === 'no_data') return 'No data';
  return 'Normal';
}

export function PeriodStatsPanel({ week, month }: { week: PeriodIndicators; month: PeriodIndicators }) {
  const [period, setPeriod] = useState<Period>('week');
  const d = period === 'week' ? week : month;

  return (
    <div className={styles.weekCard}>
      <div className={styles.weekCardHead}>
        <h2>{period === 'week' ? 'This week' : 'This month'}</h2>
        <div className={styles.periodToggle} role="tablist">
          <button
            type="button"
            className={period === 'week' ? styles.periodBtnActive : styles.periodBtn}
            onClick={() => setPeriod('week')}
          >
            Week
          </button>
          <button
            type="button"
            className={period === 'month' ? styles.periodBtnActive : styles.periodBtn}
            onClick={() => setPeriod('month')}
          >
            Month
          </button>
        </div>
      </div>
      <div className={styles.cardSub}>
        From the last {period === 'week' ? '7' : '30'} days of <code>vrm.energy_daily</code> — the same figures and
        formulas the PDF report already computes, not a second definition.
      </div>
      <div className={styles.weekStats}>
        <div className={styles.weekStat}>
          <span className={styles.weekStatLabel}>Battery cycles</span>
          <span className={styles.weekStatValue}>{d.batteryCycles ?? '—'}</span>
          <span className={`${styles.stressBadge} ${styles[`stress_${d.batteryStress}`]}`}>
            {stressLabel(d.batteryStress)}
          </span>
          {d.batteryCyclesEstimated && (
            <span className={styles.weekStatSub}>Estimated from SOC swing — no exact discharge data for this site</span>
          )}
        </div>
        <div className={styles.weekStat}>
          <span className={styles.weekStatLabel}>Grid outages</span>
          <span className={styles.weekStatValue}>
            {/* `d.daysWithData === 0` means no energy_daily rows exist in this
                window at all (e.g. a site that stopped syncing weeks ago) —
                "0" there would misreport "no outages" as fact when it's
                really "no data," the same distinction every other stat in
                this panel already makes. */}
            {d.daysWithData === 0 ? '—' : d.outageCount > 0 ? `${d.outageCount} (${d.outageMinutes} min)` : '0'}
          </span>
        </div>
        <div className={styles.weekStat}>
          <span className={styles.weekStatLabel}>SOC range</span>
          <span className={styles.weekStatValue}>
            {d.minSoc !== null && d.maxSoc !== null ? `${d.minSoc}–${d.maxSoc}%` : '—'}
          </span>
          {d.avgSoc !== null && <span className={styles.weekStatSub}>avg {d.avgSoc}%</span>}
        </div>
        <div className={styles.weekStat}>
          <span className={styles.weekStatLabel}>Days self-sufficient</span>
          <span className={styles.weekStatValue}>{d.daysWithData > 0 ? `${d.daysSelfSufficient} / ${d.daysWithData}` : '—'}</span>
        </div>
      </div>
    </div>
  );
}
