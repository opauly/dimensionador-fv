'use client';

import { useState } from 'react';
import styles from './ModeToggle.module.css';

export type ModeToggleOption = { value: string; label: string };

export type ModeToggleProps = {
  options: ModeToggleOption[];
  /** Controlled value. Omit to let ModeToggle own its own state (defaultValue / options[0]). */
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  'aria-label': string;
  className?: string;
};

// A useState client component replaces the template's three separate
// data-mode + [data-toggle-target] + querySelectorAll('.mode-toggle')
// wireups (report-section modules, pricing, installer/owner) — and with
// them, the script-ordering bug landing_template.html documents at L887-896
// (a <script> earlier in document order only sees elements already parsed;
// the pricing toggle went inert because it lived after the block that once
// queried for '.mode-toggle'). There is no "document order" for a React
// component instance to be sensitive to, so that bug class doesn't have
// anywhere to reappear — not "fixed", structurally absent.
export function ModeToggle({ options, value, defaultValue, onChange, className, ...rest }: ModeToggleProps) {
  const [uncontrolled, setUncontrolled] = useState(defaultValue ?? options[0]?.value);
  const active = value ?? uncontrolled;

  function select(next: string) {
    if (value === undefined) setUncontrolled(next);
    onChange?.(next);
  }

  const classes = [styles.toggle, className].filter(Boolean).join(' ');

  return (
    <div className={classes} role="group" {...rest}>
      {options.map((option) => {
        const isActive = option.value === active;
        const buttonClasses = [styles.button, isActive && styles.active].filter(Boolean).join(' ');
        return (
          <button
            key={option.value}
            type="button"
            className={buttonClasses}
            aria-pressed={isActive}
            onClick={() => select(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
