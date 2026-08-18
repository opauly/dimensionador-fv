import type { HTMLAttributes, ReactNode } from 'react';
import styles from './Panel.module.css';

export type PanelVariant = 'card' | 'readout' | 'price';

export type PanelProps = {
  /** Which of the template's three surfaces this renders (.card / .readout / .price-card). */
  variant?: PanelVariant;
  /** .price-card.featured — only meaningful with variant="price". */
  featured?: boolean;
  /** The top-edge hairline gradient (.readout::after / .price-card.featured::after). */
  hairline?: boolean;
  /** .card:hover's background lift — only the module grid uses this, not every card. */
  interactive?: boolean;
  /** .card .led — the small green "alive" dot, top-right. */
  led?: boolean;
  /** .featured-tag pill, e.g. "Most installers". */
  featuredTag?: ReactNode;
  children: ReactNode;
  className?: string;
} & Omit<HTMLAttributes<HTMLDivElement>, 'className' | 'children'>;

export function Panel({
  variant = 'card',
  featured = false,
  hairline = false,
  interactive = false,
  led = false,
  featuredTag,
  children,
  className,
  ...rest
}: PanelProps) {
  const variantClass = variant === 'readout' ? styles.readout : variant === 'price' ? styles.price : styles.card;
  const classes = [
    variantClass,
    variant === 'card' && interactive && styles.interactive,
    variant === 'price' && featured && styles.featured,
    hairline && styles.hairline,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={classes} {...rest}>
      {variant === 'price' && featured && featuredTag && <span className={styles.featuredTag}>{featuredTag}</span>}
      {variant === 'card' && led && <span className={styles.led} aria-hidden="true" />}
      {children}
    </div>
  );
}
