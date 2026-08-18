// Token-refresh entry point — PLAN_PHASE14.md §2 Step 3 calls this file
// `middleware.ts`; Next.js 16 deprecated and renamed that file convention to
// `proxy.ts` / `export function proxy()` between the plan being written and
// this step being built (`node_modules/next/dist/docs/.../proxy.md`: "The
// `middleware.js` file convention has been deprecated ... and renamed to
// `proxy.js`. All functionality remains the same — only the file and export
// names have changed."). This *is* PLAN_PHASE14.md's "middleware.ts", under
// the name the installed Next.js version requires.
//
// Matched to exactly the routes that touch a Supabase session
// (PLAN_PHASE14.md §2 Step 3): `/app`, `/admin`, `/login`, `/activate`
// (the last is Step 7's, matched now so it doesn't need a second edit to
// this file later). Everything else — the marketing site, static assets,
// `/styleguide` — never reads or writes a Supabase cookie, so running this
// on every request there would just be per-request Auth-server latency
// with nothing to show for it.
import type { NextRequest } from 'next/server';
import { refreshSupabaseSession } from '@/lib/server/supabase-middleware';

export function proxy(request: NextRequest) {
  return refreshSupabaseSession(request);
}

export const config = {
  matcher: ['/app/:path*', '/admin/:path*', '/login', '/activate/:path*'],
};
