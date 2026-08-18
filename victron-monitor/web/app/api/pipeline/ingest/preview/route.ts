// `POST /api/pipeline/ingest/preview` — kicks off the "parse, don't write
// yet" leg of the two-step upload flow (PLAN_PHASE14.md §1.6, §2 Step 6),
// mirroring `pages/06_vrm_monitor.py:tab_upload()`'s "never write on the
// first click" rule one process over. Thin on purpose: `vrm_api` does the
// actual parsing; everything here is tenancy plumbing plus request-shape
// validation.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { assertOwnsSite, canAddSite, NotAuthorized } from '@/lib/server/db';
import { ingestPreview, toErrorResponse, type SiteFieldsIn } from '@/lib/server/pipeline';

const siteFieldsSchema = z.object({
  display_name: z.string().trim().min(1).optional(),
  pv_kwp: z.number().nullable().optional(),
  battery_nominal_kwh: z.number().nullable().optional(),
  battery_dod_pct: z.number().nullable().optional(),
  system_type: z.enum(['grid_zero', 'off_grid', 'hybrid']).optional(),
  report_language: z.enum(['es', 'en']).optional(),
  location: z.string().nullable().optional(),
  timezone: z.string().optional(),
  latitude: z.number().nullable().optional(),
  longitude: z.number().nullable().optional(),
  country: z.string().optional(),
  savings_rate: z.number().nullable().optional(),
  savings_currency: z.string().nullable().optional(),
  exports_to_grid: z.boolean().optional(),
});

// A discriminated union, not a single optional `siteId` — Zod's own excess-
// property checking then guarantees a caller can't send both `siteId` and
// `newSiteName` and have one silently ignored; the shape itself states
// which of "reuse mine" and "create one, if I'm still under my limit" was
// asked for.
const bodySchema = z.discriminatedUnion('siteSelection', [
  z.object({
    siteSelection: z.literal('existing'),
    siteId: z.string().trim().min(1),
    storagePath: z.string().trim().min(1),
    // The browser's original filename, e.g. "997979_0_Emtec_log_....csv" —
    // `storagePath` itself is always `uploads/{customerId}/{uuid}.csv` by
    // this point (`app/api/uploads/sign`), which would otherwise silently
    // blank out `installation_id()` (vrm_api parses it from the filename)
    // and the `ingestion_log.filename` audit column.
    filename: z.string().trim().min(1),
    siteFields: siteFieldsSchema,
  }),
  z.object({
    siteSelection: z.literal('new'),
    newSiteName: z.string().trim().min(1),
    storagePath: z.string().trim().min(1),
    filename: z.string().trim().min(1),
    siteFields: siteFieldsSchema,
  }),
]);

export async function POST(request: Request) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const json = await request.json().catch(() => null);
  const parsed = bodySchema.safeParse(json);
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });
  const body = parsed.data;

  // `storagePath` must live under this customer's own uploads prefix.
  // `app/api/uploads/sign` only ever hands out `uploads/{customerId}/...`
  // paths, but nothing stops a tampered request from naming a path it never
  // received — vrm_api has no way to know whose object a path names, so
  // this is the one place that fact gets enforced before vrm_api is ever
  // asked to download it.
  if (!body.storagePath.startsWith(`uploads/${session.customerId}/`)) {
    return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
  }

  let siteNameOrId: string;
  try {
    if (body.siteSelection === 'existing') {
      // The dropdown that produced `siteId` was already filtered to this
      // customer's own sites — this check is the control, not the dropdown
      // (PLAN_PHASE14.md §1.12 rule 3). `vrm_api/routers/ingest.py` re-derives
      // the same fact independently via `tenancy.find_customer_site()`.
      await assertOwnsSite(session.customerId, body.siteId);
      siteNameOrId = body.siteId;
    } else {
      // Re-checked here even though the page only renders "New site…" when
      // `canAddSite()` already said yes — same reasoning as
      // `app/(portal)/app/sites/actions.ts:addSiteAction()`: the render-time
      // check is UX, this is the control (§1.2 rule 4).
      const gate = await canAddSite(session.customerId);
      if (!gate.ok) return NextResponse.json({ error: gate.reason }, { status: 403 });
      siteNameOrId = body.newSiteName;
    }
  } catch (err) {
    if (err instanceof NotAuthorized) return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
    throw err;
  }

  try {
    const result = await ingestPreview({
      customer_id: session.customerId,
      site_name_or_id: siteNameOrId,
      storage_path: body.storagePath,
      filename: body.filename,
      site_fields: body.siteFields as SiteFieldsIn,
    });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
