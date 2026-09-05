import Image from 'next/image';
import Link from 'next/link';
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
// links are anchors to in-page section ids (`/#how`, `/#modules`, ...) —
// an absolute path, not a bare `#how`, since `Nav` now renders on
// `/login`/`/signup`/etc. too (2026-08-21): a bare hash from one of those
// routes would just scroll the current (sectionless) page to nowhere,
// while `/#how` correctly navigates to the marketing page and scrolls
// there, from anywhere. Rendered via `next/link` rather than a plain `<a>`
// — eslint's `@next/next/no-html-link-for-pages` is right that a same-origin
// path belongs on `Link`, hash suffix or not; `Link` still performs a
// normal scroll-to-element after navigating, same as a plain anchor would.
// The two other links, "Log in"
// (PLAN_PHASE14.md §2 Step 2) and "Sign up" (PLAN_PHASE16.md §8 Step 5.5 —
// replaces the old `#cta` anchor into the now-deleted `AccessForm`,
// Oscar's explicit decision to retire it), point at real routes.
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
          <Link href="/#how">How it works</Link>
          <Link href="/#modules">What&apos;s inside</Link>
          <Link href="/#preview">Sample report</Link>
          <Link href="/#dashboard">Live dashboard</Link>
          <Link href="/#pricing">Pricing</Link>
          {/* padding override matches the template's own inline
              style="padding:9px 16px;" on these two nav .btn.ghost links —
              kept as an inline style here too rather than a CSS Module class,
              so it wins regardless of CSS-chunk ordering between Nav's
              module and Button's (a class-vs-class override would depend on
              which stylesheet Next.js happens to concatenate second). */}
          <Button href="/login" variant="ghost" style={{ padding: '9px 16px' }}>
            Log in
          </Button>
          <Button href="/signup" variant="ghost" style={{ padding: '9px 16px' }}>
            Sign up
          </Button>
        </div>
      </div>
    </nav>
  );
}
