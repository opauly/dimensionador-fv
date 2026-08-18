import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from 'react';
import styles from './Button.module.css';

type Variant = 'primary' | 'ghost';

type SharedProps = {
  variant?: Variant;
  children: ReactNode;
  className?: string;
  /** Renders the template's slide-on-hover arrow glyph (".btn .arrow") after the label. */
  arrow?: boolean;
};

// Renders <a> when `href` is passed (nav CTAs, "See a sample report", the
// mailto access-form link) and <button> otherwise. The landing page's .btn
// class is applied to both tag types in the template — one component with
// two possible prop shapes avoids two near-duplicate components that would
// drift out of sync with each other's styling.
type LinkProps = SharedProps & { href: string } & Omit<
    AnchorHTMLAttributes<HTMLAnchorElement>,
    'href' | 'className' | 'children'
  >;

type ButtonElProps = SharedProps & { href?: undefined } & Omit<
    ButtonHTMLAttributes<HTMLButtonElement>,
    'className' | 'children'
  >;

export type ButtonProps = LinkProps | ButtonElProps;

// The four component-only props (variant/children/className/arrow — plus
// href, which both branches also declare) need stripping out before what's
// left gets spread onto the underlying <a>/<button> as native attributes.
// A named `delete` loop reads clearer here than a five-name destructure-and-
// discard per branch, and — unlike destructuring unused names — doesn't
// trip `no-unused-vars` on the names it's discarding.
const OWN_PROP_KEYS = ['variant', 'children', 'className', 'arrow', 'href'] as const;

function nativeProps<T extends Record<string, unknown>>(props: T): Omit<T, (typeof OWN_PROP_KEYS)[number]> {
  const rest: Record<string, unknown> = { ...props };
  for (const key of OWN_PROP_KEYS) delete rest[key];
  return rest as Omit<T, (typeof OWN_PROP_KEYS)[number]>;
}

export function Button(props: ButtonProps) {
  const { variant = 'primary', children, className, arrow } = props;
  const classes = [styles.btn, variant === 'ghost' && styles.ghost, className].filter(Boolean).join(' ');
  const content = (
    <>
      {children}
      {arrow && (
        <span className={styles.arrow} aria-hidden="true">
          →
        </span>
      )}
    </>
  );

  if (props.href !== undefined) {
    const anchorRest = nativeProps<LinkProps>(props);
    return (
      <a href={props.href} className={classes} {...anchorRest}>
        {content}
      </a>
    );
  }

  const buttonRest = nativeProps<ButtonElProps>(props);
  return (
    <button type={buttonRest.type ?? 'button'} className={classes} {...buttonRest}>
      {content}
    </button>
  );
}
