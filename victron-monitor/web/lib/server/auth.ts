import 'server-only';

// Session and role resolution — the TypeScript port of
// `vrm_portal/auth.py`'s `resolve_role()` / `require_admin()` /
// `require_customer()` (PLAN_PHASE14.md §2 Step 3). Read that file before
// changing this one; the role-resolution *order* below is a deliberate,
// exact port, not a reinterpretation.
//
// ── Why this looks different in shape from the Python original ──────────
// `vrm_portal/auth.py` resolves a role once, at sign-in, and caches the
// result in `st.session_state` for the rest of that browser tab's life
// (Phase 13 §1.10 — sessions didn't survive a refresh anyway, so caching
// cost nothing extra). There is no server-side equivalent of
// `st.session_state` here: every request is its own render, so
// `getSessionContext()` re-derives role + `customerId` from Supabase on
// every call. That is intentional, not a missed optimization — it is what
// makes `requireCustomer()` / `requireAdmin()` "the first statement of
// every route handler, server action, and protected page" (§1.2 rule 4) an
// actually-enforced property instead of a stale cached one: if Oscar
// deactivates a customer mid-session, the very next guarded request sees it.
import { cache } from 'react';
import { redirect } from 'next/navigation';
import { NextResponse } from 'next/server';
import type { User } from '@supabase/supabase-js';

import { createSupabaseServerClient, getSupabaseAdmin } from './supabase';
import type { Lang } from '@/lib/i18n/strings';

/**
 * Raised when an authenticated Supabase user has no active link to a
 * `vrm.customers` row and isn't flagged as admin via `app_metadata` — the
 * exact condition `vrm_portal/auth.py:resolve_role()` raises `NotLinked`
 * for. An inactive customer hits this same branch (§1.5's "same clean
 * rejection" rule): from the outside, "never linked" and "deactivated" must
 * be indistinguishable to the person being rejected.
 */
export class NotLinked extends Error {}

export type AdminSession = {
  role: 'admin';
  customerId: null;
  userId: string;
  email: string;
  uiLanguage: 'es';
};

export type CustomerSession = {
  role: 'customer';
  customerId: string;
  userId: string;
  email: string;
  uiLanguage: Lang;
};

export type SessionContext = AdminSession | CustomerSession;

type RoleResolution =
  | { role: 'admin'; customerId: null }
  | { role: 'customer'; customerId: string; uiLanguage: Lang };

/**
 * Implements §1.5's role-resolution order exactly:
 *
 *   1. `app_metadata.vrm_role === 'admin'` -> admin, no customerId.
 *   2. Else look up `vrm.customers` by `auth_user_id`; must also be
 *      `active` -> customer, that row's id.
 *   3. Else throw `NotLinked` — an inactive customer gets the same clean
 *      rejection as an unlinked one.
 *
 * `user` is whatever `supabase.auth.getUser()` returned — `app_metadata`
 * comes back on that response, so admin never needs a second round trip.
 * Unlike the Python original, this also fetches `ui_language` in the same
 * query (one row, one round trip) rather than a separate call, because —
 * per the module docstring above — this runs on every guarded request, not
 * once per sign-in.
 */
export async function resolveRole(user: User): Promise<RoleResolution> {
  // `app_metadata`'s TS type is an index signature of `any` (it's arbitrary
  // JSON on the Supabase side); routing it through `Record<string, unknown>`
  // here is what keeps that `any` from leaking into the comparison below —
  // "No `any` crossing a server boundary" (PLAN_PHASE14.md §3), even though
  // this value never actually reaches a client.
  const appMetadata = (user.app_metadata ?? {}) as Record<string, unknown>;
  if (appMetadata.vrm_role === 'admin') {
    return { role: 'admin', customerId: null };
  }

  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('customers')
    .select('id, active, ui_language')
    .eq('auth_user_id', user.id)
    .limit(1);

  // A real Supabase/network failure is not the same fact as "not linked" —
  // let it propagate as a real error (§1.12 rule 6 covers what happens to
  // it before it reaches a browser: `lib/server/db` does that translation
  // from Step 4 onward; here it just isn't swallowed into a false rejection).
  if (error) throw error;

  const row = data?.[0] as { id: string; active: boolean; ui_language: string } | undefined;
  if (row && row.active) {
    return { role: 'customer', customerId: row.id, uiLanguage: row.ui_language === 'es' ? 'es' : 'en' };
  }
  throw new NotLinked();
}

