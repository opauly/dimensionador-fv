import 'server-only';

// Generic, database-backed rate limiter (PLAN_PHASE16.md §3.8, §6.5, §6.6).
//
// Why database-backed and not an in-process counter: this app is deployed
// serverless, where "in-process" can mean "reset on the very next request" —
// an in-memory `Map` here would be close to useless as an abuse control.
// `vrm.rate_limits` + `vrm.increment_rate_limit()` (migration 025) give a
// single atomic upsert-and-return round trip instead, so a check-and-
// increment can never race across concurrent invocations.
//
// Deliberately a FIXED window, not a sliding one (§3.8: "do not build a
// token bucket") — `window_start` is `now()` truncated down to the window
// size. At this product's scale, letting through up to 2x the limit at a
// window boundary in the worst case is a fine trade for the simplicity.
//
// Two callers today, both described in §0.3: the signup flow (§6.6,
// `signup_email` / `signup_ip` / `signup_global` buckets) and the ONVO
// webhook receiver (§6.5, `onvo_webhook`). Neither is implemented here —
// this module only knows how to check-and-increment a named bucket.
import { getSupabaseAdmin } from '@/lib/server/supabase';

/**
 * Atomically increments the counter for `(bucket, key, <current window>)`
 * and reports whether the caller is still within `max` for this window.
 *
 * `windowSeconds` truncation uses UTC epoch seconds, so every caller within
 * the same window (regardless of which server/instance handled the
 * request) computes the identical `window_start` and therefore hits the
 * same row — that shared row, plus the RPC's single atomic upsert, is what
 * makes this correct across concurrent/serverless invocations.
 *
 * On a database error, this fails OPEN (returns `true`, i.e. "allowed") —
 * rate limiting here is an abuse control, not the authentication boundary
 * (that's the webhook secret check / the signup token, each fail-CLOSED on
 * their own terms). A transient Postgres hiccup should not itself become an
 * outage for legitimate traffic. The error is logged so a sustained failure
 * is still visible.
 */
export async function checkRateLimit(bucket: string, key: string, windowSeconds: number, max: number): Promise<boolean> {
  const windowStart = truncateToWindow(new Date(), windowSeconds);

  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .rpc('increment_rate_limit', {
      p_bucket: bucket,
      p_key: key,
      p_window_start: windowStart,
    });

  if (error) {
    console.error(`checkRateLimit: increment_rate_limit failed for bucket=${bucket}: ${error.message}`);
    return true;
  }

  const count = typeof data === 'number' ? data : Number(data);
  return count <= max;
}

function truncateToWindow(now: Date, windowSeconds: number): string {
  const epochSeconds = Math.floor(now.getTime() / 1000);
  const windowStartSeconds = epochSeconds - (epochSeconds % windowSeconds);
  return new Date(windowStartSeconds * 1000).toISOString();
}
