import 'server-only';

// Row shapes for the three tenancy tables this app is allowed to touch
// (PLAN_PHASE14.md §1.11: "queries only tenancy-shaped tables — customers,
// sites, ingestion_log, jobs"). Deliberately *not* full 1:1 mirrors of
// every column migration 012/021 defines — `vrm_token_secret_id`,
// `vrm_user_id`, `branding`, `health_thresholds` etc. are real columns this
// app never reads or writes in Step 4, so they're left off rather than
// typed and ignored. Add a field here only when something in `app/(portal)`
// — or, since `lib/server/db/admin.ts`'s `AdminCustomerRow`/`listAllSites()`
// build directly on `CustomerRecord`/`SiteRecord`, something in
// `app/(admin)` — actually needs it. An unused field in this file is a
// silent invitation for a later page to read (or worse, spread-update) a
// column nobody audited for tenant-safety.
//
// `vrm_token_*`/`vrm_account_email`/`vrm_last_sync*`/`vrm_sync_enabled`
// below (PLAN_PHASE15.md §8 Step 6) are the one deliberate exception to
// "the customer-facing surface reads this": `app/(portal)/app/**` never
// reads these off `CustomerRecord`/`SiteRecord` directly — it gets
// connection state from `vrm_api`'s own `GET /v1/vrm-link/status`
// (`lib/server/db/vrmLink.ts`'s `VrmLinkStatusOut`, see that file's own
// header comment on why). These fields exist here only because
// `/admin/customers` and `/admin/sites` have no such endpoint to call —
// there is no "every customer's VRM status" `vrm_api` route, and Step 6
// deliberately didn't add one (PLAN_PHASE15.md's own framing: this is
// Postgres data already in scope for a direct admin query).

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
  /** Set once, at first connect, by `vrm.set_customer_vrm_token()` —
   * NEVER cleared on disconnect (only `vrm_token_revoked_at` is), so a
   * disconnected customer's row can still carry a stale email from their
   * last connection. `/admin/customers`'s VRM link column only trusts this
   * alongside `vrm_token_revoked_at`/`vrm_token_added_at` below, never
   * alone. */
  vrm_account_email: string | null;
  /** Stamped `now()` on every (re)connect by `vrm.set_customer_vrm_token()`
   * (migration 012/024); the "Conectado <email> desde <date>" date on
   * `/admin/customers`. */
  vrm_token_added_at: string | null;
  /** `NULL` while connected. Stamped `now()` by BOTH a deliberate
   * disconnect (`vrm.clear_customer_vrm_token()`, customer- or
   * admin-triggered) and an auth failure (401/403 —
   * `vrm_api/routers/vrm_sync.py`'s `VrmRemoteAuthError` handler) — this
   * column alone can't distinguish "the customer chose to disconnect" from
   * "their token broke," which is why `/admin/customers`'s VRM link column
   * (PLAN_PHASE15.md §8 Step 6) reads it as one unified "not connected"
   * state either way, same as `vrm_api`'s own `connected` boolean does. */
  vrm_token_revoked_at: string | null;
  /** A hand-written, customer-safe sentence (never a raw Victron/Postgres
   * error — PLAN_PHASE14.md §1.12 rule 6), written only by the
   * `VrmRemoteAuthError` handler above and cleared to `NULL` on the next
   * successful customer-token sync. Untouched by a deliberate disconnect. */
  vrm_token_last_error: string | null;
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
  /** Stamped `now()` by `vrm_api/routers/vrm_sync.py:_do_sync()` after
   * every successful sync (any trigger) — the "Última sync VRM" column on
   * `/admin/sites` (PLAN_PHASE15.md §8 Step 6). `NULL` for a `csv_upload`
   * site, or a `vrm_api` site never yet synced. */
  vrm_last_synced_at: string | null;
  /** A short, hand-written failure code/sentence written by `_do_sync()`'s
   * non-auth failure branches (`installation_not_found`, an unreachable-VRM
   * message, a `vrm_series` mapping error) — never a raw Victron/Postgres
   * error string. Cleared to `NULL` on the next successful sync. Admin-only
   * surface (`/admin/sites`); the customer-facing equivalent is
   * `VrmLinkSiteStatus.vrm_last_sync_error` in `lib/server/pipeline.ts`,
   * read through `vrm_api` rather than this column directly (see this
   * file's header comment). */
  vrm_last_sync_error: string | null;
  /** `false` disables further syncs for this site without touching its
   * data — set by `_do_sync()` when the linked VRM installation goes
   * missing (§9's "installation removed" row). Defaults `false` on every
   * pre-Phase-15 `csv_upload` row (migration 024); flipped `true` only by
   * the connect flow (`vrm_link.py`'s `POST /connect`). */
  vrm_sync_enabled: boolean;
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
