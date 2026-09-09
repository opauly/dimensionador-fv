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
// against Supabase on every call) — after mount, and swap in the shared
// `AccountMenu` (same avatar/dropdown the in-app header uses, 2026-09-08)
// if one exists. A returning logged-in visitor sees a brief flash of "Log
// in / Sign up" before the swap; that's the accepted tradeoff for keeping
// the page itself cacheable rather than making every anonymous visitor's
// page load pay for a live Supabase round trip too.
import { useEffect, useState } from 'react';
import { AccountMenu, Button } from '@/components/ui';

type SessionInfo =
  | { authenticated: false }
  | { authenticated: true; role: 'admin' | 'customer'; email: string };

export function NavAuthArea() {
  // `null` = not checked yet (renders the same logged-out buttons the
  // server did, so the initial client render matches SSR exactly).
  const [session, setSession] = useState<SessionInfo | null>(null);

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

  // From outside the app, the dropdown's first job is getting the visitor
  // BACK into it — Profile/Help are real pages there too, but a visitor who
  // hasn't followed the "My account"/"Admin dashboard" link yet has never
  // seen the in-app nav that would otherwise surface them.
  const items =
    session.role === 'admin'
      ? [{ href: '/admin', label: 'Admin dashboard' }]
      : [
          { href: '/app', label: 'My account' },
          { href: '/app/profile', label: 'Profile' },
          { href: '/app/help', label: 'Help' },
        ];

  return <AccountMenu email={session.email} items={items} />;
}