/**
 * Returns the signed-in session, or `null` if nobody is signed in *or* the
 * signed-in user isn't linked/active (the clean-rejection case collapses to
 * the same `null` a guard sees for "no session" — callers that need to
 * distinguish the two, i.e. the sign-in action, call `resolveRole()`
 * directly instead so they can show the specific "not linked" copy and sign
 * the user back out; see `app/(auth)/login/actions.ts`).
 *
 * Wrapped in React's `cache()` deliberately: §3 requires `requireCustomer()`
 * / `requireAdmin()` to be "the first statement of every ... protected page
 * — never inferred from layout nesting," so both `app/(portal)/app/layout.tsx`
 * *and* every page under it call this independently. Without memoization
 * that would mean one `getUser()` round trip to the Supabase Auth server
 * per component instead of one per request — `cache()` is React's own
 * per-request dedup primitive for exactly this shape (same arguments, same
 * render pass, only one real call happens), so the security property (every
 * layer checks for itself) and the performance property (one network call)
 * both hold at once.
 */
export const getSessionContext = cache(async (): Promise<SessionContext | null> => {
  const supabase = await createSupabaseServerClient();

  // getUser() — never getSession(). See lib/server/supabase.ts's header
  // comment for why: getSession() trusts whatever user object is embedded
  // in the cookie without checking it against Supabase; getUser() re-
  // validates the access token against the Auth server on every call. This
  // is the one function every authorization decision in this app is built
  // on top of.
  const {
    data: { user },
    error,
  } = await supabase.auth.getUser();
  if (error || !user) return null;

  try {
    const resolution = await resolveRole(user);
    if (resolution.role === 'admin') {
      return { role: 'admin', customerId: null, userId: user.id, email: user.email ?? '', uiLanguage: 'es' };
    }
    return {
      role: 'customer',
      customerId: resolution.customerId,
      userId: user.id,
      email: user.email ?? '',
      uiLanguage: resolution.uiLanguage,
    };
  } catch (err) {
    if (err instanceof NotLinked) return null;
    throw err;
  }
});

/**
 * First statement of every protected **page** (Server Component) or
 * **Server Action**. Redirects rather than 403ing because there's no
 * meaningful response body to return from render — see
 * `requireCustomerForRoute()` below for the Route Handler equivalent.
 *
 * A signed-in admin hitting a customer-only page is redirected to `/admin`
 * (their own home) rather than back to `/login` — they're not unauthenticated,
 * so sending them to a login form they don't need would just be confusing.
 * Either way, the page body never renders for the wrong role: this is the
 * guard doing the work, not `AppShell`'s nav happening to omit a link
 * (§1.2 rule 4 — "navigation-level gating is UX, never the control").
 */
export async function requireCustomer(): Promise<CustomerSession> {
  const session = await getSessionContext();
  if (session === null) redirect('/login');
  if (session.role !== 'customer') redirect('/admin');
  return session;
}

/** Admin counterpart of `requireCustomer()`. See its comment for the redirect reasoning. */
export async function requireAdmin(): Promise<AdminSession> {
  const session = await getSessionContext();
  if (session === null) redirect('/login');
  if (session.role !== 'admin') redirect('/app');
  return session;
}

const FORBIDDEN = () => NextResponse.json({ error: 'Not authorized.' }, { status: 403 });

/**
 * Route Handler equivalent of `requireCustomer()` — a Route Handler is
 * answering a `fetch()`, not rendering a page, so it gets a 403 JSON body
 * instead of a redirect. Call sites narrow the union before use:
 *
 *   const session = await requireCustomerForRoute();
 *   if (session instanceof NextResponse) return session;
 *   // session is CustomerSession from here down.
 *
 * Not exercised by anything in Step 3 (no Route Handlers exist yet) — built
 * now because Step 4's `app/api/*` proxies and Step 6's upload/report
 * routes depend on it existing with this exact contract.
 */
export async function requireCustomerForRoute(): Promise<CustomerSession | NextResponse> {
  const session = await getSessionContext();
  if (session === null || session.role !== 'customer') return FORBIDDEN();
  return session;
}

/** Route Handler equivalent of `requireAdmin()`. See `requireCustomerForRoute()`. */
export async function requireAdminForRoute(): Promise<AdminSession | NextResponse> {
  const session = await getSessionContext();
  if (session === null || session.role !== 'admin') return FORBIDDEN();
  return session;
}
