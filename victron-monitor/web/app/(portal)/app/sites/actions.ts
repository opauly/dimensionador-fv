'use server';

import 'server-only';

// Server Actions for `app/(portal)/app/sites` (PLAN_PHASE14.md §2 Step 4).
// `requireCustomer()` is the first statement of every one of these — never
// inferred from the page having already called it (§3: "the first
// statement of every route handler, server action, and protected page").
// Every write goes through `lib/server/db/sites.ts`'s whitelist; nothing
// here ever spreads a raw `FormData`-derived object straight into a
// Supabase call.
import { revalidatePath } from 'next/cache';
import { z } from 'zod';
import { requireCustomer } from '@/lib/server/auth';
import { canAddSite, createSite, updateSite, type SiteUpdateFields } from '@/lib/server/db';
import { reverseGeocode } from '@/lib/server/geocode';
import { t } from '@/lib/i18n/strings';

// Zod parses the *shape* of what a <form> can possibly send (a string that
// should coerce to a number, one of a fixed set of enum values) — it does
// NOT decide which columns are writable. That's `sites.ts`'s
// `SITE_WHITELIST`, enforced again after this, independently, per
// PLAN_PHASE14.md §3's "Zod ... only checks the shape" framing (matching
// the Next.js docs' own warning about this same distinction).
const numberOrNull = z.preprocess((v) => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}, z.number().nullable());

const stringOrNull = z.preprocess((v) => (typeof v === 'string' && v.trim() !== '' ? v.trim() : null), z.string().nullable());

const siteFormSchema = z.object({
  display_name: z.string().trim().min(1),
  pv_kwp: numberOrNull,
  battery_nominal_kwh: numberOrNull,
  battery_dod_pct: numberOrNull,
  system_type: z.enum(['hybrid', 'off_grid', 'grid_zero']),
  report_language: z.enum(['es', 'en']),
  location: stringOrNull,
  timezone: z.string().trim().min(1),
  latitude: numberOrNull,
  longitude: numberOrNull,
  country: z.string().trim().min(1),
  savings_rate: numberOrNull,
  savings_currency: stringOrNull,
  exports_to_grid: z.boolean(),
  active: z.boolean(),
});

/** Every field in `siteFormSchema` is always present on submit — the edit
 * and add forms both render every field every time (no partial-form UI), so
 * a checkbox's *absence* from `FormData` unambiguously means "unchecked,"
 * not "leave unchanged." That's what makes it safe to always send the full
 * set through `updateSite()`'s whitelist rather than only the fields that
 * changed. */
function parseSiteForm(formData: FormData) {
  const raw = {
    display_name: formData.get('display_name'),
    pv_kwp: formData.get('pv_kwp'),
    battery_nominal_kwh: formData.get('battery_nominal_kwh'),
    battery_dod_pct: formData.get('battery_dod_pct'),
    system_type: formData.get('system_type'),
    report_language: formData.get('report_language'),
    location: formData.get('location'),
    timezone: formData.get('timezone'),
    latitude: formData.get('latitude'),
    longitude: formData.get('longitude'),
    country: formData.get('country'),
    savings_rate: formData.get('savings_rate'),
    savings_currency: formData.get('savings_currency'),
    exports_to_grid: formData.get('exports_to_grid') === 'true',
    active: formData.get('active') === 'true',
  };
  return siteFormSchema.safeParse(raw);
}

export type SiteFormState = { error?: string; success?: boolean };

export async function updateSiteAction(
  siteId: string,
  _prevState: SiteFormState,
  formData: FormData,
): Promise<SiteFormState> {
  const session = await requireCustomer();
  const parsed = parseSiteForm(formData);
  if (!parsed.success) {
    return { error: t(session.uiLanguage, 'sites_save_error') };
  }
  try {
    // `assertOwnsSite()` inside `updateSite()` is what actually stops a
    // tampered `siteId` (bound into this action via `.bind(null, siteId)`
    // client-side, so in principle editable in DevTools before submit) from
    // touching another tenant's row — this call trusts nothing about
    // `siteId` beyond "some string the browser sent."
    await updateSite(session.customerId, siteId, parsed.data as SiteUpdateFields);
  } catch {
    return { error: t(session.uiLanguage, 'sites_save_error') };
  }
  revalidatePath('/app/sites');
  return { success: true };
}

export async function addSiteAction(_prevState: SiteFormState, formData: FormData): Promise<SiteFormState> {
  const session = await requireCustomer();

  // Re-checked here even though the page only renders this form when
  // `canAddSite()` already said yes — the render-time check is UX, this is
  // the control (§1.2 rule 4). A second browser tab open on a stale render,
  // or a replayed POST after Oscar lowered the limit, must not slip through.
  const gate = await canAddSite(session.customerId);
  if (!gate.ok) {
    return { error: t(session.uiLanguage, 'sites_limit_title') };
  }

  const parsed = parseSiteForm(formData);
  if (!parsed.success) {
    return { error: t(session.uiLanguage, 'sites_create_error') };
  }

  try {
    const { display_name, ...rest } = parsed.data;
    // §1.12 rule 1's "never call `upsert_customer()` from a customer-
    // initiated path" — `createSite()` never takes a customer_id from the
    // form; it's the trusted `session.customerId` only, and the new site's
    // id is namespaced from that customer's own (already-existing) slug.
    await createSite(session.customerId, display_name, rest as SiteUpdateFields);
  } catch {
    return { error: t(session.uiLanguage, 'sites_create_error') };
  }
  revalidatePath('/app/sites');
  return { success: true };
}

export type GeocodeResult = { location: string | null; countryCode: string | null } | { error: string };

/**
 * Not a `<form action>` — invoked directly from a button's `onClick`
 * wrapped in `startTransition` (see `SiteForm.tsx`), the "event handler ...
 * wrapped in `startTransition`" shape the Next.js Server Actions guide
 * documents as the non-form way to call one. `requireCustomer()` still
 * runs first: this hits an external network call (Nominatim) on the
 * server's behalf, and an unauthenticated caller has no business triggering
 * that through this app even though it writes nothing.
 */
export async function reverseGeocodeAction(lat: number, lng: number): Promise<GeocodeResult> {
  const session = await requireCustomer();
  if (!Number.isFinite(lat) || !Number.isFinite(lng) || (lat === 0 && lng === 0)) {
    return { error: t(session.uiLanguage, 'sites_geocode_missing_coords') };
  }
  const result = await reverseGeocode(lat, lng);
  if (!result) {
    return { error: t(session.uiLanguage, 'sites_geocode_not_found') };
  }
  return result;
}
