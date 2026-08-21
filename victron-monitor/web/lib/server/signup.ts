import 'server-only';

// The public signup flow's orchestration layer (PLAN_PHASE16.md §5.5 Step 1
// + Step 2, §8 Step 5.5 build item 2). Two public-facing operations, both
// called by thin wrappers under `app/(auth)/signup/**`:
//
//   submitSignup()      — the ENTIRE §5.5 Step 1 sequence (honeypot, rate
//                          limits, the CAPTCHA seam, the existing-account
//                          branch, the token mint + insert). Called from
//                          `app/(auth)/signup/actions.ts`'s Server Action,
//                          which always returns the same {submitted:true}
//                          no matter what this function actually did —
//                          §6.6's non-enumeration discipline lives HERE,
//                          not in the action, because this is the one place
//                          that ever sees the real branch taken.
//   redeemSignupToken() — the §5.5 Step 2 sequence: atomically consume the
//                          token, create the ONE vrm.customers row signup
//                          is allowed to create (`lib/server/db/signup.ts:
//                          createSelfServeCustomer()`), link/create the
//                          Supabase auth user (`lib/server/invites.ts:
//                          createOrLinkAuthUser()`), stamp it, and hand back
//                          a same-origin redirect target for
//                          `app/(auth)/signup/verify/route.ts` to issue.
//
// Neither function is reachable from `lib/server/db` (the tenant-scoped
// choke point, PLAN_PHASE14.md §1.2 rule 4) — this is pre-session code by
// definition, so it talks to `lib/server/db/signup.ts` and
// `lib/server/invites.ts` directly, the same way `lib/server/invites.ts`
// itself does.
import crypto from 'node:crypto';
import { headers } from 'next/headers';
import { checkRateLimit } from './ratelimit';
import {
  consumeSignupRequest,
  createSelfServeCustomer,
  customerExistsByEmail,
  deleteSelfServeCustomer,
  insertSignupRequest,
  linkSignupRequestToCustomer,
} from './db/signup';
import { createOrLinkAuthUser, stampInvited } from './invites';
import { renderActivationEmail } from './emailTemplates';
import { sendEmail } from './resend';
import type { AccountType, Lang } from './db/types';

// PLAN_PHASE16.md §6.6's rate-limit table, verbatim — one exported constant
// so these numbers are tunable without hunting through the flow below.
export const SIGNUP_RATE_LIMITS = {
  signup_email: { windowSeconds: 24 * 60 * 60, max: 3 },
  signup_ip: { windowSeconds: 60 * 60, max: 5 },
  signup_global: { windowSeconds: 60 * 60, max: 100 },
} as const;

const TOKEN_TTL_MS = 24 * 60 * 60 * 1000;

/**
 * The CAPTCHA seam (§6.6 / §0.6 Q12: "a seam, not a decision"). Returns
 * `true` (human) immediately when `SIGNUP_CAPTCHA_PROVIDER` is unset —
 * which is every deployment today, Q12 is unanswered. `app/(auth)/signup/
 * SignupForm.tsx` only renders a widget (and therefore only ever produces a
 * non-null `token`) when a sitekey is configured, so a real request has
 * `token: null` here on every environment that exists right now.
 *
 * If `SIGNUP_CAPTCHA_PROVIDER` is ever set without a matching verifier
 * being implemented in this function, failing OPEN would make the env var
 * silently do nothing (worse than not having it), and failing CLOSED would
 * brick every signup the moment it's set. Neither is right — this logs
 * loudly and rejects, so the misconfiguration is visible instead of either
 * silently inert or silently catastrophic.
 */
// `token` is part of this seam's permanent public signature (§6.6/Q12: "a
// seam, not a decision") even though nothing verifies it until a provider
// is actually wired up.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export async function verifyHumanChallenge(token: string | null): Promise<boolean> {
  const provider = process.env.SIGNUP_CAPTCHA_PROVIDER;
  if (!provider) return true;
  console.error(`verifyHumanChallenge: SIGNUP_CAPTCHA_PROVIDER=${provider} is set, but no verifier is implemented for it yet.`);
  return false;
}

function sha256Hex(value: string): string {
  return crypto.createHash('sha256').update(value).digest('hex');
}

/**
 * sha256(ip + SIGNUP_IP_SALT) — never the raw IP, matching `vrm.
 * signup_requests.ip_hash`'s own column comment (§3.7). `SIGNUP_IP_SALT`
 * missing entirely (local dev without it set) degrades to an unsalted hash
 * rather than throwing — still never a raw IP at rest, just a weaker one,
 * which is the right trade for "don't crash local dev over a rate-limit
 * salt."
 */
function hashIp(ip: string): string {
  const salt = process.env.SIGNUP_IP_SALT ?? '';
  return sha256Hex(`${ip}${salt}`);
}

