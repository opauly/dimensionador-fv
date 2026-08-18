// `POST /api/uploads/sign` — the only step of the upload path that ever
// touches Vercel with anything but a tiny JSON body (PLAN_PHASE14.md §1.5,
// §2 Step 6). The CSV's actual bytes never come through this route or any
// other Next.js server code: Vercel caps a function's request body at
// 4.5 MB (infrastructure-level, not configurable — PLAN_PHASE14.md §0.1),
// which a 12 MB weekly VRM export already blows past. So this route's only
// job is to hand the browser a Supabase Storage *signed upload URL* — the
// browser then PUTs the file straight to Storage
// (`app/(portal)/app/upload/uploadClient.ts`), and nothing this app's own
// server does ever sees those bytes.
import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { getSupabaseAdmin } from '@/lib/server/supabase';
import { MAX_UPLOAD_BYTES } from '@/lib/uploadLimits';

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

  // §1.5 / §0.4 Q2: the Supabase Free plan's Storage cap (50 MB) is this
  // repo's working assumption — Oscar never explicitly confirmed the plan
  // tier, and the plan document says to state that assumption rather than
  // silently build against it (PLAN_PHASE14.md §2 Step 6). Checked here,
  // BEFORE `createSignedUploadUrl()` is ever called, so an oversized file
  // never gets so much as a place to upload to — this is what stops a
  // DevTools request that skips UploadManager's own client-side check.
  if (parsed.data.sizeBytes > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ error: 'file_too_large', maxBytes: MAX_UPLOAD_BYTES }, { status: 413 });
  }
  if (!parsed.data.filename.toLowerCase().endsWith('.csv')) {
    return NextResponse.json({ error: 'not_a_csv' }, { status: 400 });
  }

  // `uploads/{customerId}/{uuid}.csv` (PLAN_PHASE14.md §1.5 point 1) — the
  // customer-id segment is what lets every later step (the ingest/preview
  // route, `vrm_api/storage.py`'s orphan sweep) reason about whose object
  // this is from the path alone, and it comes from the session, never from
  // the request body a client could set `filename`/a path prefix through.
  const path = `uploads/${session.customerId}/${randomUUID()}.csv`;

  const { data, error } = await getSupabaseAdmin().storage.from(BUCKET).createSignedUploadUrl(path);
  if (error || !data) {
    return NextResponse.json({ error: 'sign_failed' }, { status: 500 });
  }

  // The signed URL only — never a Supabase key of any kind (PLAN_PHASE14.md
  // §2 Step 6's own instruction for this route). The token embedded in
  // `signedUrl` is itself the only credential the browser gets: it's scoped
  // to this one object, expires in 2 hours (Supabase's own limit on
  // `createSignedUploadUrl`), and grants nothing beyond "write this one
  // path once" — a world away from the secret key this route's own call
  // just used server-side.
  return NextResponse.json({ uploadUrl: data.signedUrl, path: data.path });
}
