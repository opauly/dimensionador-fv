import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';
import styles from './Field.module.css';

export type FieldProps = {
  label: ReactNode;
  htmlFor?: string;
  /** .field label .req — the amber asterisk. */
  required?: boolean;
  /** .field label .opt — "(optional)" by default. `landing_template.html`'s
   * forms (AccessForm, the login screen) are English-only by design (§1.10),
   * so that default is correct there without a `t()` call. A bilingual
   * caller (`app/(portal)/app/**`, PLAN_PHASE14.md §2 Step 4) MUST override
   * this with a translated string via `optionalLabel` instead of relying on
   * the default — passing `optional` alone on a Spanish-rendered page would
   * be exactly the "literal that bypassed lib/i18n/strings.ts" Step 4's own
   * validation checks for. */
  optional?: boolean;
  optionalLabel?: ReactNode;
  children: ReactNode;
  className?: string;
};

export function Field({
  label,
  htmlFor,
  required = false,
  optional = false,
  optionalLabel = ' (optional)',
  children,
  className,
}: FieldProps) {
  const classes = [styles.field, className].filter(Boolean).join(' ');
  return (
    <div className={classes}>
      <label htmlFor={htmlFor} className={styles.label}>
        {label}
        {required && (
          <span className={styles.req} aria-hidden="true">
            *
          </span>
        )}
        {optional && <span className={styles.opt}>{optionalLabel}</span>}
      </label>
      {children}
    </div>
  );
}

function joinControlClassName(className: string | undefined) {
  return [styles.control, className].filter(Boolean).join(' ');
}

// Thin wrappers so form call sites (Step 2's AccessForm, Step 4/6/7's
// dashboard forms) get the ported ".field input/select/textarea" styling —
// including the focus ring — without repeating the className plumbing.
export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props;
  return <input className={joinControlClassName(className)} {...rest} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  const { className, ...rest } = props;
  return <select className={joinControlClassName(className)} {...rest} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { className, ...rest } = props;
  return <textarea className={joinControlClassName(className)} {...rest} />;
}
