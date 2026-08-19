// `POST /api/admin/pipeline/vrm-fleet/link` — proxies `vrm_api`'s
// `POST /v1/vrm-fleet/link` (PLAN_PHASE15.md §3.3 / §8 Step 4b). The admin
// gate lives HERE, not in `vrm_api` itself (that router only carries the
// same `require_pipeline_key` every `vrm_api` router already has — see
// `vrm_api/routers/vrm_fleet.py`'s own module docstring for why): a
// non-admin session never gets past `requireAdminForRoute()`'s first
// statement, the same pattern every existing `app/api/admin/pipeline/*`
// route already uses (`ingest/preview/route.ts` is this route's closest
// analogue).
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireAdminForRoute } from '@/lib/server/auth';
import { linkVrmFleetInstallation, toErrorResponse, type SiteFieldsIn } from '@/lib/server/pipeline';

// Same shape as `app/api/admin/pipeline/ingest/preview/route.ts`'s own
// `siteFieldsSchema` (restated, not shared, matching this codebase's own
// "mirrored in every layer" convention for `SiteFieldsIn` — see that
// model's own docstring in `vrm_api/schemas.py`). Bug-fix pass 2026-08-18,
// Bug 1: this is the field this route was previously missing entirely —
// `VrmFleetManager.tsx`'s link form only ever sent `siteNameOrId`, which is
// how an installation could get linked with `system_type` defaulting to
// 'hybrid' and no coordinates at all.
const siteFieldsSchema = z.object({
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

const bodySchema = z
  .object({
    vrmInstallationId: z.number().int().positive(),
    customerId: z.string().trim().min(1).optional(),
    newCustomerName: z.string().trim().min(1).optional(),
    siteNameOrId: z.string().trim().min(1),
    siteFields: siteFieldsSchema.optional(),
  })
  // Exactly one of customerId/newCustomerName — restated here (a 400 before
  // ever calling vrm_api) even though vrm_api's own VrmFleetLinkRequest
  // enforces the same rule server-side; see that router's own comment for
  // why the check lives in the route handler rather than a pydantic
  // validator, on ITS side — this is the equivalent belt-and-suspenders
  // check on OUR side.
  .refine((b) => Boolean(b.customerId) !== Boolean(b.newCustomerName), {
    message: 'Provide exactly one of customerId or newCustomerName.',
  });

export async function POST(request: Request) {
  const session = await requireAdminForRoute();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });
  const body = parsed.data;

  try {
    const result = await linkVrmFleetInstallation({
      vrm_installation_id: body.vrmInstallationId,
      customer_id: body.customerId,
      new_customer_name: body.newCustomerName,
      site_name_or_id: body.siteNameOrId,
      site_fields: body.siteFields as SiteFieldsIn | undefined,
    });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
