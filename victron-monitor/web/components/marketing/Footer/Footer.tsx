import Link from 'next/link';
import styles from './Footer.module.css';

// Footer now renders on /terms and /privacy too (not just the marketing
// home page), so the in-page anchors need the leading `/` — a bare `#how`
// clicked from /terms would try to scroll that page instead of navigating
// home, same bug class already fixed on Nav.tsx's links (PLAN_PHASE16.md
// §8 legal follow-up, 2026-08-20).
export function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={`wrap ${styles.inner}`}>
        <div className={styles.brand}>
          <svg className={styles.mark} viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M15 2 L27 8.5 V21.5 L15 28 L3 21.5 V8.5 Z" stroke="#6F93A6" strokeWidth="1.6" fill="none" />
          </svg>
          VRM Monitor by Pauly &amp; Co. — Atenas, Costa Rica
        </div>
        <div className={styles.links}>
          <a href="mailto:proyectos@paulyco.com">proyectos@paulyco.com</a>
          <Link href="/#how">How it works</Link>
          <Link href="/#modules">What&apos;s inside</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/privacy">Privacy</Link>
        </div>
      </div>
    </footer>
  );
}
