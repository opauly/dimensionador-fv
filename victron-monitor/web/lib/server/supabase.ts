import 'server-only';

// Supabase access, server-only — PLAN_PHASE14.md §1.2.
//
// This module is the ONLY place in the web app allowed to construct a
// Supabase client. Two clients, two jobs, deliberately not one:
//
//   createSupabaseServerClient() -- an @supabase/ssr client bound to this
//     request's cookies via Next's `cookies()`, keyed with the
//     PUBLISHABLE key. Its only job is auth: sign-in, sign-out, and
//     `getUser()`. Never call `.schema()`/`.from()` on it.
//   getSupabaseAdmin() -- a plain, lazily-constructed singleton keyed with
//     the SECRET key (mirrors `database/supabase_client.py:get_client()`).
//     Its only job is data: `.schema('vrm').from(...)`. Never call
//     `.auth.*` on it.
//
// Why this split survives even though the Python hazard that originally
// motivated it (vrm_portal/auth.py's "two-client rule") does not: supabase-py
// mutates a shared client's PostgREST auth header on every SIGNED_IN /
// SIGNED_OUT event, so signing a user in on the service_role singleton would
// silently re-scope every other caller's next query to that user's token.
// @supabase/ssr's server client is constructed fresh per request instead
// (see createSupabaseServerClient below), so that specific failure mode
// doesn't exist here. The split is kept anyway because the *principle* —
// the client that authenticates a browser's cookie session should never be
// the same client instance that reads tenant data with elevated privilege —
// is still the right shape, and keeping it means a future contributor never
// has to wonder whether it's safe to call `.auth.signInWithPassword()` on
// the client that also renders someone else's `vrm.sites` rows.
//
// ── Why there is no browser-exposed Supabase env var anywhere in this repo ──
// Every other Next.js Supabase example defines a browser client from a
// `NEXT_PUBLIC_`-prefixed URL/key pair. This app deliberately has no such
// variables and no browser Supabase client at all (§1.2 rule 2). That is
// not a style preference — Next's `NEXT_PUBLIC_` prefix is its own
// mechanism for inlining a value into the client bundle at build time, so
// its mere absence here is a structural guarantee that no client-side code
// can construct a Supabase client, accidentally or otherwise.
// `import 'server-only'` above turns any future attempt to pull this
// module into a Client Component into a build error instead of a runtime
// leak (a repo-wide grep for that env var prefix is one of the three leak
// checks re-run at every later step — see the README).
//
// ── Why `getUser()` and not `getSession()` (both here and in lib/server/auth.ts) ──
// `getSession()` reads the session straight out of the cookie and returns
// whatever user object is embedded in it, without contacting the Supabase
// Auth server — the cookie is client-readable-adjacent (Next can read it,
// but so could a tampered proxy or a bug that forwards it somewhere it
// shouldn't), so that user object is not verified. `getUser()` re-validates
// the access token against Supabase's Auth server on every call, which is
// the only version of "who is this" this app treats as an authorization
// fact — @supabase/ssr's own type declarations say exactly this
// (`node_modules/@supabase/ssr/.../types.d.ts`, the `CookieMethodsServer`
// doc comment). Every guard in `lib/server/auth.ts` is built on `getUser()`.
//
// ── Why `realtime: { transport: ws }` is passed to every client here ────
// Neither client in this module subscribes to anything — this app only
// ever does Auth calls and PostgREST reads/writes. But `@supabase/supabase-js`
// constructs a `RealtimeClient` unconditionally inside `createClient()`
// (and `@supabase/ssr`'s `createServerClient()` forwards straight through to
// it), and as of the installed version that constructor throws immediately
// if it can't find a `WebSocket` global — which Node.js only provides
// natively from v22 (`node_modules/@supabase/realtime-js/.../websocket-
// factory.js:detectEnvironment()`). This repo's web app is pinned to Node
// 20.20.0 (`.nvmrc`) for local dev, so every Supabase client construction
// would otherwise crash before this module's first real call. `ws` is
// already a real npm dependency (not a shim) — supplying it as the
// `transport` is the fix `realtime-js`'s own thrown error message
// recommends, and costs nothing at runtime since the realtime channel it
// would open is never used.
import { createServerClient } from '@supabase/ssr';
import { createClient, type RealtimeClientOptions, type SupabaseClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';
import WebSocket from 'ws';

// `ws`'s own type declarations don't structurally match `realtime-js`'s
// `WebSocketLikeConstructor` (its "attach to an existing raw socket"
// constructor overload types `address` as `null`, which trips up matching
// against the browser-shaped interface `createClient()` expects) even
// though `ws` is a correct drop-in *at runtime* — Supabase's own
// documentation snippet for this exact fix (`new RealtimeClient(url, {
// transport: ws })`) has the same mismatch. One narrow, explicit cast here
// is clearer than widening the option's type or reaching for `any`.
const wsTransport = WebSocket as unknown as NonNullable<RealtimeClientOptions['transport']>;

function requireEnv(name: 'SUPABASE_URL' | 'SUPABASE_PUBLISHABLE_KEY' | 'SUPABASE_SECRET_KEY'): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set. See victron-monitor/web/README.md for the required env vars.`);
  }
  return value;
}

/**
 * The per-request auth/session client for Server Components, Server
 * Actions, and Route Handlers. Always construct a new one per request (the
 * @supabase/ssr docs are explicit about this) — never hold a module-level
 * reference to this one, unlike `getSupabaseAdmin()` below.
 */
export async function createSupabaseServerClient() {
  const cookieStore = await cookies();

  return createServerClient(requireEnv('SUPABASE_URL'), requireEnv('SUPABASE_PUBLISHABLE_KEY'), {
    realtime: { transport: wsTransport },
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // Next.js only allows cookie mutation from a Server Action or
          // Route Handler, not while a Server Component is rendering (see
          // the `cookies()` docs: "Setting cookies is not supported during
          // Server Component rendering"). A Server Component that only
          // calls `getUser()` still needs `setAll` wired up so refreshed
          // tokens *can* be written back to cookies wherever that's legal —
          // it just can't do it from here. `proxy.ts`'s own client (with a
          // working setAll on every request) is what actually keeps the
          // session alive across a hard refresh; this try/catch just stops
          // that one, expected, non-error case from crashing a page render.
        }
      },
    },
  });
}

// A lazy singleton, deliberately mirroring
// `database/supabase_client.py:get_client()` (constructed once, on first
// use, keyed with the highest-privilege credential this app holds). Safe as
// a singleton specifically *because* nothing in this module ever calls
// `.auth.*` on it — see the module docstring above.
let _admin: SupabaseClient | null = null;

export function getSupabaseAdmin(): SupabaseClient {
  if (_admin === null) {
    _admin = createClient(requireEnv('SUPABASE_URL'), requireEnv('SUPABASE_SECRET_KEY'), {
      auth: { persistSession: false, autoRefreshToken: false },
      realtime: { transport: wsTransport },
    });
  }
  return _admin;
}
