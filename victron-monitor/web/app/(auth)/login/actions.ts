'use server';

import 'server-only';

// The sign-in Server Action (PLAN_PHASE14.md §2 Step 3). This is the
// TypeScript port of `vrm_portal/auth.py:sign_in()` — read that function's
// docstring before changing this one. Two things it must keep doing
// exactly as the Python original does:
//
//   1. Every credential failure — wrong password, no such account, a
//      rate limit — surfaces the SAME generic copy. Distinguishing "no
//      such user" from "wrong password" is precisely what an account-
//      enumeration attack goes looking for, and there's no legitimate UI
//      need to tell them apart here. (PLAN_PHASE16.md §8 Step 5.5: this
//      used to say "on a portal with no public signup" — that's now
//      stale, since `/signup` exists — but the behaviour this comment
//      justifies matters MORE now, not less: `/signup` itself is
//      non-enumerating by the same discipline, §6.6, and this sign-in
//      form staying that way too is what keeps "does an account exist
//      for this email" unanswerable from either surface.)
//   2. If Supabase Auth accepts the credentials but role resolution then
//      rejects the account (`NotLinked` — unlinked or deactivated), the
//      session that sign-in just created is torn down with `signOut()`
//      before the rejection is returned. A user who can't use the portal
//      must never be left holding a live (if useless) auth cookie — this
//      is the specific behaviour Step 3's validation checks for with a
//      hard-refresh / new-tab test.
//
// Deliberately does NOT call `getSessionContext()` — that function
// collapses "no session" and "not linked" into the same `null` (correct
// for a guard, which only needs to know "may this request proceed"), but
// this action needs the distinction to choose between the generic
// `login_error` copy and the specific `not_linked_error` copy, so it calls
// `resolveRole()` directly instead.
import { redirect } from 'next/navigation';
import { createSupabaseServerClient } from '@/lib/server/supabase';
import { NotLinked, resolveRole } from '@/lib/server/auth';
import { t } from '@/lib/i18n/strings';

export type LoginFormState = { error?: string };

// The login screen is always English — the app's default UI language,
// same reasoning as `vrm_portal/views/login.py`'s `_LANG = "en"`: a
// customer's own `ui_language` preference isn't known until *after* they've
// signed in and their `vrm.customers` row has been resolved.
const LANG = 'en' as const;

export async function signInAction(_prevState: LoginFormState, formData: FormData): Promise<LoginFormState> {
  const email = String(formData.get('email') ?? '').trim();
  const password = String(formData.get('password') ?? '');

  if (!email || !password) {
    return { error: t(LANG, 'login_missing_fields') };
  }

  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase.auth.signInWithPassword({ email, password });

  if (error || !data.user) {
    return { error: t(LANG, 'login_error') };
  }

  let redirectTo: '/admin' | '/app';
  try {
    const resolution = await resolveRole(data.user);
    redirectTo = resolution.role === 'admin' ? '/admin' : '/app';
  } catch (err) {
    if (err instanceof NotLinked) {
      await supabase.auth.signOut();
      return { error: t(LANG, 'not_linked_error') };
    }
    throw err;
  }

  // Outside the try/catch on purpose — `redirect()` throws a control-flow
  // exception that must not be caught by the `catch` block above (the
  // Next.js docs are explicit: call `redirect()` outside `try`/`catch`).
  redirect(redirectTo);
}
