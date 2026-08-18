import type { ReactNode } from 'react';
import { Eyebrow } from '../Eyebrow/Eyebrow';
import styles from './SectionHead.module.css';

export type SectionHeadProps = {
  eyebrow: ReactNode;
  children: ReactNode;
  /** .section-head p — the short intro paragraph under the heading. */
  lede?: ReactNode;
  className?: string;
};

// Listed in components/ui/* by PLAN_PHASE14.md §1.7 but not built in Step 1
// (Step 1 only needed it once the marketing page existed to use it). Three
// of Step 2's sections (How it works, Modules, Pricing) open with the exact
// same eyebrow + h2 + lede shape (landing_template.html's .section-head), so
// this is one shared primitive rather than the same three rules copied into
// FlowSteps.module.css, ModuleGrid.module.css and Pricing.module.css.
export function SectionHead({ eyebrow, children, lede, className }: SectionHeadProps) {
  const classes = [styles.head, className].filter(Boolean).join(' ');
  return (
    <div className={classes}>
      <Eyebrow className={styles.eyebrow}>{eyebrow}</Eyebrow>
      <h2>{children}</h2>
      {lede !== undefined && <p>{lede}</p>}
    </div>
  );
}
