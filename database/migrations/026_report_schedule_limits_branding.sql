-- Migration 026: scheduled reports, report cost limits, tiered branding —
-- the schema half of Phase 17 Step 2
--
-- PLAN_PHASE17.md §5 in full, §8 Step 2. Schema and seed data ONLY — no
-- vrm_api scheduler/limits/branding code, no frontend. Those are later
-- steps. All new objects live in the `vrm` schema (already exposed to
-- PostgREST, migration 012), same house style as migrations 024/025:
-- idempotent (`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`),
-- header records reasoning, not just DDL.
--
-- FOUR new tables/column groups: (1) vrm.plan_limits — per-tier cost and
-- capability limits, (2) vrm.report_runs — the ledger for every report
-- generation attempt, manual or scheduled, (3) vrm.sites — seven new
-- columns for the per-site schedule, plus a table-level CHECK, (4)
-- vrm.customers — one new column (default_report_schedule) and an updated
-- COMMENT on the long-dead `branding` column.
--
-- ── 1. vrm.plan_limits — per-tier cost and capability limits (§5.1) ──────
-- Keyed by plan_key alone (NOT (plan_key, interval, currency, mode) like
-- vrm.plans) — a customer's limits should not depend on whether they pay
-- monthly or annually. Every per-tier number here is a database row, not a
-- constant, for the same reason migration 021 made site_limit a column
-- instead of a TS constant: a hand-negotiated deal should cost an UPDATE,
-- not a deploy. The 'default' row is mandatory and is the MOST
-- RESTRICTIVE row in the table — the opposite of lib/plans.ts:
-- planSiteLimit(), which fails open; a customer whose plan string is a
-- typo or a retired name gets the tightest limits, not the loosest.
-- Seeded below with Oscar's own numbers (PLAN_PHASE17.md §2.3, revised
-- 2026-08-21 from the architect's first-guess table) — not a placeholder
-- pass; these are the real starting values.
--
-- ── 2. vrm.report_runs — the ledger (§5.2) ────────────────────────────────
-- One row per report generation attempt, manual or scheduled. Three jobs
-- at once: the scheduled-runs cap's counter, the scheduler's idempotency
-- claim, and the "what happened last night" audit trail PHASES.md Phase 12
-- named as non-negotiable for an unattended job. The idempotency claim is
-- a PARTIAL UNIQUE INDEX on (site_id, period_end) WHERE trigger='scheduled'
-- — not a lock in a process — so two overlapping cron runs cannot
-- double-generate; a manual regeneration of the same range is a
-- legitimate, unrestricted thing to do (that's what the separate manual
-- rate limit is for), so manual rows are deliberately NOT covered by the
-- index. No CHECK on `status`: same reasoning as vrm.subscriptions.status
-- and vrm.billing_events.status (migration 025) — a status vocabulary that
-- grows should not be able to fail an insert in a background job. These
-- rows are NOT pruned (unlike vrm.signup_requests) — they are the audit
-- trail for a paid deliverable, and volume is bounded by the scheduled-run
-- cap by construction.
--
-- ── 3. vrm.sites — seven new columns + one table-level CHECK (§5.3) ──────
-- report_schedule defaults to 'off' so EVERY SITE THAT EXISTS TODAY KEEPS
-- BEHAVING EXACTLY AS IT DOES TODAY — the same protective-default
-- direction migration 024 used for vrm_sync_enabled and migration 025 used
-- for provisioning_state. day_of_month is capped at 28 (not 31) so
-- February never silently skips a month (PLAN_PHASE17.md §3.2).
--
-- Oscar's own decision, 2026-08-21 (PLAN_PHASE17.md §0.7, raised
-- independently of the architect's original eleven questions): a
-- CSV-sourced site's data is only ever as fresh as the last manual upload,
-- so scheduling automatic reports against it schedules reports against
-- data that usually isn't there yet. ONLY source='vrm_api' sites may ever
-- be scheduled. The table-level CHECK below
-- (sites_scheduled_reports_require_vrm_api) makes the invalid state
-- (a CSV-sourced site with a live schedule) UNREPRESENTABLE at the
-- database layer — the first of three independent enforcement layers
-- (write-path and UI are the other two, built in later steps). Every
-- existing vrm.sites row passes trivially, since report_schedule defaults
-- to 'off' for all of them regardless of source.
--
-- ── 4. vrm.customers — one new column + one comment fix (§5.4) ───────────
-- default_report_schedule is applied by createSite() (a later step) to
-- NEW sites only, and only when the new site's source='vrm_api' — never
-- retroactively, and never to an existing row. This migration only adds
-- the column; nothing here changes what any existing row does.
--
-- The `branding` jsonb column has existed since migration 012 with the
-- comment "(logo_url, primary_color, contact block)" and has been
-- completely dead ever since — nothing reads it, nothing writes it. This
-- migration updates that COMMENT to document the real shape
-- (PLAN_PHASE17.md §4.1) and name vrm_api/branding.py:resolve_branding()
-- (a later step) as the only reader. The column itself is unchanged: still
-- jsonb, still no schema-level constraint on its keys, same reasoning
-- migration 012 gave — it genuinely varies and shouldn't need a migration
-- per field.
--
-- ── What this migration deliberately does NOT do (PLAN_PHASE17.md §5.5) ──
-- No new SECURITY DEFINER function. No CHECK on vrm.report_runs.status. No
-- backfill of vrm.report_runs from vrm.jobs (those rows have no
-- period/trigger/schedule semantics and would corrupt the scheduled-runs
-- cap's counts on day one). No change to vrm.plans — the tier catalogue is
-- the money path; limits are not. No RLS policies (anon/authenticated hold
-- zero grants on vrm — nothing to police; every access path is
-- service-role from server-only code, unchanged since migration 012).
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice.
-- Afterwards, verify with `python -m tools.run_migration_026`.


-- ════════════════════════════════════════════════════════════════════
-- 1. vrm.plan_limits (§5.1)
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.plan_limits (
  -- No FK to vrm.plans (different grain — one row per TIER, not per
  -- price) and no CHECK (vrm.customers.plan is free text and always has
  -- been, migration 012/021).
  plan_key                     text        PRIMARY KEY,
  manual_reports_per_hour      int         NOT NULL,
  manual_reports_per_day       int         NOT NULL,
  scheduled_reports_per_period int         NOT NULL,
  white_label                  boolean     NOT NULL DEFAULT false,
  notes                        text,
  updated_at                   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE vrm.plan_limits ENABLE ROW LEVEL SECURITY;
GRANT ALL ON vrm.plan_limits TO service_role;

COMMENT ON TABLE vrm.plan_limits IS
  'Per-tier report cost limits and the white-label gate (PLAN_PHASE17.md §2.3/§5.1) — every number here is a database row, not a constant, so a hand-negotiated exception costs Oscar one UPDATE, not a deploy. The ''default'' row is MANDATORY and is stricter than every PAID tier (starter/growth/fleet) — deliberately the opposite of lib/plans.ts:planSiteLimit(), which fails open — reached only by a typo or a retired plan string, and it should be survivable, not generous. It is NOT the strictest row in the whole table: ''trial'' and ''single_report'' are independently even stricter on scheduled_reports_per_period (0, vs default''s 4), because those states cannot schedule reports at all (no paid subscription, or CSV-only — §0.7), which is a structural restriction, not a typo-safety one. Resolution: vrm.customers.plan -> this table''s plan_key, falling back to ''default'' for any unrecognized value. Read by vrm_api/report_limits.py (Cap A/Cap B, a later step) and vrm_api/branding.py:resolve_branding() (white_label, a later step) — neither exists yet as of this migration.';
COMMENT ON COLUMN vrm.plan_limits.scheduled_reports_per_period IS
  'The cap on trigger=''scheduled'' vrm.report_runs rows per billing period (PLAN_PHASE17.md §2.2 Cap B). Calibrated (§2.3) so weekly-on-every-site-plus-daily-on-a-handful clears the cap, and daily-across-most-of-the-fleet is capped — that ratio is the thing to preserve if these numbers are ever re-derived, not the absolute values.';
COMMENT ON COLUMN vrm.plan_limits.white_label IS
  'Gates whether vrm_api/branding.py:resolve_branding() (a later step) ever looks at vrm.customers.branding for this tier, or ignores it outright and returns the Pauly & Co defaults. Not a UI condition — the renderer never receives unresolved branding for a false-gated customer (PLAN_PHASE17.md §4.2).';

-- Oscar's own numbers, 2026-08-21 (PLAN_PHASE17.md §2.3) — not a
-- placeholder pass. ON CONFLICT DO NOTHING: safe to re-run this migration
-- without silently overwriting a row Oscar has already hand-tuned with a
-- real UPDATE.
INSERT INTO vrm.plan_limits
  (plan_key, manual_reports_per_hour, manual_reports_per_day, scheduled_reports_per_period, white_label, notes)
VALUES
  ('default',       3, 10,   4, false, 'Fallback for any unrecognized vrm.customers.plan string. Most restrictive on purpose — reached only by a typo or a retired plan name.'),
  ('trial',         2, 10,   0, false, 'plan=''trial'' means either a legacy hand-created customer with no subscription (provisioning_state=''active'') or a signup that verified email but has not yet subscribed (provisioning_state=''pending_subscription''). A real trialing customer has plan=''starter'' and billing_status=''trialing'' — they get the starter row below, correctly. Scheduling is a paid capability; 0 here reflects that, and (independently, PLAN_PHASE17.md §0.7) plan=''single_report''/''trial'' rows are typically CSV-sourced anyway, which can never schedule regardless.'),
  ('single_report', 3, 5,    0, false, 'One-off purchase against a single uploaded CSV. 0 scheduled for two independent reasons: no subscription, and (§0.7) CSV-sourced sites can never be scheduled.'),
  ('starter',       10, 30,  100, false, 'Up to 10 sites (PLAN_PHASE16.md §0.6 Q1). Weekly-on-10 sites is roughly 44 reports/month, comfortably inside 100; daily-on-all-10 is roughly 300, which is deliberately capped.'),
  ('growth',        20, 50,  300, true,  'Up to 50 sites. Weekly-on-50 is roughly 217 reports/month, inside 300 with headroom; daily-on-all-50 is roughly 1,500, which is deliberately capped. First tier with white_label=true.'),
  ('fleet',         40, 200, 2000, true, '50+ sites, hand-negotiated. Generous by design — Fleet is a conversation, and any real exception is one UPDATE away.')
ON CONFLICT (plan_key) DO NOTHING;


-- ════════════════════════════════════════════════════════════════════
-- 2. vrm.report_runs (§5.2)
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.report_runs (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id   uuid        NOT NULL REFERENCES vrm.customers(id) ON DELETE CASCADE,
  -- text, no FK — matches vrm.jobs' own precedent (migration 023).
  site_id       text        NOT NULL,
  trigger       text        NOT NULL
                              CHECK (trigger IN ('scheduled', 'manual', 'admin')),
  -- The cadence that produced this run; NULL for a manual/admin run.
  schedule      text,
  period_start  date        NOT NULL,
  period_end    date        NOT NULL,
  -- PLAN_PHASE17.md §3.4's status vocabulary (done / skipped_not_due /
  -- skipped_no_data / skipped_capped / skipped_not_entitled / failed /
  -- abandoned). No CHECK — see this migration's header.
  status        text        NOT NULL,
  attempt_count int         NOT NULL DEFAULT 0,
  storage_path  text,
  -- The vrm.jobs row, when one was used for this run.
  job_id        uuid,
  -- Who this run was emailed to (a later step). NULL/empty until then.
  recipients    text[],
  -- 'sent' | 'failed' | 'skipped' | NULL (email not yet in scope for this
  -- run's trigger path).
  email_status  text,
  -- Customer-safe only — vrm_api/jobs.py:_safe_error_message()'s
  -- allow-list discipline, same as every other error column in this
  -- schema.
  error         text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

-- The scheduler's idempotency claim: INSERT ... ON CONFLICT DO NOTHING
-- RETURNING id. If nothing comes back, the period is already claimed —
-- Postgres is the mutex, not an application-level lock (same move
-- PLAN_PHASE16.md §5.4 made for duplicate subscriptions). Deliberately
-- partial: a manual regeneration of the same (site_id, period_end) is a
-- legitimate, unrestricted thing to do, so trigger='manual' rows are not
-- covered.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vrm_report_runs_scheduled_period
  ON vrm.report_runs (site_id, period_end) WHERE trigger = 'scheduled';

CREATE INDEX IF NOT EXISTS idx_vrm_report_runs_customer
  ON vrm.report_runs (customer_id, created_at DESC);
-- The scheduled-runs cap's own count query (PLAN_PHASE17.md §2.2 Cap B).
CREATE INDEX IF NOT EXISTS idx_vrm_report_runs_cap
  ON vrm.report_runs (customer_id, trigger, status, period_end);

ALTER TABLE vrm.report_runs ENABLE ROW LEVEL SECURITY;
GRANT ALL ON vrm.report_runs TO service_role;

COMMENT ON TABLE vrm.report_runs IS
  'One row per report generation attempt, manual or scheduled (PLAN_PHASE17.md §5.2). Serves three jobs: the scheduled-runs cap''s counter (Cap B), the scheduler''s idempotency claim (the partial unique index below), and the audit trail PHASES.md Phase 12 named as non-negotiable for an unattended job. NOT pruned, unlike vrm.signup_requests — this is the audit trail for a paid deliverable, and volume is bounded by Cap B by construction. Do not add this table to Phase 16''s prune sweep by analogy.';
COMMENT ON COLUMN vrm.report_runs.status IS
  'PLAN_PHASE17.md §3.4''s vocabulary: done, skipped_not_due, skipped_no_data, skipped_capped, skipped_not_entitled, failed, abandoned. No CHECK, same reasoning as vrm.subscriptions.status (migration 025) — a status vocabulary that grows should not be able to fail an insert in a background job.';
COMMENT ON INDEX vrm.idx_vrm_report_runs_scheduled_period IS
  'The scheduler''s entire idempotency guarantee (PLAN_PHASE17.md §0.5 Decision 1, §5.2). A scheduled run claims a period with INSERT ... ON CONFLICT DO NOTHING RETURNING id — nothing returned means the period is already claimed. Partial on trigger=''scheduled'' on purpose: a customer regenerating the same range manually is legitimate and must not collide with this index.';


-- ════════════════════════════════════════════════════════════════════
-- 3. vrm.sites — seven new columns + one table-level CHECK (§5.3, §0.7)
-- ════════════════════════════════════════════════════════════════════
ALTER TABLE vrm.sites
  ADD COLUMN IF NOT EXISTS report_schedule text NOT NULL DEFAULT 'off'
    CHECK (report_schedule IN ('off', 'daily', 'weekly', 'monthly')),
  ADD COLUMN IF NOT EXISTS report_schedule_weekday smallint NOT NULL DEFAULT 1
    CHECK (report_schedule_weekday BETWEEN 1 AND 7),
  -- Capped at 28, not 31 — PLAN_PHASE17.md §3.2: so February never
  -- silently skips a month.
  ADD COLUMN IF NOT EXISTS report_schedule_day_of_month smallint NOT NULL DEFAULT 1
    CHECK (report_schedule_day_of_month BETWEEN 1 AND 28),
  ADD COLUMN IF NOT EXISTS report_schedule_hour smallint NOT NULL DEFAULT 6
    CHECK (report_schedule_hour BETWEEN 0 AND 23),
  -- NULL/empty -> falls back to the customer's own contact_email at send
  -- time (a later step). Third-party recipients: PLAN_PHASE17.md §0.6 Q5.
  ADD COLUMN IF NOT EXISTS report_recipients text[],
  -- The last successfully-generated SCHEDULED period's end date — not
  -- touched by a manual/admin run.
  ADD COLUMN IF NOT EXISTS report_last_period_end date,
  ADD COLUMN IF NOT EXISTS report_last_run_at timestamptz;

-- Oscar's decision, 2026-08-21 (PLAN_PHASE17.md §0.7): only a
-- source='vrm_api' site may ever carry a live schedule. This makes the
-- invalid state (a CSV-sourced site with report_schedule <> 'off')
-- UNREPRESENTABLE at the database layer — enforcement layer 1 of 3 (the
-- write path and the UI are the other two, built in later steps). Every
-- existing row passes trivially: report_schedule defaults to 'off' for
-- every row this migration touches, regardless of source.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint con
    JOIN pg_class rel ON rel.oid = con.conrelid
    JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
    WHERE nsp.nspname = 'vrm'
      AND rel.relname = 'sites'
      AND con.conname = 'sites_scheduled_reports_require_vrm_api'
  ) THEN
    ALTER TABLE vrm.sites
      ADD CONSTRAINT sites_scheduled_reports_require_vrm_api
      CHECK (report_schedule = 'off' OR source = 'vrm_api');
  END IF;
END $$;

COMMENT ON COLUMN vrm.sites.report_schedule IS
  'PLAN_PHASE17.md §3/§5.3. off (default — every site that existed before this migration) | daily | weekly | monthly. Only ever non-''off'' when source=''vrm_api'' — see the sites_scheduled_reports_require_vrm_api CHECK below (§0.7: a CSV-sourced site''s data is only as fresh as the last manual upload, so it can never be scheduled). Computed into a due/not-due decision by vrm_api/report_schedule.py (a later step), never read directly as a cron expression.';
COMMENT ON COLUMN vrm.sites.report_schedule_day_of_month IS
  'Capped at 28, not 31 (PLAN_PHASE17.md §3.2) — so a monthly schedule never silently skips February.';
COMMENT ON CONSTRAINT sites_scheduled_reports_require_vrm_api ON vrm.sites IS
  'Oscar''s decision, 2026-08-21 (PLAN_PHASE17.md §0.7): a CSV-sourced site''s data is only ever as fresh as the last manual upload, so it may never be scheduled — only source=''vrm_api'' sites can be. This is enforcement layer 1 of 3 (write-path and UI are the other two, later steps) and makes the invalid state unrepresentable regardless of what any application code does or fails to do.';


-- ════════════════════════════════════════════════════════════════════
-- 4. vrm.customers — one new column + one comment fix (§5.4)
-- ════════════════════════════════════════════════════════════════════
ALTER TABLE vrm.customers
  -- Applied by createSite() (a later step) to NEW sites only, and only
  -- when the new site's source='vrm_api' (§0.7) — never retroactively.
  -- 'off' by default: this migration does not change what any existing
  -- customer's sites do.
  ADD COLUMN IF NOT EXISTS default_report_schedule text NOT NULL DEFAULT 'off'
    CHECK (default_report_schedule IN ('off', 'daily', 'weekly', 'monthly'));

COMMENT ON COLUMN vrm.customers.default_report_schedule IS
  'PLAN_PHASE17.md §3.1/§5.4. Applied by createSite() (a later step) to NEW sites only, and only when the new site''s source=''vrm_api'' (§0.7 — a CSV-sourced site can never be scheduled regardless of this default). Never applied retroactively to existing sites; the bulk "apply to all sites" action (§3.7, a later step) is the explicit, opt-in way to do that.';

-- The `branding` column has existed since migration 012 ("(logo_url,
-- primary_color, contact block)") and has been completely dead ever
-- since — nothing reads it, nothing writes it. This updates the comment
-- to the real shape; the column itself (jsonb, no schema-level
-- constraint) is unchanged.
COMMENT ON COLUMN vrm.customers.branding IS
  'jsonb, shape documented (not enforced by a CHECK — migration 012''s original reasoning holds: it genuinely varies and shouldn''t need a migration per field) in PLAN_PHASE17.md §4.1: company_name, logo_storage_path, primary_color, contact_name, contact_email, contact_phone, website — every key optional. Existed since migration 012 and was completely dead until Phase 17: nothing read it, nothing wrote it. The ONLY reader is vrm_api/branding.py:resolve_branding() (a later step), which additionally gates on vrm.plan_limits.white_label and entitlement before ever honoring what''s stored here — a Starter customer''s populated branding is ignored, not merged. victron/weekly_report.py never receives this column''s raw value directly.';
