import 'server-only';

// A lightweight Resend HTTP client — the TypeScript-side counterpart of
// `victron/mailer.py` (PLAN_PHASE14.md §1.9, §2 Step 7).
//
// ── Why this exists instead of `lib/server/invites.ts` calling `victron/mailer.py` ──
// `victron-monitor/web` (this process) and `vrm_api`/`victron/*` (a
// separate Python process, possibly on a different host in production —
// Render vs. Vercel, §1.4) share no interpreter and no import path.
// PLAN_PHASE14.md §2 Step 7 lists both `victron/mailer.py` *and*
// `lib/server/invites.ts` as build items with `invites.ts` described as
// "render + send," which reads as two candidate designs: (a) `invites.ts`
// calls a new `vrm_api` endpoint that uses `victron/mailer.py` internally,
// or (b) `invites.ts` has its own Resend client and `victron/mailer.py`
// exists for Phase 12 (scheduled report emails, Python-side) to import
// later, unchanged. This repo takes (b): sending a transactional email is
// one HTTP POST — round-tripping it through `vrm_api` would hand that
// service a responsibility §1.3 deliberately keeps out of its scope
// ("Narrow verbs only... ingest/report/meta"), for no isolation benefit
// (this module holds the Resend key the same way `victron/mailer.py` holds
// it: a secret read from `server-only` code, never near a browser).
//
// This is deliberately generic — no invite-specific copy or `vrm.customers`
// writes here, mirroring `victron/mailer.py`'s own "no invite-specific
// logic in this module" rule one process over. `lib/server/invites.ts` owns
// what gets sent and why; this module only knows how to hand Resend a
// `{to, subject, html}` and turn a non-2xx response into a typed error.
const RESEND_API_URL = 'https://api.resend.com/emails';

export class MailerError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MailerError';
  }
}

export type SendEmailInput = {
  to: string;
  subject: string;
  html: string;
  from?: string;
  replyTo?: string;
};

/** Sends one email via Resend. Returns Resend's message id on success. */
export async function sendEmail({ to, subject, html, from, replyTo }: SendEmailInput): Promise<string> {
  const apiKey = process.env.RESEND_API_KEY;
  const sender = from ?? process.env.PORTAL_FROM_EMAIL;
  if (!apiKey) throw new MailerError('RESEND_API_KEY is not set.');
  if (!sender) throw new MailerError('No sender address: pass from or set PORTAL_FROM_EMAIL.');

  let res: Response;
  try {
    res = await fetch(RESEND_API_URL, {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from: sender,
        to: [to],
        subject,
        html,
        ...(replyTo ? { reply_to: replyTo } : {}),
      }),
      // Never cached — every call here is a real side effect (an email
      // actually being sent), the opposite of what Next's fetch cache is
      // for.
      cache: 'no-store',
    });
  } catch {
    // Never let the raw fetch error (can carry request internals) surface
    // to a caller that might log it or, worse, put it in a response —
    // PLAN_PHASE14.md §3's "never log ... a full email-send payload,"
    // applied to the failure path too.
    throw new MailerError('Could not reach Resend.');
  }

  if (!res.ok) {
    // Body text logged server-side only (this module never runs anywhere
    // a browser can see its return value directly) — never included in
    // what a caller further up might surface to an admin's screen.
    const bodyText = await res.text().catch(() => '');
    // Server-side diagnostic only — no token/password/payload in it beyond
    // Resend's own rejection reason, and this never runs anywhere a
    // browser can see it (PLAN_PHASE14.md §3: never log a token_hash or a
    // full email-send payload; a rejection reason isn't either).
    console.error(`Resend rejected an email to ${to}: ${res.status} ${bodyText}`);
    throw new MailerError(`Resend rejected the email (${res.status}).`);
  }

  const data = (await res.json()) as { id?: string };
  return data.id ?? '';
}