/**
 * `x-forwarded-for`'s first hop is the originating client on every
 * deployment shape this app runs behind (Vercel, and any standard reverse
 * proxy) — there is no `request.ip` here because this is called from a
 * Server Action, which has no `NextRequest` object, only `next/headers`.
 * `user_agent` is truncated to 200 chars per §6.6's own length cap.
 */
async function clientMeta(): Promise<{ ipHash: string | null; userAgent: string | null }> {
  const h = await headers();
  const forwardedFor = h.get('x-forwarded-for');
  const ip = forwardedFor ? forwardedFor.split(',')[0]?.trim() : (h.get('x-real-ip') ?? null);
  const ua = h.get('user-agent');
  return {
    ipHash: ip ? hashIp(ip) : null,
    userAgent: ua ? ua.slice(0, 200) : null,
  };
}

async function sendVerificationEmail(email: string, token: string): Promise<void> {
  const url = new URL('/signup/verify', SITE_URL());
  url.searchParams.set('token', token);
  const html = renderActivationEmail({
    heading: 'Confirm your email',
    intro: 'Click the button below to verify your email and finish setting up your VRM Monitor account.',
    ctaLabel: 'Verify email',
    ctaUrl: url.toString(),
    footerNote: "This link is single-use and expires in 24 hours. If you didn't try to sign up, you can safely ignore this email.",
  });
  try {
    await sendEmail({ to: email, subject: 'Verify your email — VRM Monitor', html });
  } catch (err) {
    // Swallowed on purpose, same rule as `sendPasswordReset()` — the
    // caller (`submitSignup`) has already committed to returning the
    // neutral state regardless (§5.5 Step 1 point 4: "including when
    // Resend threw"). Logged so a sustained Resend outage is still visible.
    console.error('submitSignup: verification email failed to send', err);
  }
}

/**
 * §5.5 Step 1's "you already have an account" branch — a `renderActivationEmail()`
 * call with sign-in copy and a link to `/login`, never a new `vrm.
 * signup_requests` row. The single most important non-enumeration branch in
 * the flow (see this module's own header comment): a stranger probing
 * addresses gets the identical `{submitted:true}` either way, and the real
 * account holder gets a useful email if it was actually them.
 */
async function sendExistingAccountEmail(email: string): Promise<void> {
  const url = new URL('/login', SITE_URL());
  const html = renderActivationEmail({
    heading: 'You already have a VRM Monitor account',
    intro: `An account already exists for ${email}. Sign in below — or use "Forgot your password?" on that page if you don't remember it.`,
    ctaLabel: 'Sign in',
    ctaUrl: url.toString(),
    footerNote: "If you didn't just try to sign up, you can safely ignore this email — nothing changed on your account.",
  });
  try {
    await sendEmail({ to: email, subject: 'You already have a VRM Monitor account', html });
  } catch (err) {
    console.error('submitSignup: existing-account email failed to send', err);
  }
}

function SITE_URL(): string {
  // Deliberately re-read on every call rather than imported as a top-level
  // constant from `lib/site.ts` — this file is imported by Server Actions
  // AND the verify Route Handler, and `lib/site.ts`'s own module-level
  // constant is fine either way, but keeping the read local to this module
  // avoids a second import of a value only these two email builders need.
  return process.env.SITE_URL ?? 'https://monitor.paulyco.com';
}

export type SubmitSignupInput = {
  name: string;
  email: string;
  accountType: AccountType;
  planId: string | null;
  uiLanguage: Lang;
  /** The `website` honeypot field, exactly as submitted. */
  honeypot: string;
  captchaToken: string | null;
};

/**
 * The entire §5.5 Step 1 sequence, run to completion regardless of which
 * branch it takes. NEVER throws in a way the caller needs to catch —
 * `app/(auth)/signup/actions.ts` returns the identical `{submitted:true}`
 * whether this inserted a row, sent an email, hit a rate limit, or did
 * nothing at all (the honeypot case). Every rejection is logged
 * server-side (bucket + key, never the raw token/email in a way that
 * would violate §11) so a real attack is visible to Oscar even though it's
 * invisible to the visitor — exactly the trade §6.6 describes.
 */
