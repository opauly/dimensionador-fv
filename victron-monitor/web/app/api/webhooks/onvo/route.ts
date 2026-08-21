// `POST /api/webhooks/onvo` — the ONLY place ONVO's shared-secret webhook
// lands (PLAN_PHASE16.md §4.1, §6.5). No session, no
// `requireCustomerForRoute()` — this is machine-to-machine, authenticated
// by nothing but `X-Webhook-Secret`.
//
// This route contains NO billing logic: parse, verify secret, rate-limit,
// forward-or-record, respond. If it ever grows something that looks like a
// business rule, that rule belongs in `vrm_api` instead — that's the whole
// point of §4.1's split.
//
// Two branches, deliberately asymmetric:
//   - Bad/missing/misconfigured secret: recorded HERE, directly, via
//     `getSupabaseAdmin()` — `vrm_api` is never called on this path. This is
//     a documented exception to "Next.js never writes `vrm.*` directly"
//     (most of the app goes through `lib/server/pipeline.ts` instead): a
//     rejected delivery must be visible even if `vrm_api` or the pipeline
//     key is broken, and a forged/leaked-secret flood must never reach
//     `vrm_api` or ONVO's own API at all
//     (`vrm_api/schemas.py:BillingWebhookEventRequest`'s own docstring
//     states this split explicitly — "a request whose secret check fails
//     must never reach this endpoint at all").
//   - Good secret: rate-limited (DB-backed, §3.8/§6.5 — an in-process
//     counter would be near-useless on a serverless deployment), then
//     forwarded to `vrm_api` unchanged via
//     `lib/server/pipeline.ts:billingWebhookEvent()`, which does the actual
//     resolution + reconcile (§4.2, §4.3).
//
// Response policy (§6.5): "the response body is `{"ok":true}` or nothing.
// Never echo the payload, never include an error message, never confirm
// whether the event resolved to a known customer" — this is why the
// rejected-secret and rate-limited branches below return an EMPTY body,
// never a `{error: ...}` shape a leaked-secret holder (or anyone probing
// this endpoint) could use as an oracle.
import crypto from 'node:crypto';
import { NextResponse } from 'next/server';
import { billingWebhookEvent, toErrorResponse } from '@/lib/server/pipeline';
import { checkRateLimit } from '@/lib/server/ratelimit';
import { getSupabaseAdmin } from '@/lib/server/supabase';

// Generous on purpose (§6.5, §6.6): this endpoint can legitimately receive
// a burst of real events from ONVO. The actual thing this limit protects
// against is "a forged/leaked-secret flood fills `vrm.billing_events` or
// makes us hammer ONVO's own API with our secret key on their behalf" — not
// throttling normal delivery traffic. One shared/global bucket (`key: ''`):
// nothing about a webhook delivery identifies a distinct caller more
// specifically than "holds the shared secret."
const RATE_LIMIT_WINDOW_SECONDS = 60;
const RATE_LIMIT_MAX = 120;

function sha256(value: string): Buffer {
  return crypto.createHash('sha256').update(value, 'utf8').digest();
}

/**
 * Constant-time secret comparison, mirroring `vrm_api/deps.py`'s exact
 * reasoning (§6.5). `crypto.timingSafeEqual` THROWS on buffers of
 * differing length, and that throw is itself a length-leak side channel —
 * comparing the raw strings/buffers directly is wrong for exactly the
 * reason `hmac.compare_digest` exists on the Python side. SHA-256ing both
 * inputs first always produces two 32-byte digests, so `timingSafeEqual`
 * never throws and never leaks how many leading characters of a guessed
 * secret were right.
 */
function secretsMatch(provided: string, expected: string): boolean {
  return crypto.timingSafeEqual(sha256(provided), sha256(expected));
}

export async function POST(request: Request) {
  const rawBody = await request.text();
  let payload: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(rawBody);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) payload = parsed as Record<string, unknown>;
  } catch {
    // Not JSON, or an empty body — `payload` stays `{}`. §4.2's resolution
    // ladder already tolerates a payload with no matching id (the event is
    // recorded as 'ignored', never dropped); a malformed body is no
    // different from that case once it reaches vrm_api.
  }

  const expectedSecret = process.env.ONVO_WEBHOOK_SECRET ?? '';
  const providedSecret = request.headers.get('x-webhook-secret') ?? '';

  // An empty/unset ONVO_WEBHOOK_SECRET must fail CLOSED — mirrors
  // `vrm_api/deps.py`'s own guard against `compare_digest("", "")` being
  // `true`. Without the `expectedSecret.length > 0` check, an
  // unconfigured secret would silently accept every request instead of
  // hard-failing every one of them.
  const secretOk = expectedSecret.length > 0 && secretsMatch(providedSecret, expectedSecret);

  if (!secretOk) {
    // §6.5 / `BillingWebhookEventRequest`'s own docstring: a rejected
    // secret never reaches `vrm_api` — recorded directly here instead, so
    // an attempted forgery is durably visible even if the pipeline key or
    // vrm_api itself is broken.
    const { error } = await getSupabaseAdmin()
      .schema('vrm')
      .from('billing_events')
      .insert({ secret_ok: false, payload, status: 'received' });
    if (error) {
      // §4.1's response policy, one layer up: "could not even record it
      // (database down) -> 500. This is the one case where a failure in
      // their dashboard is genuinely informative." No error detail in the
      // body regardless (§6.5) — only the status differs from the normal
      // rejected-secret 401.
      console.error(`onvo webhook: failed to record a rejected-secret delivery: ${error.message}`);
      return new NextResponse(null, { status: 500 });
    }
    // Deliberately empty body: never confirm anything about the payload,
    // or whether it would have resolved to a known customer (§6.5).
    return new NextResponse(null, { status: 401 });
  }

  // Rate-limit only AFTER the secret check — a caller with no/wrong secret
  // already gets nothing but a bare 401 above, so there is no distinct
  // signal to protect on that path. DB-backed (§3.8) so the count is real
  // across serverless invocations, not reset per request.
  const allowed = await checkRateLimit('onvo_webhook', '', RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_MAX);
  if (!allowed) {
    // Not recorded anywhere on this path: §4.4's daily sweep
    // (`POST /v1/billing/reconcile-due`) covers exactly this case — "a
    // renewal that happened while nobody was looking and whose webhook
    // never arrived." The same freshness bound applies whether ONVO's own
    // delivery was lost, or a burst was throttled here.
    return new NextResponse(null, { status: 429 });
  }

  try {
    const result = await billingWebhookEvent({ secret_ok: true, payload });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
