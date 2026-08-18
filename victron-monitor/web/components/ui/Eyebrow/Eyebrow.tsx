import type { ReactNode } from 'react';
import styles from './Eyebrow.module.css';

export type EyebrowProps = {
  children: ReactNode;
  /** .eyebrow.amber — the pulsing "Live" indicator variant. Sparing use only, per the token comment in tokens.css. */
  amber?: boolean;
  className?: string;
};

export function Eyebrow({ children, amber = false, className }: EyebrowProps) {
  const classes = [styles.eyebrow, amber && styles.amber, className].filter(Boolean).join(' ');
  return (
    <span className={classes}>
      <span className={styles.dot} aria-hidden="true" />
      {children}
    </span>
  );
}
