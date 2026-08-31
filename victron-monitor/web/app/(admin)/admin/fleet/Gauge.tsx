// A single circular gauge (self-sufficiency / self-consumption / DoD) —
// pure CSS conic-gradient, no chart library, no client state. Presentational
// only, same reasoning as `FlowDiagram.tsx`: every number is a prop.
import styles from './gauge.module.css';

export function Gauge({
  pct,
  color,
  label,
  desc,
}: {
  pct: number | null;
  color: string;
  label: string;
  desc: string;
}) {
  const clamped = pct === null ? 0 : Math.max(0, Math.min(100, pct));
  return (
    <div className={styles.row}>
      <div className={styles.ring} style={{ ['--pct' as string]: clamped, ['--color' as string]: color }}>
        <span>{pct === null ? '—' : `${pct}%`}</span>
      </div>
      <div className={styles.info}>
        <div className={styles.label}>{label}</div>
        <div className={styles.desc}>{desc}</div>
      </div>
    </div>
  );
}
