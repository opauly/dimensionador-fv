// A single circular gauge (self-sufficiency / self-consumption / depth of
// discharge) — pure CSS conic-gradient, no chart library, no client state.
// Same technique as the real per-site dashboard's own gauge
// (app/(admin)/admin/fleet/Gauge.tsx and its customer-facing counterpart),
// ported into components/ui/* (2026-09-05) so the marketing page's Hero
// readout can show the same visual language real subscribers see, not an
// invented one.
import styles from './Gauge.module.css';

export type GaugeProps = {
  pct: number | null;
  color: string;
  label: string;
  /** Omitted entirely in `compact` mode — there isn't room for a
   * description line at that size. */
  desc?: string;
  /** Small ring + label only, stacked vertically instead of the full
   * row-with-description layout — for tight spaces (Hero's own readout)
   * where three gauges need to fit beside an already-full stat grid. */
  compact?: boolean;
};

export function Gauge({ pct, color, label, desc, compact = false }: GaugeProps) {
  const clamped = pct === null ? 0 : Math.max(0, Math.min(100, pct));
  const classes = [styles.row, compact && styles.compact].filter(Boolean).join(' ');
  return (
    <div className={classes}>
      <div className={styles.ring} style={{ ['--pct' as string]: clamped, ['--color' as string]: color }}>
        <span>{pct === null ? '—' : `${pct}%`}</span>
      </div>
      <div className={styles.info}>
        <div className={styles.label}>{label}</div>
        {desc && <div className={styles.desc}>{desc}</div>}
      </div>
    </div>
  );
}
