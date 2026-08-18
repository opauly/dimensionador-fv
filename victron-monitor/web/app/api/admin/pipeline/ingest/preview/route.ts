// `POST /api/admin/pipeline/ingest/preview` — admin-side counterpart of
// `app/api/pipeline/ingest/preview` (PLAN_PHASE14.md §2 Step 7). The one
// real difference from the customer route: `customerId` comes from the
// request body (an admin-chosen customer), not the session — this is the
// one legitimate place that's true, per `/admin/upload`'s own reason for
// existing (§Step 7: "the one place `upsert_customer`-equivalent behavior
// belongs, and only reachable from an admin session"). In practice this
// route never triggers `upsert_customer` either (`vrm_api/routers/
// ingest.py` still only ever `upsert_site`s under an *existing* customer —
// see that router's own TODO comment) because `/admin/customers` is always
// what actually creates the tenant; this route only ever uploads for one
// that's already there.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireAdminForRoute } from '@/lib/server/auth';
import { getCustomer, canAddSite, assertOwnsSite, NotAuthorized } from '@/lib/server/db';
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

const bodySchema = z.discriminatedUnion('siteSelection', [
  z.object({
    siteSelection: z.literal('existing'),
    customerId: z.string().trim().min(1),
    siteId: z.string().trim().min(1),
    storagePath: z.string().trim().min(1),
    filename: z.string().trim().min(1),
    siteFields: siteFieldsSchema,
  }),
  z.object({
    siteSelection: z.literal('new'),
    customerId: z.string().trim().min(1),
    newSiteName: z.string().trim().min(1),
    storagePath: z.string().trim().min(1),
    filename: z.string().trim().min(1),
    siteFields: siteFieldsSchema,
  }),
]);

export async function POST(request: Request) {
  const session = await requireAdminForRoute();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });
  const body = parsed.data;

  if (!body.storagePath.startsWith(`uploads/${body.customerId}/`)) {
    return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
  }

  try {
    await getCustomer(body.customerId);
  } catch {
    return NextResponse.json({ error: 'no_such_customer' }, { status: 404 });
  }

  let siteNameOrId: string;
  try {
    if (body.siteSelection === 'existing') {
      await assertOwnsSite(body.customerId, body.siteId);
      siteNameOrId = body.siteId;
    } else {
      const gate = await canAddSite(body.customerId);
      if (!gate.ok) return NextResponse.json({ error: gate.reason }, { status: 403 });
      siteNameOrId = body.newSiteName;
    }
  } catch (err) {
    if (err instanceof NotAuthorized) return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
    throw err;
  }

  try {
    const result = await ingestPreview({
      customer_id: body.customerId,
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
