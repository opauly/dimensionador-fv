// `POST /api/admin/uploads/sign` — the admin-side counterpart of
// `app/api/uploads/sign` (PLAN_PHASE14.md §2 Step 7's `/admin/upload`).
// Same signed-upload-URL mechanics (§1.5), gated by `requireAdminForRoute()`
// instead of `requireCustomerForRoute()`, and takes a `customerId` in the
// body — the one legitimate place a caller other than the session itself
// gets to name whose Storage prefix an upload lands under, since the whole
// point of this route is uploading *on behalf of* a customer an admin
// chose.
import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireAdminForRoute } from '@/lib/server/auth';
import { getSupabaseAdmin } from '@/lib/server/supabase';
import { getCustomer } from '@/lib/server/db';
import { MAX_UPLOAD_BYTES } from '@/lib/uploadLimits';

const BUCKET = 'vrm-monitor';

const bodySchema = z.object({
  customerId: z.string().trim().min(1),
  filename: z.string().trim().min(1).max(255),
  sizeBytes: z.number().int().positive(),
});

export async function POST(request: Request) {
  const session = await requireAdminForRoute();
  if (session instanceof NextResponse) return session;

  const json = await request.json().catch(() => null);
  const parsed = bodySchema.safeParse(json);
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  // Confirms `customerId` names a real customer before ever signing a
  // path for it — same "must be real" contract the rest of this app
  // enforces before touching a cross-entity write.
  try {
    await getCustomer(parsed.data.customerId);
  } catch {
    return NextResponse.json({ error: 'no_such_customer' }, { status: 404 });
  }

  // Admin uploads have no ceiling in principle (§1.5's 50 MB cap exists to
  // protect the customer-facing surface's Storage cost, not because a
  // backfill couldn't fit) — but this route still enforces it rather than
  // silently diverging, since it shares the same Storage bucket/plan tier
  // (§0.4 Q2). Oscar's genuinely oversized backfills stay on
  // `pages/06_vrm_monitor.py`, which has no such ceiling at all
  // (PLAN_PHASE14.md §1.5) — this is for admin-assisted *customer* uploads,
  // not a backfill tool.
  if (parsed.data.sizeBytes > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ error: 'file_too_large', maxBytes: MAX_UPLOAD_BYTES }, { status: 413 });
  }
  if (!parsed.data.filename.toLowerCase().endsWith('.csv')) {
    return NextResponse.json({ error: 'not_a_csv' }, { status: 400 });
  }

  const path = `uploads/${parsed.data.customerId}/${randomUUID()}.csv`;
  const { data, error } = await getSupabaseAdmin().storage.from(BUCKET).createSignedUploadUrl(path);
  if (error || !data) {
    return NextResponse.json({ error: 'sign_failed' }, { status: 500 });
  }

  return NextResponse.json({ uploadUrl: data.signedUrl, path: data.path });
}
