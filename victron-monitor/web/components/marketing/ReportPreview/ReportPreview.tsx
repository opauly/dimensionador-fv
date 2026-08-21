import Image from 'next/image';
import { Button, Eyebrow } from '@/components/ui';
import styles from './ReportPreview.module.css';

// public/sample_report.png is 1819x2573 (landing-page/assets/sample_report.png,
// copied not moved — see PLAN_PHASE14.md §6.2).
const SHOT_WIDTH = 1819;
const SHOT_HEIGHT = 2573;

export function ReportPreview() {
  return (
    <section id="preview" className="band">
      <div className={`wrap ${styles.grid}`}>
        <div>
          <Eyebrow>Sample report</Eyebrow>
          <h2>What lands in the inbox.</h2>
          <p style={{ marginTop: 16 }}>
            Not a mockup — this is page one of an actual report, rendered by the same pipeline that generates every
            customer&apos;s PDF: real health scoring, a real AI narrative, real savings math against live tariff
            tables. Only the household is invented.
          </p>
          <ul className={styles.miniList}>
            <li>
              Format <b>PDF, 2 pages</b>
            </li>
            <li>
              Cadence <b>Weekly or Monthly Overview</b>
            </li>
            <li>
              Languages <b>ES / EN</b>
            </li>
            <li>
              Delivery <b>Automatic, branded</b>
            </li>
          </ul>
          <span className={styles.badge}>
            <span className={styles.badgeDot} aria-hidden="true" />
            Synthetic household — no customer data shown
          </span>
        </div>

        <div className={styles.frame}>
          <div className={styles.chrome}>
            <span className={styles.dot} style={{ background: '#E4664B' }} />
            <span className={styles.dot} style={{ background: '#F2A93B' }} />
            <span className={styles.dot} style={{ background: '#3FBF8F' }} />
            <span className={styles.fname}>weekly-report_casa-modelo_2026-08-09.pdf</span>
          </div>
          <div className={styles.shotWrap}>
            <Image
              src="/sample_report.png"
              alt="Sample weekly report PDF, page 1: Casa Modelo, health score 86 out of 100, 264.7 kWh solar generated, 94.0% grid independence, an AI-written narrative paragraph, a daily solar-versus-consumption bar chart, and an energy-mix donut chart."
              width={SHOT_WIDTH}
              height={SHOT_HEIGHT}
              className={styles.shot}
              sizes="(max-width: 920px) 100vw, 55vw"
            />
          </div>
          <div className={styles.shotFoot}>
            <span>Page 1 of 2</span>
            {/* PLAN_PHASE16.md §8 Step 5.5 — `#cta` pointed at the
                now-deleted `AccessForm` (Oscar's explicit decision to
                retire it). "Request the full sample" isn't a signup, so
                this becomes a mailto, the same pattern Fleet's/Single
                Report's own CTAs already use, rather than /signup. */}
            <Button
              href="mailto:proyectos@paulyco.com?subject=VRM%20Monitor%20-%20Full%20sample%20report"
              variant="ghost"
              style={{ padding: '9px 16px' }}
            >
              Request the full sample
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}
