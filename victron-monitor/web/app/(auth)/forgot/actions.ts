'use server';

import 'server-only';

// The `/forgot` Server Action (PLAN_PHASE14.md §2 Step 7).
//
// Why this always returns the same `{success: true}` no matter what
// happened internally: telling a visitor "no account with that email"
// vs. "reset link sent" is a textbook account-enumeration leak — it lets
// anyone learn which email addresses are (or aren't) customers just by
// trying them here, with no login required. `lib/server/invites.ts:
// sendPasswordReset()` already does nothing observably different for an
// unknown address (no error thrown, no distinguishable timing this action
// waits on differently); this action's only remaining job is to not
// introduce a difference of its own by branching on the result.
import { sendPasswordReset } from '@/lib/server/invites';

export type ForgotFormState = { submitted?: boolean };

export async function requestPasswordResetAction(_prevState: ForgotFormState, formData: FormData): Promise<ForgotFormState> {
  const email = String(formData.get('email') ?? '').trim();
  if (email) {
    // Errors here (a Supabase outage, a malformed address that still made
    // it past the <input type="email"> guard) are swallowed on purpose —
    // see the module comment. A thrown error here would surface Next's
    // generic error boundary, which IS an observable difference from the
    // success path.
    await sendPasswordReset(email).catch(() => undefined);
  }
  return { submitted: true };
}
