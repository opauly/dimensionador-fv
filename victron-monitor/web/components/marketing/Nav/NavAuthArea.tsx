'use client';

// The nav's own auth-aware corner (2026-09-08, Oscar's own live finding:
// clicking "Get started" while already signed in as admin landed on
// /admin's Customers list — correct, /signup's own "already signed in?
// skip the form" redirect (PLAN_PHASE16.md §5.5) — but the nav right next
// to it still showed "Log in"/"Sign up" as if no session existed, which
// reads as broken/inconsistent even though it isn't).
//
// This can't be a server-side check: app/(marketing)/page.tsx is ISR-cached
// (`revalidate = 86400`), so its own render can't see any ONE visitor's
// cookies — the same static HTML is served to everyone between
// revalidations. Instead: render the logged-out state first (matching what
// the cached HTML's own server render always looks like, so hydration
// never mismatches), then check `/api/session` — a genuinely dynamic route
// (lib/server/auth.ts:getSessionContext(), which re-validates the token
// against Supabase on every call) — after mount, and swap in a profile menu
// if one exists. A returning logged-in visitor sees a brief flash of "Log
// in / Sign up" before the swap; that's the accepted tradeoff for keeping
// the page itself cacheable rather than making every anonymous visitor's
// page load pay for a live Supabase round trip too.
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui';
import { signOutAction } from '@/lib/server/auth-actions';
import styles from './NavAuthArea.module.css';

type SessionInfo =
  | { authenticated: false }
  | { authenticated: true; role: 'admin' | 'customer'; email: string };

export function NavAuthArea() {
  // `null` = not checked yet (renders the same logged-out buttons the
  // server did, so the initial client render matches SSR exactly).
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/session')
      .then((r) => r.json())
      .then((data: SessionInfo) => {
        if (!cancelled) setSession(data);
      })
      .catch(() => {
        if (!cancelled) setSession({ authenticated: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  if (session === null || !session.authenticated) {
    return (
      <>
        {/* Same inline padding override Nav.tsx's own comment explains for
            these two — kept identical so the logged-out render here is
            pixel-for-pixel what Nav.tsx used to render directly. */}
        <Button href="/login" variant="ghost" style={{ padding: '9px 16px' }}>
          Log in
        </Button>
        <Button href="/signup" variant="ghost" style={{ padding: '9px 16px' }}>
          Sign up
        </Button>
      </>
    );
  }

  const homeHref = session.role === 'admin' ? '/admin' : '/app';
  const initial = session.email.charAt(0).toUpperCase() || '?';

  return (
    <div className={styles.wrap} ref={wrapRef}>
      <button
        type="button"
        className={styles.trigger}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu — signed in as ${session.email}`}
      >
        <span className={styles.avatar} aria-hidden="true">
          {initial}
        </span>
      </button>
      {open && (
        <div className={styles.menu} role="menu">
          <div className={styles.menuEmail}>{session.email}</div>
          <Link href={homeHref} className={styles.menuItem} role="menuitem" onClick={() => setOpen(false)}>
            {session.role === 'admin' ? 'Admin dashboard' : 'My account'}
          </Link>
          {session.role === 'customer' && (
            <>
              <Link href="/app/profile" className={styles.menuItem} role="menuitem" onClick={() => setOpen(false)}>
                Profile
              </Link>
              <Link href="/app/help" className={styles.menuItem} role="menuitem" onClick={() => setOpen(false)}>
                Help
              </Link>
            </>
          )}
          <form action={signOutAction}>
            <button type="submit" className={styles.menuItemButton} role="menuitem">
              Log out
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
