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
  // ── PLAN_PHASE16.md §3.6 / §8 Step 6 — four billing/signup columns ────
  // Read directly off `vrm.customers` here (not through `vrm_api`, unlike
  // `app/(portal)/app/**`'s own billing reads — see `lib/server/db/billing.ts`'s
  // header comment) because `/admin/customers` is exactly the "Postgres data
  // already in scope for a direct admin query" case this file's own header
  // comment already carves out for the VRM-link columns above, and because
  // §5.1's `BillingStatusOut` is deliberately a SINGLE-customer read (a
  // `customer_id` query param) with no bulk/admin variant to call instead.
  /** `'manual'` (a hand-negotiated `site_limit`) or `'plan'` (tracks
   * `vrm.plans.site_limit` for the customer's current subscription) —
   * diagnostic only here, never edited from `/admin/customers` directly. */
  site_limit_source: 'manual' | 'plan';
  /** A derived, denormalized cache of the entitlement decision, written
   * only by `vrm_api/billing.py:apply_entitlements()` — `'none' | 'trialing'
   * | 'active' | 'past_due' | 'canceled' | 'incomplete' | 'unpaid'` in
   * practice, but NO CHECK constraint (same reasoning as `vrm.subscriptions
   * .status`), so this stays `string | null` rather than a closed union. */
  billing_status: string | null;
  /** `'active'` = a real tenant. `'pending_subscription'` = an email-verified
   * self-serve signup with no entitled subscription yet — the "Pending
   * signup" filter/badge on `/admin/customers`. */
  provisioning_state: 'pending_subscription' | 'active';
  /** `'admin'` = Oscar invited/created this account by hand (every
   * pre-Phase-16 row). `'self_serve'` = created via the public `/signup`
   * flow. Never used in an authorization decision — filter/diagnostics
   * only, per migration 025's own column comment. */
  origin: 'admin' | 'self_serve';
  /** jsonb, shape documented in migration 026's own `COMMENT ON COLUMN`
   * and `lib/server/db/branding.ts:BrandingFields` (PLAN_PHASE17.md §4.1)
   * — company_name/logo_storage_path/primary_color/contact fields/website,
   * all optional. `{}` on every pre-Phase-17 row. Read here (added 2026-08-21,
   * this file's own header comment's exception rule: "add a field only
   * when something in app/(portal) actually needs it" — the branding
   * settings page, `app/(portal)/app/branding/`, does) but this is NEVER
   * the value a rendered report sees directly: `vrm_api/branding.py:
   * resolve_branding()` is the only thing that turns this raw jsonb into
   * what `victron/weekly_report.py` receives, gated on tier + entitlement.
   * This app's own read/write path (`lib/server/db/branding.ts`) applies
   * the SAME two gates independently, for UX only — the real enforcement
   * stays server-side at render time regardless of what this layer does. */
  branding: Record<string, unknown> | null;
  /** Applied by `sites.ts:createSite()` to NEW sites only, and only when
   * the new site's `source='vrm_api'` (PLAN_PHASE17.md §0.7/§3.1/§5.4) —
   * never retroactively. `'off'` on every pre-Phase-17 row. */
  default_report_schedule: ReportSchedule;
  /** PLAN_PHASE18.md §1. Applied to a customer's NEW sites only, at
   * creation, never retroactively — same rule `default_report_schedule`
   * follows. `NULL` (every pre-Phase-18 row) means "no default," which
   * itself means "every module on" once resolved. */
  default_report_modules: string[] | null;
};

/** PLAN_PHASE17.md §3/§5.3. `'off'` is the only legal value for a
 * `source='csv_upload'` site (migration 026's
 * `sites_scheduled_reports_require_vrm_api` CHECK) — enforced again,
 * independently, in `sites.ts:updateSite()`/`createSite()` (§3.1 point 2:
 * "hide an editor is UX, never the control"). */
export type ReportSchedule = 'off' | 'daily' | 'weekly' | 'monthly';

/** One `vrm.billing_events` row (PLAN_PHASE16.md §3.5 / §8 Step 6) — the
 * append-only webhook receipt log `/admin/activity`'s new "Billing events"
 * section reads. `secret_ok=false` rows (a rejected/forged delivery) are
 * the one thing that section must make visibly distinguishable — see that
 * table's own header comment. `payload` is kept as `unknown` (never typed
 * against ONVO's own shape, same as `vrm.subscriptions.raw` upstream) —
 * this view only ever shows it inside an expandable detail row, the same
 * "raw payload behind a toggle" shape `ActivityTable.tsx`'s own `warnings`
 * column already uses. */
export type BillingEventRecord = {
  id: string;
  received_at: string;
  event_type: string | null;
  secret_ok: boolean;
  customer_id: string | null;
  subscription_id: string | null;
  status: string;
  processed_at: string | null;
  error: string | null;
  payload: unknown;
};

/** One `vrm.signup_requests` row (PLAN_PHASE16.md §3.7 / §8 Step 6) — the
 * staging-table read `/admin/activity`'s "Recent signups" panel uses.
 * `consumed_at` set = the visitor actually redeemed their verification
 * link (`token_hash` and the raw token itself are never selected here —
 * see that column's own migration comment on why the token is never even
 * stored, let alone read back). */
export type SignupRequestRecord = {
  id: string;
  email: string;
  name: string;
  account_type: AccountType;
  created_at: string;
  expires_at: string;
  consumed_at: string | null;
  customer_id: string | null;
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
  // ── PLAN_PHASE17.md §3/§5.3/§8 Step 6-7 — the schedule ──────────────────
  // Only ever non-`'off'` when `source='vrm_api'` (migration 026's
  // `sites_scheduled_reports_require_vrm_api` CHECK, §0.7) — a CSV site's
  // data is only as fresh as the last manual upload, so it can never be
  // scheduled. `'off'` on every pre-Phase-17 row.
  report_schedule: ReportSchedule;
  /** ISO weekday, 1=Monday..7=Sunday. Only meaningful when
   * `report_schedule='weekly'`. */
  report_schedule_weekday: number;
  /** 1-28 (capped by a CHECK — never 29-31, so a monthly schedule never
   * silently skips February, §3.2). Only meaningful when
   * `report_schedule='monthly'`. */
  report_schedule_day_of_month: number;
  /** 0-23, in the site's own `timezone` column above. */
  report_schedule_hour: number;
  /** `NULL`/empty falls back to the customer's own `contact_email` at send
   * time (Step 8, not built yet) — third-party recipients are §0.6 Q5,
   * still open. */
  report_recipients: string[] | null;
  /** PLAN_PHASE18.md §1. `NULL` (every pre-Phase-18 row) means every one
   * of the 9 selectable modules renders — today's exact behavior,
   * unchanged. Only ever honored for a Growth/Fleet-installer customer;
   * `getReportModulesAccess()` is the gate, not this column alone. */
  report_modules: string[] | null;
  /** The last successfully-generated SCHEDULED period's end date — never
   * touched by a manual/admin report run. `NULL` until the first one. */
  report_last_period_end: string | null;
  report_last_run_at: string | null;
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
