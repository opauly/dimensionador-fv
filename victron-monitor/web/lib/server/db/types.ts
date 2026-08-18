import 'server-only';

// Row shapes for the three tenancy tables this app is allowed to touch
// (PLAN_PHASE14.md §1.11: "queries only tenancy-shaped tables — customers,
// sites, ingestion_log, jobs"). Deliberately *not* full 1:1 mirrors of
// every column migration 012/021 defines — `vrm_token_secret_id`,
// `vrm_user_id`, `branding`, `health_thresholds` etc. are real columns this
// app never reads or writes in Step 4, so they're left off rather than
// typed and ignored. Add a field here only when something in `app/(portal)`
// actually needs it — an unused field in this file is a silent invitation
// for a later page to read (or worse, spread-update) a column nobody
// audited for tenant-safety.

export type Lang = 'en' | 'es';
export type AccountType = 'owner' | 'installer';
export type SystemType = 'grid_zero' | 'off_grid' | 'hybrid';

export type CustomerRecord = {
  id: string;
  name: string;
  slug: string;
  contact_name: string | null;
  contact_email: string | null;
  country: string | null;
  plan: string;
  active: boolean;
  notes: string | null;
  created_at: string;
  auth_user_id: string | null;
  auth_email: string | null;
  invited_at: string | null;
  activated_at: string | null;
  account_type: AccountType;
  /** `null` = unlimited — see migration 021's own comment on this column.
   * Populated from `lib/plans.ts:PLANS` at customer-create time (Step 7);
   * overridable per customer by Oscar from then on. */
  site_limit: number | null;
  ui_language: Lang;
};

export type SiteRecord = {
  id: number;
  customer_id: string;
  site_id: string;
  vrm_installation_id: number | null;
  display_name: string;
  location: string | null;
  country: string | null;
  latitude: number | null;
  longitude: number | null;
  timezone: string;
  pv_kwp: number | null;
  battery_nominal_kwh: number | null;
  battery_dod_pct: number | null;
  /** GENERATED ALWAYS AS (nominal * dod / 100) STORED (migration 019) —
   * read-only everywhere in this app. Postgres recomputes it the instant
   * `battery_nominal_kwh`/`battery_dod_pct` change; there is no code path
   * here that writes it, and none should ever be added — see
   * `updateSite()`'s whitelist below. */
  battery_usable_kwh: number | null;
  active: boolean;
  report_language: Lang;
  system_type: SystemType;
  source: 'csv_upload' | 'vrm_api';
  exports_to_grid: boolean;
  savings_rate: number | null;
  savings_currency: string | null;
  created_at: string;
};

export type IngestionLogRecord = {
  id: number;
  site_id: string;
  source: string;
  filename: string | null;
  installation_id: string | null;
  period_start: string | null;
  period_end: string | null;
  sample_count: number | null;
  rows_written: number | null;
  alarm_events_written: number | null;
  warnings: unknown;
  uploaded_at: string;
};
