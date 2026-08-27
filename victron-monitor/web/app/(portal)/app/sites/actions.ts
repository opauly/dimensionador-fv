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
import {
  applyScheduleToAllSites,
  canAddSite,
  countSchedulableSites,
  createSite,
  estimatedReportsPerPeriod,
  getScheduledCapLimit,
  getCustomer,
  updateSite,
  type BulkScheduleFields,
  type ReportSchedule,
  type SiteUpdateFields,
} from '@/lib/server/db';
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

// PLAN_PHASE17.md §3.7 — these four are CONDITIONALLY rendered in
// `SiteForm.tsx` (the schedule section only shows for an existing
// `source='vrm_api'` site; the weekday/day-of-month fields only show for
// their own matching cadence), so `FormData` genuinely omits them in most
// submissions — a plain, non-optional `z.enum`/`z.number()` would fail
// every csv_upload-site edit and the whole add-site flow. Each preprocessor
// falls back to migration 026's own column default (`'off'`/1/1/6) for
// anything missing or out of range, rather than rejecting the submission —
// `sites.ts:updateSite()`'s `ScheduleRequiresVrmApi` check is what actually
// matters for a csv_upload site, not this shape check.
const reportScheduleField = z.preprocess(
  (v) => (typeof v === 'string' && ['off', 'daily', 'weekly', 'monthly'].includes(v) ? v : 'off'),
  z.enum(['off', 'daily', 'weekly', 'monthly']),
);
const weekdayField = z.preprocess((v) => {
  const n = Number(v);
  return Number.isInteger(n) && n >= 1 && n <= 7 ? n : 1;
}, z.number().int().min(1).max(7));
const dayOfMonthField = z.preprocess((v) => {
  const n = Number(v);
  return Number.isInteger(n) && n >= 1 && n <= 28 ? n : 1;
}, z.number().int().min(1).max(28));
const hourField = z.preprocess((v) => {
  const n = Number(v);
  return Number.isInteger(n) && n >= 0 && n <= 23 ? n : 6;
}, z.number().int().min(0).max(23));

// PLAN_PHASE17.md §0.6 Q5 / §8 Step 8 — `SiteForm.tsx` submits this as one
// newline-separated textarea value (also always absent for a csv_upload
// site's edit form and the add form, same as the four schedule fields
// above — hence the same "default to the safe empty value when missing"
// shape). The real cap/format enforcement is `sites.ts:sanitizeRecipients()`,
// server-side, independent of this parse — this only turns the textarea
// string into an array Zod can validate the SHAPE of.
const reportRecipientsField = z.preprocess((v) => {
  if (typeof v !== 'string') return [];
  return v.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
}, z.array(z.string()));

// PLAN_PHASE18.md §5. Genuinely optional in this schema — NOT "default to
// an empty array when missing" like the schedule fields above. An empty
// checkbox group (report_modules_present absent, so `parseSiteForm()`
// below never puts this key in `raw` at all) and "the customer unchecked
// every box" (report_modules_present present, `report_modules` genuinely
// `[]`) must stay distinguishable all the way to `updateSite()` — the
// first must never touch the stored value, the second is a real, valid
// "zero optional modules" choice. Real validation (known ids only, the
// Growth/Fleet gate) is `sites.ts:sanitizeReportModules()`, server-side,
// same "Zod only checks the shape" split every other field here uses.
const reportModulesField = z.array(z.string()).optional();

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
  report_schedule: reportScheduleField,
  report_schedule_weekday: weekdayField,
  report_schedule_day_of_month: dayOfMonthField,
  report_schedule_hour: hourField,
  report_recipients: reportRecipientsField,
  report_modules: reportModulesField,
});

/** Every field in `siteFormSchema` is always present on submit — the edit
 * and add forms both render every field every time (no partial-form UI), so
 * a checkbox's *absence* from `FormData` unambiguously means "unchecked,"
 * not "leave unchanged." That's what makes it safe to always send the full
 * set through `updateSite()`'s whitelist rather than only the fields that
 * changed. (The four schedule fields above are the one exception — see
 * their own comment.) */
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
    report_schedule: formData.get('report_schedule'),
    report_schedule_weekday: formData.get('report_schedule_weekday'),
    report_schedule_day_of_month: formData.get('report_schedule_day_of_month'),
    report_schedule_hour: formData.get('report_schedule_hour'),
    report_recipients: formData.get('report_recipients'),
    // Deliberately NOT `formData.getAll('report_modules')` unconditionally —
    // see `reportModulesField`'s own comment. Only included at all when
    // `SiteForm.tsx`'s hidden sentinel confirms the checklist actually
    // rendered; otherwise this key is genuinely absent from `raw`, and Zod's
    // `.optional()` then leaves it absent from `parsed.data` too, so
    // `updateSite()`'s whitelist never touches the column.
    ...(formData.has('report_modules_present') ? { report_modules: formData.getAll('report_modules') } : {}),
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

// ── Bulk "apply schedule to all sites" (PLAN_PHASE17.md §3.7, §2.2 "moment
// 1") — two separate actions, not one: the projection is a pure read (no
// `<form>`, invoked the same "onClick wrapped in startTransition" way
// `reverseGeocodeAction` above already is), so `SitesManager.tsx` can show
// the customer the real numbers BEFORE the confirm button even exists,
// exactly the "refused with the projected number named, before anything is
// saved" requirement — this is a UI-side ESTIMATE (`estimatedReportsPerPeriod()`'s
// own comment), not a live count; the actual enforcement is
// `vrm_api/report_limits.py:check_scheduled_cap()`, unaffected by anything
// in this file.
export type BulkScheduleProjection =
  | { ok: true; siteCount: number; projectedPerPeriod: number; cap: number; overCap: boolean }
  | { error: string };

export async function getBulkScheduleProjectionAction(schedule: ReportSchedule): Promise<BulkScheduleProjection> {
  const session = await requireCustomer();
  try {
    const [customer, siteCount] = await Promise.all([getCustomer(session.customerId), countSchedulableSites(session.customerId)]);
    const cap = await getScheduledCapLimit(customer.plan);
    const projectedPerPeriod = Math.round(estimatedReportsPerPeriod(schedule) * siteCount);
    return { ok: true, siteCount, projectedPerPeriod, cap, overCap: projectedPerPeriod > cap };
  } catch {
    return { error: t(session.uiLanguage, 'sites_bulk_apply_error') };
  }
}

export async function applyScheduleToAllSitesAction(fields: BulkScheduleFields): Promise<{ count: number } | { error: string }> {
  const session = await requireCustomer();
  try {
    const count = await applyScheduleToAllSites(session.customerId, fields);
    revalidatePath('/app/sites');
    return { count };
  } catch {
    return { error: t(session.uiLanguage, 'sites_bulk_apply_error') };
  }
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
