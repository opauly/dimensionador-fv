'use server';

import 'server-only';

// Server Actions for `/admin/sites` (PLAN_PHASE14.md §2 Step 7).
import { revalidatePath } from 'next/cache';
import { z } from 'zod';
import { requireAdmin } from '@/lib/server/auth';
import { updateAnySite, reassignSite, type AdminSiteUpdateFields } from '@/lib/server/db/admin';

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
  });
  if (!parsed.success) return { error: 'No se pudo guardar el sitio.' };

  try {
    await updateAnySite(siteId, parsed.data as AdminSiteUpdateFields);
  } catch {
    return { error: 'No se pudo guardar el sitio. Intentá de nuevo.' };
  }
  revalidatePath('/admin/sites');
  return { success: true };
}

export type ReassignState = { error?: string; success?: boolean };

export async function reassignSiteAction(siteId: string, newCustomerId: string): Promise<ReassignState> {
  await requireAdmin();
  if (!newCustomerId) return { error: 'Elegí un cliente.' };
  try {
    await reassignSite(siteId, newCustomerId);
  } catch {
    return { error: 'No se pudo reasignar el sitio.' };
  }
  revalidatePath('/admin/sites');
  return { success: true };
}
