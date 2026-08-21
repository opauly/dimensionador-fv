'use server';

import 'server-only';

// Server Actions for `/activate` (PLAN_PHASE14.md §2 Step 7).
//
// ── Why `verifyActivationTokenAction` exists at all, instead of `page.tsx` just calling `verifyOtp()` itself ──
// A Server *Component* cannot persist cookies — Next.js enforces this
// (`lib/server/supabase.ts`'s own `setAll` has a documented try/catch for
// exactly this restriction: "Setting cookies is not supported during
// Server Component rendering"). `verifyOtp()` needs to *set* the session
// cookie it establishes, so it has to run somewhere Next.js allows a cookie
// write — a Server Action or a Route Handler. This repo's deliverable is
// `app/(auth)/activate/page.tsx` (a page, not a route handler), so
// `page.tsx` reads `token_hash`/`type` from its own server-rendered
// `searchParams` and hands a *bound Server Action* down to a client
// component — never the token itself. See `ActivateClient.tsx`'s own
// comment for why a bound action reference isn't the same thing as passing
// the token as a literal client-component prop (Next.js serializes a bound
// Server Action as an opaque reference, not inspectable client-side data —
// the same mechanism `app/(portal)/app/sites/SitesManager.tsx` already
// relies on for `updateSiteAction.bind(null, site.site_id)`).
import { redirect } from 'next/navigation';
import type { EmailOtpType } from '@supabase/supabase-js';
import { createSupabaseServerClient } from '@/lib/server/supabase';
import { getCustomerByAuthUserId, markActivated } from '@/lib/server/invites';
import { t } from '@/lib/i18n/strings';

const ALLOWED_TYPES: readonly string[] = ['invite', 'recovery', 'magiclink'];

export type VerifyResult = { ok: true } | { ok: false };

/**
 * Bound to `(tokenHash, type)` server-side in `page.tsx`, then called with
 * no further arguments from `ActivateClient` on mount. Establishes a real
 * session (cookies set on the response) on success — the "set your
 * password" form that follows relies on that session existing; it never
 * receives the token itself.
 */
export async function verifyActivationTokenAction(tokenHash: string, type: string): Promise<VerifyResult> {
  if (!tokenHash || !ALLOWED_TYPES.includes(type)) return { ok: false };

  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.verifyOtp({ token_hash: tokenHash, type: type as EmailOtpType });
  // Expired/already-used/malformed tokens all collapse to the same `{ok:
  // false}` here — `ActivateClient` shows one friendly message for all of
  // them (PLAN_PHASE14.md §2 Step 7: "Expired or already-used token → a
  // friendly ... message, never a stack trace or raw Supabase error"), the
  // same "don't distinguish failure reasons that don't change what the
  // visitor should do" instinct `login/actions.ts` already applies to
  // credential failures.
  return { ok: !error };
}

export type SetPasswordState = { error?: string };

/**
 * `nextPath` is bound server-side in `page.tsx` (`.bind(null, nextPath)`,
 * the same pattern `verifyActivationTokenAction.bind(null, tokenHash,
 * type)` already uses one function up) — never read from a client
 * component prop, matching this file's own header comment on why the
 * token/type pair is threaded the same way. Already validated by
 * `page.tsx`'s own `sanitizeNextPath()` (PLAN_PHASE16.md §5.5 Step 3's
 * open-redirect guard) before it's ever bound — this function trusts its
 * bound argument, the same way `verifyActivationTokenAction` trusts the
 * `tokenHash`/`type` `page.tsx` bound onto it.
 *
 * `sanitizeNextPath()` itself lives in `page.tsx`, NOT here, even though
 * this file is otherwise the natural home for it: every export from a
 * `'use server'` file becomes a Server Action reference, and Next.js
 * requires every one of them to be an `async` function — a plain
 * synchronous helper exported from this file breaks the ENTIRE module at
 * compile time ("Server Actions must be async functions"), which is not a
 * theoretical hazard: it broke `/activate` outright during this step's own
 * validation before being caught and fixed by moving the function out.
 */
export async function setActivationPasswordAction(nextPath: string, _prevState: SetPasswordState, formData: FormData): Promise<SetPasswordState> {
  const password = String(formData.get('password') ?? '');
  const confirm = String(formData.get('confirm_password') ?? '');

  if (password.length < 8) return { error: t('en', 'activate_error_short') };
  if (password !== confirm) return { error: t('en', 'activate_error_mismatch') };

  const supabase = await createSupabaseServerClient();

  // Re-derive the user from the session `verifyActivationTokenAction`
  // established — never trust anything about "who this is" from the form
  // itself, matching `getUser()` (never `getSession()`) everywhere else in
  // this app that gates on identity.
  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser();
  if (userError || !user) return { error: t('en', 'activate_error_generic') };

  const { error: updateError } = await supabase.auth.updateUser({ password });
  if (updateError) return { error: t('en', 'activate_error_generic') };

  const customer = await getCustomerByAuthUserId(user.id);
  if (customer) {
    // Best-effort: a customer row not resolving here (shouldn't happen —
    // `sendInvite()`/`resendInvite()` always stamp `auth_user_id` before
    // this link is ever sent) must not strand the visitor on a form that
    // just silently fails after their password DID get set.
    await markActivated(user.id).catch(() => undefined);
  }

  // Outside any try/catch — `redirect()` is a control-flow throw, same
  // rule `login/actions.ts` follows. `nextPath` was already validated by
  // `sanitizeNextPath()` before this action was ever bound (`page.tsx`),
  // not re-checked here — this function trusts its own bound argument, the
  // same way `verifyActivationTokenAction` trusts the `tokenHash`/`type`
  // `page.tsx` bound onto IT.
  redirect(nextPath);
}
