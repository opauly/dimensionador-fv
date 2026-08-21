'use server';

import 'server-only';

// The `/signup` Server Action (PLAN_PHASE16.md §5.5 Step 1). A Server
// Action, not a Route Handler, specifically so Next.js's own Origin/Host
// validation applies to this POST — a free CSRF-shaped defense on the one
// public write in this app that creates a database row (§5.5 Step 1's own
// framing).
//
// Every field here is typed by the visitor and none of it is trusted —
// Zod at the boundary, with the exact length caps §6.6 calls for (name
// <=120, email <=254 per RFC, `website` — the honeypot — capped too so it
// can't be used to bloat a request). `account_type`/`ui_language` are
// `<select>`/toggle-driven in the UI, but a raw POST from outside the form
// could send anything, so they're still `z.enum()`, not `z.string()`.
//
// Whatever `submitSignup()` actually did (inserted a row, sent an
// already-a-customer email, got rate-limited, saw a filled honeypot, or
// hit a Zod validation failure below) — this action returns the SAME
// `{submitted:true}` shape every time, differing only in the `email` echo
// (the address the visitor actually typed, for the "check your email at
// <address>" copy — never a normalized/validated fact about it). That is
// the whole non-enumeration property §6.6 asks for, enforced at the one
// place a caller could otherwise learn something (a thrown error would
// render Next's generic error boundary, which IS an observable
// difference — same reasoning `requestPasswordResetAction` documents).
import { z } from 'zod';
import { submitSignup } from '@/lib/server/signup';

const signupSchema = z.object({
  name: z.string().trim().min(1).max(120),
  email: z.string().trim().email().max(254),
  account_type: z.enum(['installer', 'owner']),
  ui_language: z.enum(['en', 'es']),
  plan_id: z.preprocess((v) => (typeof v === 'string' && v.trim() !== '' ? v.trim() : undefined), z.string().uuid().optional()),
  // The honeypot — capped short; a real visitor's browser never fills
  // this, so there's no legitimate reason for it to carry a large value.
  website: z.preprocess((v) => (typeof v === 'string' ? v : ''), z.string().max(200)),
  // The "I agree to the Terms of Service and Privacy Policy" checkbox
  // (SignupForm.tsx). The client already disables Submit until it's
  // checked, so this only fires for a direct POST that skips the real
  // form — folded into the same undifferentiated `{submitted:true}`
  // fallback as every other field here (§6.6), not a distinct error, so
  // it doesn't become a second signal a caller could probe.
  agreed_to_terms: z.literal('on'),
});

export type SignupFormState = { submitted?: boolean; email?: string };

export async function signUpAction(_prevState: SignupFormState, formData: FormData): Promise<SignupFormState> {
  const typedEmail = String(formData.get('email') ?? '').trim();

  const parsed = signupSchema.safeParse({
    name: formData.get('name'),
    email: formData.get('email'),
    account_type: formData.get('account_type'),
    ui_language: formData.get('ui_language'),
    plan_id: formData.get('plan_id'),
    website: formData.get('website'),
    agreed_to_terms: formData.get('agreed_to_terms'),
  });

  // A validation failure here is never surfaced as a different response
  // shape (§6.6) — every one of these fields is either free text a length
  // cap already handles, or a value this app's own form always sends
  // correctly (a <select>/hidden input a browser can't submit malformed).
  // A failure here is therefore either a bot skipping the real form or a
  // field this app's own bug mis-sent — neither should look different
  // from success to whoever's looking at the response.
  if (!parsed.success) {
    return { submitted: true, email: typedEmail };
  }

  await submitSignup({
    name: parsed.data.name,
    email: parsed.data.email,
    accountType: parsed.data.account_type,
    planId: parsed.data.plan_id ?? null,
    uiLanguage: parsed.data.ui_language,
    honeypot: parsed.data.website,
    // No CAPTCHA is wired up yet (§0.6 Q12 unanswered) — the form never
    // renders a widget, so there is no client-side token to read.
    captchaToken: null,
  }).catch((err) => {
    // Belt-and-suspenders: `submitSignup()` already swallows its own
    // errors (see its header comment), but a thrown error escaping HERE
    // would still be the one thing this action must never do (§6.6 — see
    // the module comment above).
    console.error('signUpAction: submitSignup threw unexpectedly', err);
  });

  return { submitted: true, email: parsed.data.email };
}
