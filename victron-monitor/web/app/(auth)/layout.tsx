import type { ReactNode } from 'react';
import { Nav } from '@/components/marketing/Nav/Nav';
import styles from './auth.module.css';

// Shared chrome for /login, /signup, /activate, /forgot — a route group,
// not a real path segment, so /login stays served at /login rather than
// /auth/login.
//
// Reuses the real marketing Nav (Oscar's explicit request, 2026-08-21):
// every one of these routes now shows the same persistent top banner the
// landing page does, rather than the standalone brand-only header this
// group originally had — the plain "no Nav" reasoning this comment used to
// give (this being "the one place that must render correctly for someone
// who isn't signed in") no longer holds now that Nav itself has no
// session-dependent state; it renders identically for a signed-out
// visitor as for anyone else. `Nav`'s in-page anchors (`#how`/`#modules`/
// `#preview`/`#pricing`) are written as bare hashes for the marketing
// page's own use — from any OTHER route they'd silently no-op (a same-page
// scroll-to-nothing), which is exactly why Nav.tsx's anchors are `/#how`
// etc., not `#how`: an absolute path+hash navigates to the marketing page
// and then scrolls, correctly, from anywhere in the app.
//
// Plain `{ children: ReactNode }` rather than the generated `LayoutProps<>`
// helper (as `app/layout.tsx` uses for `'/'`): this group covers several
// sibling routes with no single route param key to name, and the generated
// type is only as current as the last `next build`/`next dev` typegen pass
// anyway.
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <Nav />
      <main className={styles.shell}>
        <div className={styles.inner}>{children}</div>
      </main>
    </>
  );
}
