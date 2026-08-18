import Image from 'next/image';
import { Button } from '@/components/ui';
import styles from './Nav.module.css';

// public/pauly_logo.png is 567x156 (landing-page/assets/pauly_logo.png,
// copied not moved — see PLAN_PHASE14.md §6.2). Referenced by URL string
// rather than a static `import` from public/, which is the conventional
// Next.js pattern for public/ assets (static import is for files colocated
// with components); explicit width/height here reproduces the aspect ratio
// next/image would otherwise infer from an imported module.
const LOGO_WIDTH = 567;
const LOGO_HEIGHT = 156;

// Server Component — nothing here reads client state. The template's nav
// links are plain anchors to in-page section ids (#how, #modules, ...); the
// only new link is "Log in" (PLAN_PHASE14.md §2 Step 2), which points at
// /login even though that route doesn't exist until Step 3 — a marketing
// visitor clicking it before Step 3 ships gets a 404, not a broken build.
export function Nav() {
  return (
    <nav className={styles.nav}>
      <div className={`wrap ${styles.inner}`}>
        <div className={styles.brand}>
          <Image
            src="/pauly_logo.png"
            alt="Pauly & Co."
            width={LOGO_WIDTH}
            height={LOGO_HEIGHT}
            className={styles.logoImg}
            priority
          />
          <span className={styles.divider} aria-hidden="true" />
          VRM Monitor
        </div>
        <div className={styles.links}>
          <a href="#how">How it works</a>
          <a href="#modules">What&apos;s inside</a>
          <a href="#preview">Sample report</a>
          <a href="#pricing">Pricing</a>
          {/* padding override matches the template's own inline
              style="padding:9px 16px;" on these two nav .btn.ghost links —
              kept as an inline style here too rather than a CSS Module class,
              so it wins regardless of CSS-chunk ordering between Nav's
              module and Button's (a class-vs-class override would depend on
              which stylesheet Next.js happens to concatenate second). */}
          <Button href="/login" variant="ghost" style={{ padding: '9px 16px' }}>
            Log in
          </Button>
          <Button href="#cta" variant="ghost" style={{ padding: '9px 16px' }}>
            Request access
          </Button>
        </div>
      </div>
    </nav>
  );
}
