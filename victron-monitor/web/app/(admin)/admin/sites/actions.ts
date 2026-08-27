'use server';

import 'server-only';

// Server Actions for `/admin/sites` (PLAN_PHASE14.md §2 Step 7).
import { revalidatePath } from 'next/cache';
import { z } from 'zod';
import { requireAdmin } from '@/lib/server/auth';
import { updateAnySite, reassignSite, AdminScheduleRequiresVrmApi, type AdminSiteUpdateFields } from '@/lib/server/db/admin';

const numberOrNull = z.preprocess((v) => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}, z.number().nullable());
const stringOrNull = z.preprocess((v) => (typeof v === 'string' && v.trim() !== '' ? v.trim() : null), z.string().nullable());

// Same shape as `app/(portal)/app/sites/actions.ts`'s own four schedule
// preprocessors — restated here rather than imported, same reasoning as
// `lib/server/db/admin.ts`'s whitelist (each surface keeps its own copy).
// Each falls back to migration 026's own column default for anything
// missing or out of range; `updateAnySite()`'s `AdminScheduleRequiresVrmApi`
// check is what actually matters for a csv_upload site, not this shape check.
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
const reportRecipientsField = z.preprocess((v) => {
  if (typeof v !== 'string') return [];
  return v.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
}, z.array(z.string()));

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
});

export type AdminSiteFormState = { error?: string; success?: boolean };

export async function updateAnySiteAction(siteId: string, _prevState: AdminSiteFormState, formData: FormData): Promise<AdminSiteFormState> {
  await requireAdmin();

  const parsed = siteFormSchema.safeParse({
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
  });
  if (!parsed.success) return { error: 'Could not save the site.' };

  try {
    await updateAnySite(siteId, parsed.data as AdminSiteUpdateFields);
  } catch (err) {
    if (err instanceof AdminScheduleRequiresVrmApi) return { error: err.message };
    return { error: 'Could not save the site. Please try again.' };
  }
  revalidatePath('/admin/sites');
  return { success: true };
}

export type ReassignState = { error?: string; success?: boolean };

export async function reassignSiteAction(siteId: string, newCustomerId: string): Promise<ReassignState> {
  await requireAdmin();
  if (!newCustomerId) return { error: 'Choose a customer.' };
  try {
    await reassignSite(siteId, newCustomerId);
  } catch {
    return { error: 'Could not reassign the site.' };
  }
  revalidatePath('/admin/sites');
  return { success: true };
}
