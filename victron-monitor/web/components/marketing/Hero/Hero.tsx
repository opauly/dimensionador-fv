import { Button, Eyebrow } from '@/components/ui';
import { Readout } from '../Readout/Readout';
import styles from './Hero.module.css';

export function Hero() {
  return (
    <header className={styles.hero}>
      <div className={`wrap ${styles.grid}`}>
        <div>
          <Eyebrow className={styles.eyebrow}>Built on Victron VRM data</Eyebrow>
          <h1 className={styles.h1}>
            Your system, <em className={styles.em}>live</em>.
            <br />
            Your story, <em className={styles.em}>weekly</em>.
          </h1>
          <p className={`lede ${styles.lede}`}>
            Every Cerbo GX is already logging health score, grid independence, and battery behavior. Watch it live
            on a dashboard that updates every ~15 minutes, and get the full story in a branded, AI-narrated report —
            for your own system, or every customer on your fleet — automatically, every week.
          </p>
          <div className={styles.ctas}>
            {/* PLAN_PHASE16.md §8 Step 5.5 — replaces the old `#cta` anchor
                into the now-deleted `AccessForm`; the real self-serve
                signup flow lives at /signup instead (Oscar's explicit
                decision to retire the request-access form).
                Both CTAs point at /signup now (2026-09-08, Oscar's
                decision) — the sample report is still reachable without
                committing via Nav's own "Sample report" link (/#preview),
                so this isn't removing that path, just no longer giving it
                its own hero-level button. Second button's label changed to
                match its real destination (Pricing's own "every plan
                starts with a 7-day free trial" line) rather than promising
                a sample and delivering a signup form. */}
            <Button href="/signup" arrow>
              Get started
            </Button>
            <Button href="/signup" variant="ghost">
              Start free trial
            </Button>
          </div>
          <span className={styles.note}>
            No Node-RED changes. No Cerbo reflash. Works with equipment you&apos;ve already installed.
          </span>
        </div>

        <Readout />
      </div>
    </header>
  );
}
