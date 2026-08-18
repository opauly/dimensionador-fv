'use server';

import 'server-only';

// Server Actions for `app/(portal)/app/profile` (PLAN_PHASE14.md §2 Step 4).
// `requireCustomer()` first in both, per §3.
import { revalidatePath } from 'next/cache';
import { z } from 'zod';
import { requireCustomer } from '@/lib/server/auth';
import { createSupabaseServerClient } from '@/lib/server/supabase';
import { updateCustomerProfile, type ProfileUpdateFields } from '@/lib/server/db';
import { t } from '@/lib/i18n/strings';

const stringOrNull = z.preprocess((v) => (typeof v === 'string' && v.trim() !== '' ? v.trim() : null), z.string().nullable());

const profileFormSchema = z.object({
  name: z.string().trim().min(1),
  contact_name: stringOrNull,
  contact_email: stringOrNull,
  country: z.string().trim().min(1),
  ui_language: z.enum(['en', 'es']),
});

export type ProfileFormState = { error?: string; success?: boolean };

export async function updateProfileAction(_prevState: ProfileFormState, formData: FormData): Promise<ProfileFormState> {
  const session = await requireCustomer();

  const parsed = profileFormSchema.safeParse({
    name: formData.get('name'),
    contact_name: formData.get('contact_name'),
    contact_email: formData.get('contact_email'),
    country: formData.get('country'),
    ui_language: formData.get('ui_language'),
  });
  if (!parsed.success) {
    return { error: t(session.uiLanguage, 'profile_save_error') };
  }

  try {
    await updateCustomerProfile(session.customerId, parsed.data as ProfileUpdateFields);
  } catch {
    return { error: t(session.uiLanguage, 'profile_save_error') };
  }

  // `updateCustomerProfile` can change `ui_language`, which
  // `app/(portal)/app/layout.tsx` reads on every render to build the nav —
  // revalidating the `/app` *layout* (not just this page) is what makes a
  // language switch visible in the nav without a manual refresh, since this
  // action itself doesn't touch a cookie (the thing that would otherwise
  // trigger an automatic re-render per the Server Actions guide).
  revalidatePath('/app', 'layout');
  return { success: true };
}

export type PasswordFormState = { error?: string; success?: boolean };

export async function changePasswordAction(_prevState: PasswordFormState, formData: FormData): Promise<PasswordFormState> {
  const session = await requireCustomer();

  const current = String(formData.get('current_password') ?? '');
  const next = String(formData.get('new_password') ?? '');
  const confirm = String(formData.get('confirm_password') ?? '');

  if (!current || !next || !confirm) {
    return { error: t(session.uiLanguage, 'profile_change_password_error_generic') };
  }
  if (next.length < 8) {
    return { error: t(session.uiLanguage, 'profile_change_password_error_short') };
  }
  if (next !== confirm) {
    return { error: t(session.uiLanguage, 'profile_change_password_error_mismatch') };
  }

  const supabase = await createSupabaseServerClient();

  // Re-authenticate with the CURRENT password before allowing the change —
  // the TS port of `vrm_portal`'s (never-built, Phase-13-planned) "sign in
  // again with the current password on a fresh client, then update" flow.
  // The "fresh client" half of that plan doesn't apply here the way it did
  // in Python: `createSupabaseServerClient()` already constructs a new
  // per-request client every call (see its own header comment in
  // `lib/server/supabase.ts` for why the singleton hazard that motivated
  // "fresh" in the Python original doesn't exist in `@supabase/ssr`), so
  // this is just that same client, used for what it's always used for
  // (auth calls only, never `.schema()`/`.from()`). What's non-negotiable
  // is the *order*: never call `updateUser({ password })` without a
  // `signInWithPassword` immediately before it that used the caller-
  // supplied current password — a live but stolen session must not be
  // enough on its own to change the password.
  const { error: reauthError } = await supabase.auth.signInWithPassword({
    email: session.email,
    password: current,
  });
  if (reauthError) {
    return { error: t(session.uiLanguage, 'profile_change_password_error_wrong_current') };
  }

  const { error: updateError } = await supabase.auth.updateUser({ password: next });
  if (updateError) {
    return { error: t(session.uiLanguage, 'profile_change_password_error_generic') };
  }

  return { success: true };
}
