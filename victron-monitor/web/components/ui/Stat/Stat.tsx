import type { ReactNode } from 'react';
import styles from './Stat.module.css';

export type StatProps = {
  label: string;
  value: ReactNode;
  /** e.g. "kWh", "%", "/100 · Good" — rendered smaller, after the value. */
  unit?: ReactNode;
  /** .stat.good — the health-score-style green treatment. */
  good?: boolean;
  className?: string;
};

export function Stat({ label, value, unit, good = false, className }: StatProps) {
  const classes = [styles.stat, good && styles.good, className].filter(Boolean).join(' ');
  return (
    <div className={classes}>
      <div className={styles.lbl}>{label}</div>
      <div className={styles.val}>
        {value}
        {unit !== undefined && <small className={styles.unit}>{unit}</small>}
      </div>
    </div>
  );
}
