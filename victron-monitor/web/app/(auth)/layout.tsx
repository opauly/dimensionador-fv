import type { ReactNode } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import styles from './auth.module.css';

// Shared chrome for /login (this step) and /activate + /forgot (Step 7) —
// a route group, not a real path segment, so /login stays served at
// /login rather than /auth/login. Deliberately minimal: no Nav, no
// footer, nothing that implies the visitor is anywhere but a standalone
// sign-in screen — this is the one place in the app that must render
// correctly for someone who isn't signed in and may never have been.
//
// Plain `{ children: ReactNode }` rather than the generated `LayoutProps<>`
// helper (as `app/layout.tsx` uses for `'/'`): this group covers three
// sibling routes (`/login` now, `/activate` and `/forgot` at Step 7) with
// no single route param key to name, and the generated type is only as
// current as the last `next build`/`next dev` typegen pass anyway.
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className={styles.shell}>
      <div className={styles.inner}>
        <Link href="/" className={styles.brand}>
          <Image src="/pauly_logo.png" alt="Pauly & Co." width={567} height={156} className={styles.logoImg} />
          <span className={styles.divider} aria-hidden="true" />
          VRM Monitor
        </Link>
        {children}
      </div>
    </main>
  );
}
