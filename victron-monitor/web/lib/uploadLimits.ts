// Client-facing upload size cap (PLAN_PHASE14.md §0.4 Q2, §1.5, §2 Step 6).
//
// Oscar never explicitly answered "Free or Pro Supabase plan?" (§0.4 Q2) —
// the plan's own documented working assumption is Free, which caps a single
// Storage upload at 50 MB. That number is *this repo's* assumption about
// the Supabase project's plan tier, not something `vrm_api` or Supabase
// itself will confirm for us, so it lives here as one constant rather than
// being re-derived. A real 7-day VRM export is ~12 MB and comfortably fits;
// Oscar's own multi-month backfills (~140 MB) do not, and stay on
// `pages/06_vrm_monitor.py`, which has no such ceiling (§1.5).
//
// Not `lib/server/` — both the sign route (server) and UploadManager (the
// client component that rejects an oversized file before even asking the
// server for a signed URL) need the same number, and duplicating it would
// be exactly the kind of drift §1.11 calls out for `MAX_CUSTOM_RANGE_DAYS`.
// If the Supabase project ever moves to a paid plan with a raised global
// cap, this is the one line to revisit.
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

export function formatBytes(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return `${mb % 1 === 0 ? mb.toFixed(0) : mb.toFixed(1)} MB`;
}
