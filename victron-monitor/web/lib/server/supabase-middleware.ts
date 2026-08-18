import 'server-only';

// The request/response-bound half of the token-refresh pattern
// (PLAN_PHASE14.md §2 Step 3: "middleware.ts — Supabase's documented
// token-refresh middleware pattern"). Kept separate from
// `lib/server/supabase.ts:createSupabaseServerClient()` because that one is
// bound to Next's `cookies()` (only available inside a Server Component /
// Action / Route Handler's request context), whereas `proxy.ts` gets a raw
// `NextRequest`/`NextResponse` pair instead — the two cookie adapters
// aren't interchangeable, so this is a second, small implementation of the
// same @supabase/ssr `cookies` contract, not a reusable one split out of
// laziness.
//
// This function's ONLY job is refreshing the auth cookie before it expires
// (calling `getUser()` has the side effect of writing a refreshed session
// back through `setAll` if the access token was near expiry). It does not
// redirect, and it does not check role. Gating happens at
// `requireCustomer()` / `requireAdmin()` (`lib/server/auth.ts`), which run
// as the first statement of the page/action/route itself — per §1.2 rule 4,
// "navigation-level gating is UX, never the control," and a proxy running
// ahead of the render is exactly a navigation-level gate. Concretely: this
// is what makes Phase 13 §1.10's "no session persistence across a hard
// refresh" limitation go away for free — without it, a customer who leaves
// a tab open past the access token's short lifetime would silently get
// signed out the next time a guard called `getUser()`.
//
// `realtime: { transport: ws }` — same reasoning and same cast-past-a-type-
// mismatch as `lib/server/supabase.ts`'s header comment: this client never
// subscribes to anything, but `createServerClient()` still constructs a
// `RealtimeClient` eagerly, which throws on Node.js < 22 without an
// explicit WebSocket implementation. Next 16's Proxy runs on the Node.js
// runtime by default (not Edge), so `ws` resolves the same way it does
// everywhere else in this module tree.
import { createServerClient } from '@supabase/ssr';
import { NextResponse, type NextRequest } from 'next/server';
import type { RealtimeClientOptions } from '@supabase/supabase-js';
import WebSocket from 'ws';

const wsTransport = WebSocket as unknown as NonNullable<RealtimeClientOptions['transport']>;

export async function refreshSupabaseSession(request: NextRequest): Promise<NextResponse> {
  // Re-wrapped every time `setAll` fires below, so the cookies we just read
  // off `request` are visible to the rest of this proxy pass AND ride along
  // on the response — this two-step dance (write to `request.cookies`, then
  // rebuild `response` from that mutated request) is @supabase/ssr's own
  // documented pattern for keeping both directions in sync within one call.
  let response = NextResponse.next({ request });

  const supabaseUrl = process.env.SUPABASE_URL;
  const supabasePublishableKey = process.env.SUPABASE_PUBLISHABLE_KEY;
  if (!supabaseUrl || !supabasePublishableKey) {
    throw new Error('SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY are not set. See victron-monitor/web/README.md.');
  }

  const supabase = createServerClient(supabaseUrl, supabasePublishableKey, {
    realtime: { transport: wsTransport },
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value);
        }
        response = NextResponse.next({ request });
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options);
        }
      },
    },
  });

  // Do not add code between `createServerClient` and `getUser()` — a
  // mistake here is exactly the class of bug @supabase/ssr's own docs warn
  // makes users randomly logged out (this call is the one that triggers the
  // refresh; anything reading the session before it runs sees the stale one).
  await supabase.auth.getUser();

  return response;
}
