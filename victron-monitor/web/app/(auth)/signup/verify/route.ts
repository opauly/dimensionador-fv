// `GET /signup/verify?token=…` (PLAN_PHASE16.md §5.5 Step 2). The only
// public-facing code in this app that ever creates a real `vrm.customers`
// row — everything up to here (`app/(auth)/signup/actions.ts`) only ever
// wrote a `vrm.signup_requests` staging row.
//
// A Route Handler, not a Server Action: this is a plain `<a href>` link
// clicked from an email, not a form submission this app rendered — there
// is no client-side dispatcher to POST through.
//
// `lib/server/signup.ts:redeemSignupToken()` does the actual work (consume
// -> create customer -> link/create auth user -> stamp -> build a redirect
// target); this handler's only job is turning that result into an HTTP
// redirect, exactly the shape `app/api/webhooks/onvo/route.ts` follows for
// its own "thin route, real logic elsewhere" split.
//
// Every outcome (missing token, already-used, expired, tampered,
// `already_linked_elsewhere` race) redirects to the SAME
// `/signup?status=link_used` — one friendly message, not three, per §5.5
// Step 2's own instruction. Never a raw error page, and never a body that
// distinguishes "expired" from "already used" from "never existed."
import { NextResponse } from 'next/server';
import { redeemSignupToken } from '@/lib/server/signup';

const LINK_USED_PATH = '/signup?status=link_used';

export async function GET(request: Request) {
  const url = new URL(request.url);
  const token = url.searchParams.get('token');

  if (!token) {
    return NextResponse.redirect(new URL(LINK_USED_PATH, url));
  }

  const result = await redeemSignupToken(token);
  if (!result.ok) {
    return NextResponse.redirect(new URL(LINK_USED_PATH, url));
  }

  // NEVER log `result.redirectUrl` — it carries a real, single-use
  // activation token (`token_hash`) in its own query string, the same
  // secret-equivalent value an emailed invite link carries (§11 / §5.5
  // Step 2's own note on this exact URL).
  return NextResponse.redirect(new URL(result.redirectUrl, url));
}
