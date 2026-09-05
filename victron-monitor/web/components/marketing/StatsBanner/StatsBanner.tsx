'use client';

import { useEffect, useState } from 'react';
import styles from './StatsBanner.module.css';

export type StatsBannerProps = {
  sitesMonitored: number;
  installedKwp: number;
  kwhTracked: number;
};

// Counts 0 -> target once on mount, easing out (fast start, settles near
// the end — Oscar's own description: "counting rapidly until the numbers
// settle"). Real final values come from `getMarketingStats()`
// (`app/(marketing)/page.tsx`, a Server Component) — this hook only
// animates the DISPLAY of an already-real number, it never invents one.
// Skips the animation entirely for `prefers-reduced-motion` (this page's
// only JS-driven animation — every other motion here is CSS, already
// covered by the global `@media (prefers-reduced-motion: reduce)` rule in
// base.css, which doesn't touch requestAnimationFrame loops).
function useCountUp(target: number, durationMs: number, delayMs: number): number {
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      // Deferred into a microtask rather than called directly here — a
      // synchronous setState at the top of an effect body is a
      // react-hooks/set-state-in-effect violation (same fix ShapeChart.tsx
      // uses for its own loading-state effect).
      let cancelled = false;
      Promise.resolve().then(() => {
        if (!cancelled) setValue(target);
      });
      return () => {
        cancelled = true;
      };
    }

    let raf = 0;
    let start: number | null = null;

    function tick(ts: number) {
      if (start === null) start = ts;
      const progress = Math.min((ts - start) / durationMs, 1);
      const eased = 1 - (1 - progress) ** 3;
      setValue(Math.round(target * eased));
      if (progress < 1) raf = requestAnimationFrame(tick);
    }

    const timeout = window.setTimeout(() => {
      raf = requestAnimationFrame(tick);
    }, delayMs);

    return () => {
      window.clearTimeout(timeout);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [target, durationMs, delayMs]);

  return value;
}

export function StatsBanner({ sitesMonitored, installedKwp, kwhTracked }: StatsBannerProps) {
  // Slightly staggered starts so the three numbers don't all land at
  // once — a small cascade reads as more alive than three synchronized
  // counters.
  const sites = useCountUp(sitesMonitored, 1200, 0);
  const kwp = useCountUp(Math.round(installedKwp), 1400, 150);
  const kwh = useCountUp(Math.round(kwhTracked), 1800, 300);

  return (
    <section className={styles.banner} aria-label="Platform totals">
      <div className={`wrap ${styles.row}`}>
        <div className={styles.item}>
          <div className={styles.num}>{sites.toLocaleString('en-US')}</div>
          <div className={styles.label}>Sites monitored</div>
        </div>
        <div className={styles.item}>
          <div className={styles.num}>
            {kwp.toLocaleString('en-US')}
            <span className={styles.unit}>kW</span>
          </div>
          <div className={styles.label}>Installed capacity</div>
        </div>
        <div className={styles.item}>
          <div className={styles.num}>
            {kwh.toLocaleString('en-US')}
            <span className={styles.unit}>kWh</span>
          </div>
          <div className={styles.label}>Tracked so far</div>
        </div>
      </div>
    </section>
  );
}
