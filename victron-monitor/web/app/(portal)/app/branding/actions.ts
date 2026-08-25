'use server';

import 'server-only';

// Server Action for `app/(portal)/app/branding` (PLAN_PHASE17.md §4.4/§4.5,
// §8 Step 5). Validation here (colour regex + luminance, text length) is
// DELIBERATELY DUPLICATED from `vrm_api/branding.py`'s own rules — not
// shared, since one is Python and one is TypeScript — so a customer gets a
// real, explanatory error at save time ("too light to read") instead of
// silently having their colour ignored the first time a report renders.
// The re-validation `resolve_branding()` does at READ time (§4.2 rule 3)
// is what actually protects the renderer; this is purely for UX.
import { requireCustomer } from '@/lib/server/auth';
import { getCustomer, updateBranding, BrandingNotAllowed, type BrandingFields } from '@/lib/server/db';
import { t } from '@/lib/i18n/strings';

const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const MAX_LUMINANCE = 0.75; // matches vrm_api/branding.py's own _MAX_LUMINANCE exactly

const TEXT_FIELD_MAX_LEN: Record<string, number> = {
  company_name: 80,
  contact_name: 80,
  contact_phone: 40,
  website: 200,
};
const EMAIL_MAX_LEN = 254;

// Same WCAG relative-luminance formula as vrm_api/branding.py's
// _relative_luminance() — kept in lockstep deliberately, so a colour this
// action accepts is never one resolve_branding() would reject at read
// time (or vice versa).
function relativeLuminance(hex: string): number {
  const channel = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const r = channel(parseInt(hex.slice(1, 3), 16) / 255);
  const g = channel(parseInt(hex.slice(3, 5), 16) / 255);
  const b = channel(parseInt(hex.slice(5, 7), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function trimmedOrNull(value: FormDataEntryValue | null, maxLen: number): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.slice(0, maxLen);
}

export type BrandingFormState = { error?: string; success?: boolean };

export async function updateBrandingAction(_prevState: BrandingFormState, formData: FormData): Promise<BrandingFormState> {
  const session = await requireCustomer();
  const lang = session.uiLanguage;

  const fields: BrandingFields = {};

  const companyName = trimmedOrNull(formData.get('company_name'), TEXT_FIELD_MAX_LEN.company_name);
  if (companyName) fields.company_name = companyName;

  const contactEmail = trimmedOrNull(formData.get('contact_email'), EMAIL_MAX_LEN);
  if (contactEmail) {
    if (!contactEmail.includes('@') || !contactEmail.split('@', 2)[1]?.includes('.')) {
      return { error: t(lang, 'branding_error_invalid_email') };
    }
    fields.contact_email = contactEmail;
  }

  const primaryColorRaw = formData.get('primary_color');
  if (typeof primaryColorRaw === 'string' && primaryColorRaw.trim()) {
    const primaryColor = primaryColorRaw.trim();
    if (!HEX_COLOR_RE.test(primaryColor)) {
      return { error: t(lang, 'branding_error_invalid_color') };
    }
    if (relativeLuminance(primaryColor) > MAX_LUMINANCE) {
      return { error: t(lang, 'branding_error_color_too_light') };
    }
    fields.primary_color = primaryColor;
  }

  const logoStoragePath = trimmedOrNull(formData.get('logo_storage_path'), 300);
  // Only ever set from this app's own `/api/branding/logo-sign` response
  // (BrandingForm.tsx never lets a customer type this by hand) — still not
  // trusted as a real image until `resolve_branding()`'s Pillow check at
  // render time; this action just stores the path.
  if (logoStoragePath) fields.logo_storage_path = logoStoragePath;

  try {
    const customer = await getCustomer(session.customerId);
    await updateBranding(customer, fields);
  } catch (err) {
    if (err instanceof BrandingNotAllowed) {
      // The direct-POST-with-a-valid-session case Step 5's own gate calls
      // out explicitly: nothing was written, and this message is honest
      // about why rather than a generic "something went wrong".
      return { error: t(lang, 'branding_error_not_allowed') };
    }
    return { error: t(lang, 'branding_save_error') };
  }

  return { success: true };
}
