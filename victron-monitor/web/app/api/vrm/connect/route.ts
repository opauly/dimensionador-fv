// `POST /api/vrm/connect` — PLAN_PHASE15.md §3.1 step 3, "connect": takes
// the token plus the customer's mapping decisions from step 2 and, only
// now, writes anything. Mirrors `app/api/pipeline/ingest/preview/route.ts`'s
// own `siteSelection: 'existing' | 'new'` discriminated union PER
// INSTALLATION being mapped — an installation the customer left at "ignore"
// simply never appears in `body.mappings` at all (no explicit "ignore"
// value to model, matching `vrm_api/schemas.py:VrmLinkMapping`'s own
// docstring).
//
// `requireCustomerForRoute()` first statement; `customer_id` is always
// `session.customerId`. For an "existing site" mapping, `assertOwnsSite()`
// is re-checked here even though the dropdown that produced `siteId` was
// already filtered to this customer's own sites (PLAN_PHASE14.md §1.12 rule
// 3 — "the dropdown is UI; the guard is the control") — the same reasoning
// `ingest/preview/route.ts` already documents for the identical shape. For
// a "new site" mapping, `canAddSite()` is re-checked per new site for the
// same reason `addSiteAction()`/`ingest/preview/route.ts` already re-check
// it: the render-time check that hid "create a new site" is UX, not the
// control.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { assertOwnsSite, canAddSite, NotAuthorized } from '@/lib/server/db';
import { vrmLinkConnect, toErrorResponse, type SiteFieldsIn, type VrmLinkMapping } from '@/lib/server/pipeline';

// Same shape as `ingest/preview/route.ts`'s own `siteFieldsSchema` —
// restated, not shared, matching this codebase's "mirrored in every layer"
// convention for `SiteFieldsIn` (see that model's own docstring in
// `vrm_api/schemas.py`).
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

// A discriminated union per mapping — same reasoning as
// `ingest/preview/route.ts`'s own `bodySchema`: Zod's excess-property
// checking guarantees a caller can't send both `siteId` and `newSiteName`
// for one installation and have one silently ignored.
const mappingSchema = z.discriminatedUnion('siteSelection', [
  z.object({
    siteSelection: z.literal('existing'),
    vrmInstallationId: z.number().int().positive(),
    siteId: z.string().trim().min(1),
    siteFields: siteFieldsSchema.optional(),
  }),
  z.object({
    siteSelection: z.literal('new'),
    vrmInstallationId: z.number().int().positive(),
    newSiteName: z.string().trim().min(1),
    siteFields: siteFieldsSchema.optional(),
  }),
]);

const bodySchema = z.object({
  token: z.string().trim().min(1),
  mappings: z.array(mappingSchema),
});

export async function POST(request: Request) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });
  const body = parsed.data;

  const mappings: VrmLinkMapping[] = [];
  for (const mapping of body.mappings) {
    if (mapping.siteSelection === 'existing') {
      try {
        await assertOwnsSite(session.customerId, mapping.siteId);
      } catch (err) {
        if (err instanceof NotAuthorized) return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
        throw err;
      }
      mappings.push({
        vrm_installation_id: mapping.vrmInstallationId,
        site_name_or_id: mapping.siteId,
        site_fields: mapping.siteFields as SiteFieldsIn | undefined,
      });
    } else {
      const gate = await canAddSite(session.customerId);
      if (!gate.ok) return NextResponse.json({ error: gate.reason }, { status: 403 });
      mappings.push({
        vrm_installation_id: mapping.vrmInstallationId,
        site_name_or_id: mapping.newSiteName,
        site_fields: mapping.siteFields as SiteFieldsIn | undefined,
      });
    }
  }

  try {
    const result = await vrmLinkConnect({ customer_id: session.customerId, token: body.token, mappings });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
