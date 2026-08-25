// `POST /api/branding/logo-sign` — the branding-logo twin of
// `app/api/uploads/sign/route.ts` (PLAN_PHASE17.md §4.4/§4.5/§8 Step 5).
// Same reason to exist: the browser PUTs the logo bytes straight to
// Supabase Storage via a signed URL, so this route's own body is a tiny
// JSON request/response, never the file itself.
//
// Real image validation (Pillow, verifying actual bytes rather than a
// declared content-type) can only happen where the bytes are actually
// read — `vrm_api/branding.py:resolve_branding()`'s `_resolve_logo_b64()`,
// at REPORT-RENDER time (Step 4, already built and tested) — because a
// direct browser->Storage upload never passes through this app's own
// server at all. This route's own checks (size, extension) are a cheap,
// honest-mistake pre-filter, not the security boundary: a deliberately
// mislabeled file (real SVG bytes saved as `.png`) would pass this route
// and upload fine, but still gets rejected the first time a report is
// generated, by the real Pillow check — the same outcome as any other
// bad logo, just caught one step later than an honest oversized-PNG
// mistake is.
import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { getBrandingAccess, getCustomer } from '@/lib/server/db';
import { getSupabaseAdmin } from '@/lib/server/supabase';
import { LOGO_ALLOWED_EXTENSIONS, LOGO_MAX_BYTES } from '@/lib/uploadLimits';

const BUCKET = 'vrm-monitor';

const bodySchema = z.object({
  filename: z.string().trim().min(1).max(255),
  sizeBytes: z.number().int().positive(),
});

export async function POST(request: Request) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const json = await request.json().catch(() => null);
  const parsed = bodySchema.safeParse(json);
  if (!parsed.success) {
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 });
  }

  // The same gate `updateBranding()` re-checks before writing anything —
  // a Starter customer's browser bypassing the hidden-editor UI still
  // can't get so much as a place to upload to (PLAN_PHASE17.md §4.5's
  // "hiding the editor is UX, never the control", applied at every layer,
  // not just the final write).
  const customer = await getCustomer(session.customerId);
  const allowed = await getBrandingAccess(customer);
  if (!allowed) {
    return NextResponse.json({ error: 'branding_not_allowed' }, { status: 403 });
  }

  if (parsed.data.sizeBytes > LOGO_MAX_BYTES) {
    return NextResponse.json({ error: 'file_too_large', maxBytes: LOGO_MAX_BYTES }, { status: 413 });
  }
  const lowerName = parsed.data.filename.toLowerCase();
  if (!LOGO_ALLOWED_EXTENSIONS.some((ext) => lowerName.endsWith(ext))) {
    return NextResponse.json({ error: 'unsupported_file_type' }, { status: 400 });
  }

  const ext = lowerName.endsWith('.jpeg') || lowerName.endsWith('.jpg') ? 'jpg' : 'png';
  // `branding/{customer_id}/{uuid}.<ext>` — same UUID-per-upload shape
  // `app/api/uploads/sign/route.ts` already uses for CSVs, not a fixed
  // `logo.<ext>` path. `lib/uploadClient.ts:uploadFileToSignedUrl()` (reused
  // here unchanged) sends a hardcoded `x-upsert: false` on the PUT itself,
  // and Supabase Storage's own upsert-via-signed-token behavior is
  // deliberately NOT relied on here to avoid depending on how that header
  // and the token's own upsert flag interact — a fresh UUID path can never
  // collide, full stop. Cost: the customer's previous logo object becomes
  // orphaned in Storage on a re-upload, the same accepted class of debt
  // `vrm_api/storage.py:sweep_orphan_uploads()` already exists for on the
  // CSV side — not swept here, since branding logos are far lower volume
  // than CSV uploads and this is a fast-follow, not a correctness gap.
  const path = `branding/${session.customerId}/${randomUUID()}.${ext}`;

  const { data, error } = await getSupabaseAdmin().storage.from(BUCKET).createSignedUploadUrl(path);
  if (error || !data) {
    return NextResponse.json({ error: 'sign_failed' }, { status: 500 });
  }

  return NextResponse.json({ uploadUrl: data.signedUrl, path: data.path });
}
