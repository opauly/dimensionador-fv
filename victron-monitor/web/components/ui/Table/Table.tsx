import type { ReactNode, TableHTMLAttributes } from 'react';
import styles from './Table.module.css';

// Not extracted from `landing_template.html` — the marketing page never
// renders a data table, so there's nothing there for this to be a
// near-verbatim move of (unlike Button/Panel/Stat/Field, which are moves of
// existing rules per PLAN_PHASE14.md §1.7). This is a new primitive, built
// from the same tokens (`--panel`, `--line`, `--mute`, `--font-mono`
// eyebrow-style headers) so a dashboard table reads as the same instrument
// panel the marketing components already establish — first real table this
// app needs is `app/(portal)/app/sites`'s site list (§2 Step 4).

export type TableProps = { children: ReactNode; className?: string } & Omit<
  TableHTMLAttributes<HTMLTableElement>,
  'className' | 'children'
>;

export function Table({ children, className, ...rest }: TableProps) {
  const classes = [styles.wrap, className].filter(Boolean).join(' ');
  return (
    <div className={classes}>
      <table className={styles.table} {...rest}>
        {children}
      </table>
    </div>
  );
}
