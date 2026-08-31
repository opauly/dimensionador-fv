// Energy flow diagram — Solar/Grid/Home/Battery nodes with animated dashed
// connectors, shared by the fleet-wide rollup (aggregate values) and the
// per-site drill-down (one site's values). Pure presentational: every
// number is a prop, no data fetching, no client state — the CSS animation
// (dashed lines "flowing") is plain `@keyframes`, so this stays a Server
// Component like the rest of `/admin/fleet`.
import styles from './flow-diagram.module.css';

function formatW(w: number | null): string {
  if (w === null) return '—';
  return Math.abs(w) >= 1000 ? `${(w / 1000).toFixed(1)}kW` : `${Math.round(w)}W`;
}

export function FlowDiagram({
  solarW,
  solarNote,
  loadW,
  loadLabel = 'Home',
  batteryW,
  batteryNote,
  gridW,
  hasGridMeter,
  gridNote,
}: {
  solarW: number | null;
  solarNote?: string;
  loadW: number | null;
  loadLabel?: string;
  batteryW: number | null;
  batteryNote?: string;
  gridW: number | null;
  hasGridMeter: boolean;
  gridNote?: string;
}) {
  const batteryCharging = batteryW !== null && batteryW >= 0;
  const batteryAmt = batteryW === null ? '—' : `${batteryCharging ? '+' : ''}${formatW(batteryW)}`;

  return (
    <div className={styles.flow}>
      <svg className={styles.lines} viewBox="0 0 400 420" preserveAspectRatio="none">
        <path className={`${styles.path} ${styles.solarHome}`} d="M 75 40 Q 180 55 195 120" />
        <path className={`${styles.path} ${styles.batteryHome}`} d="M 200 276 Q 200 256 200 236" />
        {hasGridMeter && <path className={`${styles.path} ${styles.gridHome}`} d="M 325 40 Q 220 55 205 120" />}
      </svg>

      <div className={`${styles.node} ${styles.solar}`}>
        <div className={styles.ring}>
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--signal)" strokeWidth={1.8}>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
          </svg>
        </div>
        <div className={styles.name}>Solar</div>
        <div className={styles.amt}>{formatW(solarW)}</div>
        {solarNote && <div className={styles.footnote}>{solarNote}</div>}
      </div>

      <div className={`${styles.node} ${styles.grid}`}>
        <div className={styles.ring}>
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--mute)" strokeWidth={1.8}>
            <path d="M6 21V10l6-6 6 6v11M9 21v-6h6v6" />
          </svg>
        </div>
        <div className={styles.name}>Grid</div>
        <div className={styles.amt} style={!hasGridMeter ? { color: 'var(--mute)' } : undefined}>
          {hasGridMeter ? formatW(gridW) : 'no meter'}
        </div>
        {gridNote && <div className={styles.footnote}>{gridNote}</div>}
      </div>

      <div className={`${styles.node} ${styles.home}`}>
        <div className={styles.ring}>
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--paper)" strokeWidth={1.6}>
            <path d="M3 11l9-7 9 7" />
            <path d="M5 10v10h14V10" />
          </svg>
        </div>
        <div className={styles.name}>{loadLabel}</div>
        <div className={styles.amt}>{formatW(loadW)}</div>
      </div>

      <div className={`${styles.node} ${styles.battery}`}>
        <div className={styles.ring}>
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--good)" strokeWidth={1.8}>
            <rect x="3" y="8" width="16" height="9" rx="1.5" />
            <path d="M19 11h2v3h-2M8 12v-1M11 12v-3M14 12v1" />
          </svg>
        </div>
        <div className={styles.name}>Battery{batteryNote ? `, ${batteryNote}` : ''}</div>
        <div className={styles.amt}>{batteryAmt}</div>
      </div>
    </div>
  );
}
