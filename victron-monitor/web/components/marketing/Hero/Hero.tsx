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
            The export nobody opens.
            <br />
            Now a report <em className={styles.em}>everyone</em> reads.
          </h1>
          <p className={`lede ${styles.lede}`}>
            Every Cerbo GX is already logging health score, grid independence, and battery behavior. We turn that
            CSV into a branded, AI-narrated report that actually gets opened — for your own system, or every
            customer on your fleet — automatically, every week.
          </p>
          <div className={styles.ctas}>
            {/* PLAN_PHASE16.md §8 Step 5.5 — replaces the old `#cta` anchor
                into the now-deleted `AccessForm`; the real self-serve
                signup flow lives at /signup instead (Oscar's explicit
                decision to retire the request-access form). */}
            <Button href="/signup" arrow>
              Get started
            </Button>
            <Button href="#preview" variant="ghost">
              See a sample report
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