export async function submitSignup(input: SubmitSignupInput): Promise<void> {
  // Honeypot first, before spending any rate-limit budget or doing any
  // work at all (§5.5 Step 1: "does the same neutral success and does
  // nothing at all").
  if (input.honeypot.trim() !== '') return;

  const email = input.email.trim().toLowerCase();
  if (!email) return;

  const { ipHash, userAgent } = await clientMeta();

  // §6.6's exact order: global, then per-IP, then per-email.
  const globalOk = await checkRateLimit(
    'signup_global',
    '',
    SIGNUP_RATE_LIMITS.signup_global.windowSeconds,
    SIGNUP_RATE_LIMITS.signup_global.max,
  );
  if (!globalOk) {
    console.warn('submitSignup: rejected by the signup_global rate limit');
    return;
  }

  if (ipHash) {
    const ipOk = await checkRateLimit('signup_ip', ipHash, SIGNUP_RATE_LIMITS.signup_ip.windowSeconds, SIGNUP_RATE_LIMITS.signup_ip.max);
    if (!ipOk) {
      console.warn('submitSignup: rejected by the signup_ip rate limit');
      return;
    }
  }

  const emailOk = await checkRateLimit(
    'signup_email',
    email,
    SIGNUP_RATE_LIMITS.signup_email.windowSeconds,
    SIGNUP_RATE_LIMITS.signup_email.max,
  );
  if (!emailOk) {
    console.warn('submitSignup: rejected by the signup_email rate limit');
    return;
  }

  const humanOk = await verifyHumanChallenge(input.captchaToken);
  if (!humanOk) return;

  try {
    // §5.5 Step 1 point 3 — `lower(email)` against `vrm.customers.
    // auth_email`, the ONLY thing this flow is allowed to learn about an
    // existing account before a token exists.
    const alreadyCustomer = await customerExistsByEmail(email);
    if (alreadyCustomer) {
      await sendExistingAccountEmail(email);
      return;
    }

    const token = crypto.randomBytes(32).toString('hex');
    const tokenHash = sha256Hex(token);
    const expiresAt = new Date(Date.now() + TOKEN_TTL_MS).toISOString();

    await insertSignupRequest({
      email,
      tokenHash,
      name: input.name.trim(),
      accountType: input.accountType,
      planId: input.planId,
      uiLanguage: input.uiLanguage,
      ipHash,
      userAgent,
      expiresAt,
    });

    // Never log `token` — it is the same class of single-use secret as an
    // emailed invite link (§11).
    await sendVerificationEmail(email, token);
  } catch (err) {
    console.error('submitSignup: unexpected failure', err);
  }
}

export type RedeemSignupResult = { ok: true; redirectUrl: string } | { ok: false };

/**
 * §5.5 Step 2, called from `app/(auth)/signup/verify/route.ts`. Returns a
 * RELATIVE redirect target (never an absolute URL, never logged by the
 * caller) carrying a real, single-use `token_hash` — see the route
 * handler's own comment for why that's an accepted, documented shape
 * rather than a leak (mirrors `lib/server/invites.ts:buildActivationUrl()`'s
 * existing invite-link pattern one step further).
 */
export async function redeemSignupToken(rawToken: string): Promise<RedeemSignupResult> {
  const tokenHash = sha256Hex(rawToken);

  // Atomic consume — §5.5 Step 2 / §6.6's "double-click" gate. Zero rows
  // (already used, expired, or never existed) all collapse to the same
  // `{ok:false}`, which the route handler turns into ONE friendly redirect,
  // not three different messages.
  const request = await consumeSignupRequest(tokenHash);
  if (!request) return { ok: false };

  let customer;
  try {
    customer = await createSelfServeCustomer({
      name: request.name,
      accountType: request.account_type,
      authEmail: request.email,
      uiLanguage: request.ui_language,
    });
  } catch (err) {
    console.error('redeemSignupToken: createSelfServeCustomer failed', err);
    return { ok: false };
  }

  // `excludeCustomerId` = the row just created — without it, this lookup
  // would find that brand-new row itself and every self-serve signup would
  // incorrectly roll back as "already linked elsewhere" (see `invites.ts:
  // createOrLinkAuthUser()`'s own comment on this exact parameter).
  const linkResult = await createOrLinkAuthUser(request.email, customer.id);
  if (!linkResult.ok) {
    // Should be unreachable — Step 1 already checked the email — but the
    // check and this insert aren't in one transaction, so it's reachable
    // by race. A half-created account is worse than a confusing redirect.
    await deleteSelfServeCustomer(customer.id).catch((err) => {
      console.error('redeemSignupToken: rollback delete failed after already_linked_elsewhere', err);
    });
    return { ok: false };
  }

  try {
    await stampInvited(customer.id, linkResult.userId, request.email);
  } catch (err) {
    console.error('redeemSignupToken: stampInvited failed', err);
    return { ok: false };
  }

  // Diagnostics + support only (§3.7) — never worth failing the signup
  // over if this write itself fails.
  await linkSignupRequestToCustomer(request.id, customer.id).catch((err) => {
    console.error('redeemSignupToken: linking signup_requests.customer_id failed (diagnostics only)', err);
  });

  const nextPath = request.plan_id ? `/app/billing?plan=${request.plan_id}` : '/app/billing';
  const params = new URLSearchParams({
    token_hash: linkResult.hashedToken,
    type: linkResult.linkType,
    next: nextPath,
  });
  return { ok: true, redirectUrl: `/activate?${params.toString()}` };
}
