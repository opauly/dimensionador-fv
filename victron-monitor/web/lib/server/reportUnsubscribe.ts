import 'server-only';

// The "stop receiving this report" flow (PLAN_PHASE17.md §0.6 Q5, §8 Step
// 8) — deliberately NOT part of `lib/server/db/*`'s tenant-scoped choke
// point (that barrel's whole model is "a customerId the session proves");
// this is a THIRD kind of write path with no session at all, authorized
// only by possession of a correctly-signed link. `vrm_api/report_delivery.py:
// make_unsubscribe_token()` generates the token in Python, in the OTHER
// runtime, at send time; `verifyUnsubscribeToken()` here re-derives the
// same HMAC independently, from the SAME `REPORT_UNSUBSCRIBE_SECRET` value
// set in both `web/.env.local` and the repo-root `.env` — the identical
// cross-runtime-shared-secret shape `PIPELINE_API_KEY` already uses,
// restated for a one-way signature instead of a bearer token.
//
// The token embeds only `(site_id, email)` — nothing that grants any
// capability beyond "remove this one address from this one site's
// recipient list." It is not a login, it does not identify a
// `vrm.customers` row, and it cannot be replayed to do anything else.
import crypto from 'crypto';
import { getSupabaseAdmin } from '@/lib/server/supabase';

export type UnsubscribeTarget = { siteId: string; email: string };

function base64UrlDecode(input: string): Buffer | null {
  try {
    const padded = input + '='.repeat((4 - (input.length % 4)) % 4);
    return Buffer.from(padded.replace(/-/g, '+').replace(/_/g, '/'), 'base64');
  } catch {
    return null;
  }
}

/**
 * Re-derives the same HMAC `vrm_api/report_delivery.py:make_unsubscribe_token()`
 * computed at send time and compares in constant time
 * (`crypto.timingSafeEqual`) — a timing side-channel on this comparison
 * would let an attacker recover a valid signature one byte at a time, the
 * same reasoning every other signature-verification path in this repo
 * already follows. Returns `null` for anything malformed, expired-looking
 * (there is no expiry — an unsubscribe link staying valid forever is
 * correct: the whole point is a recipient can always stop future reports),
 * or signed with a different secret (including "no secret configured on
 * this deploy," which must fail closed, never open).
 */
export function verifyUnsubscribeToken(token: string): UnsubscribeTarget | null {
  const secret = process.env.REPORT_UNSUBSCRIBE_SECRET;
  if (!secret) return null;

  const decoded = base64UrlDecode(token);
  if (!decoded) return null;
  const parts = decoded.toString('utf8').split(':');
  if (parts.length !== 3) return null;
  const [siteId, email, signature] = parts;
  if (!siteId || !email || !signature) return null;

  const expected = crypto.createHmac('sha256', secret).update(`${siteId}:${email}`).digest('hex');
  const expectedBuf = Buffer.from(expected, 'utf8');
  const signatureBuf = Buffer.from(signature, 'utf8');
  if (expectedBuf.length !== signatureBuf.length || !crypto.timingSafeEqual(expectedBuf, signatureBuf)) {
    return null;
  }
  return { siteId, email };
}

/**
 * Removes `email` from `siteId`'s `report_recipients`, if present.
 * Idempotent and silent about "wasn't there" (already unsubscribed, or the
 * site/customer no longer exists) — a second click of the same link, or a
 * stale link for a since-deleted site, is not an error the visitor needs
 * to see, only a confirmation either way.
 */
export async function removeReportRecipient(siteId: string, email: string): Promise<void> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .select('report_recipients')
    .eq('site_id', siteId)
    .maybeSingle();
  if (error) throw error;
  if (!data) return;

  const current = (data.report_recipients as string[] | null) ?? [];
  const lowered = email.toLowerCase();
  const next = current.filter((e) => e.toLowerCase() !== lowered);
  if (next.length === current.length) return;

  const { error: updateError } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .update({ report_recipients: next })
    .eq('site_id', siteId);
  if (updateError) throw updateError;
}
