'use client';

// The editor half of `/app/branding` (PLAN_PHASE17.md §4.5, §8 Step 5).
// Controlled inputs throughout — unlike most forms in this app
// (uncontrolled + `useActionState`, e.g. `ProfileForm.tsx`) — because the
// live header preview needs to re-render on every keystroke/colour pick,
// which an uncontrolled form can't drive.
import { useActionState, useState, type ChangeEvent } from 'react';
import { Button, Field, Input } from '@/components/ui';
import { t, type Lang } from '@/lib/i18n/strings';
import { uploadFileToSignedUrl } from '@/lib/uploadClient';
import { LOGO_ALLOWED_EXTENSIONS, LOGO_MAX_BYTES } from '@/lib/uploadLimits';
import type { BrandingFields } from '@/lib/server/db';
import { updateBrandingAction, type BrandingFormState } from './actions';
import styles from './branding.module.css';

const INITIAL_STATE: BrandingFormState = {};

// The exact defaults `victron/weekly_report.py:render_html()` falls back
// to when a field isn't set (PLAN_PHASE17.md §4) — shown here as
// placeholders/preview fallbacks so the live preview matches what an
// UNBRANDED report already looks like before the customer changes anything.
const DEFAULT_COLOR = '#1FAE6E';
const DEFAULT_COMPANY_NAME = 'Pauly & Co.';
const DEFAULT_CONTACT_EMAIL = 'proyectos@paulyco.com';

export type BrandingFormProps = {
  branding: BrandingFields;
  existingLogoUrl: string | null;
  lang: Lang;
};

export function BrandingForm({ branding, existingLogoUrl, lang }: BrandingFormProps) {
  const [state, formAction, pending] = useActionState(updateBrandingAction, INITIAL_STATE);

  const [companyName, setCompanyName] = useState(branding.company_name ?? '');
  const [primaryColor, setPrimaryColor] = useState(branding.primary_color ?? DEFAULT_COLOR);
  const [contactEmail, setContactEmail] = useState(branding.contact_email ?? '');
  const [logoPreviewUrl, setLogoPreviewUrl] = useState<string | null>(existingLogoUrl);
  const [logoPath, setLogoPath] = useState<string | null>(branding.logo_storage_path ?? null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadError(null);

    if (file.size > LOGO_MAX_BYTES) {
      setUploadError(t(lang, 'branding_logo_too_large'));
      e.target.value = '';
      return;
    }
    const lowerName = file.name.toLowerCase();
    if (!LOGO_ALLOWED_EXTENSIONS.some((ext) => lowerName.endsWith(ext))) {
      setUploadError(t(lang, 'branding_logo_unsupported_type'));
      e.target.value = '';
      return;
    }

    // Instant local preview from the File object itself — no need to wait
    // for the upload or round-trip through Storage for this (§4.5's "live
    // preview ... from the same values" includes a just-picked local file).
    // A file that's actually invalid despite its name/extension (a
    // mislabeled SVG, say) simply fails to decode here — the browser's own
    // <img> rendering IS the first check, ahead of the real Pillow one at
    // report-render time (see app/api/branding/logo-sign/route.ts's own
    // comment on why that's the real boundary, not this route).
    setLogoPreviewUrl(URL.createObjectURL(file));
    setUploading(true);
    try {
      const signRes = await fetch('/api/branding/logo-sign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, sizeBytes: file.size }),
      });
      if (!signRes.ok) {
        setUploadError(t(lang, 'branding_logo_upload_error'));
        return;
      }
      const { uploadUrl, path } = (await signRes.json()) as { uploadUrl: string; path: string };
      await uploadFileToSignedUrl(uploadUrl, file);
      setLogoPath(path);
    } catch {
      setUploadError(t(lang, 'branding_logo_upload_error'));
    } finally {
      setUploading(false);
    }
  }

  const previewCompanyName = companyName.trim() || DEFAULT_COMPANY_NAME;
  const previewContactEmail = contactEmail.trim() || DEFAULT_CONTACT_EMAIL;
  const previewColor = primaryColor || DEFAULT_COLOR;

  return (
    <div className={styles.layout}>
      <form action={formAction} className={styles.form}>
        {/* The only way `logo_storage_path` reaches the action — never a
           text input a customer could type an arbitrary path into. */}
        <input type="hidden" name="logo_storage_path" value={logoPath ?? ''} />

        <Field label={t(lang, 'branding_field_company_name')} htmlFor="branding-company-name">
          <Input
            id="branding-company-name"
            name="company_name"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder={DEFAULT_COMPANY_NAME}
            maxLength={80}
            disabled={pending}
          />
        </Field>

        <Field label={t(lang, 'branding_field_contact_email')} htmlFor="branding-contact-email">
          <Input
            id="branding-contact-email"
            name="contact_email"
            type="email"
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            placeholder={DEFAULT_CONTACT_EMAIL}
            maxLength={254}
            disabled={pending}
          />
        </Field>

        <Field label={t(lang, 'branding_field_primary_color')} htmlFor="branding-primary-color">
          <div className={styles.colorRow}>
            <input
              id="branding-primary-color"
              type="color"
              name="primary_color"
              value={previewColor}
              onChange={(e) => setPrimaryColor(e.target.value)}
              disabled={pending}
              className={styles.colorSwatch}
            />
            <span className={styles.colorHex}>{previewColor.toUpperCase()}</span>
          </div>
        </Field>

        <Field label={t(lang, 'branding_field_logo')} htmlFor="branding-logo-input">
          <input
            id="branding-logo-input"
            type="file"
            accept="image/png,image/jpeg"
            onChange={handleFileChange}
            disabled={pending || uploading}
          />
          {uploading && <p className={styles.hint}>{t(lang, 'branding_logo_uploading')}</p>}
          {uploadError && <p className={styles.error}>{uploadError}</p>}
        </Field>

        {state.error && <p className={styles.error}>{state.error}</p>}
        {state.success && <p className={styles.success}>{t(lang, 'branding_save_success')}</p>}

        <Button type="submit" disabled={pending || uploading}>
          {pending ? t(lang, 'branding_saving') : t(lang, 'branding_save_button')}
        </Button>
      </form>

      {/* The live preview (§4.5) — a plain HTML mock of the report's own
         header, built from the SAME state driving the form fields above,
         re-rendered on every change. Not a real report render: the point
         is judging a colour/logo choice without spending §2's budget on a
         real PDF for every iteration. */}
      <div className={styles.preview}>
        <span className={styles.previewLabel}>{t(lang, 'branding_preview_label')}</span>
        <div className={styles.previewHeader}>
          <div>
            <div className={styles.previewBrand} style={{ color: previewColor }}>
              {previewCompanyName}
            </div>
            <div className={styles.previewSite}>Casa Modelo</div>
            <div className={styles.previewPeriod}>{t(lang, 'branding_preview_period_label')}: 2026-08-14 &mdash; 2026-08-20</div>
          </div>
          {logoPreviewUrl && (
            // eslint-disable-next-line @next/next/no-img-element -- a signed Storage URL / local object URL, not a static asset next/image can optimize
            <img src={logoPreviewUrl} alt="" className={styles.previewLogo} />
          )}
        </div>
        <div className={styles.previewFooter}>
          {t(lang, 'branding_preview_powered_by')} {previewCompanyName} &middot; {previewContactEmail}
        </div>
      </div>
    </div>
  );
}
