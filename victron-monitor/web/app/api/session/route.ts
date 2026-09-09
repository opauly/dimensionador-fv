// `GET /api/session` — the one place a Client Component can ask "is there
// an active session, and what role" without touching Supabase itself
// (2026-09-08, components/marketing/Nav/NavAuthArea.tsx's own need: the
// marketing page is ISR-cached (app/(marketing)/page.tsx's own
// `revalidate = 86400`), so its Server Component render can't reflect one
// specific visitor's cookies — the same static HTML is served to everyone
// between revalidations. This route is deliberately dynamic (cookies() is
// a Next.js "Dynamic API," so calling it here already opts this route out
// of any caching on its own — force-dynamic below is belt-and-suspenders,
// making that explicit rather than relying on the implicit rule) so it
// always reflects the CALLER's own cookies, fetched client-side after the
// cached page has already loaded.
//
// Deliberately minimal: role + email only, nothing a logged-out visitor
// could use for anything (no customerId, no provisioning state) — this
// endpoint has no auth requirement of its own (that's the point: anyone
// can ask "am I signed in"), so it must never leak more than what the nav
// needs to decide which two buttons to show.
import { NextResponse } from 'next/server';
import { getSessionContext } from '@/lib/server/auth';

export const dynamic = 'force-dynamic';

export async function GET() {
  const session = await getSessionContext();
  if (!session) {
    return NextResponse.json({ authenticated: false });
  }
  return NextResponse.json({
    authenticated: true,
    role: session.role,
    email: session.email,
  });
}
