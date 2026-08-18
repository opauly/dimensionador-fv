-- Migration 023: `vrm.jobs` — background work for the Next.js portal + `vrm_api`
--
-- PLAN_PHASE14.md §2 Step 5. Numbered 023, not 022 as an earlier draft of
-- that plan guessed — 022 was already taken by
-- `022_project_contract_iva.sql` (unrelated Phase 6 work) by the time this
-- was written.
--
-- ── Why jobs exist at all (PLAN_PHASE14.md §1.6) ────────────────────────
-- Parsing a VRM CSV and rendering a report (Anthropic + Open-Meteo +
-- WeasyPrint) take seconds to a minute — long enough that coupling either
-- one to a single HTTP request also couples it to Vercel's and Render's
-- request-timeout budgets and to the customer's flaky wifi. `vrm_api`
-- answers a `POST /v1/ingest/*` or `POST /v1/reports` with `{job_id}`
-- immediately, does the real work in the background, and the caller polls
-- `GET /v1/jobs/{id}` (proxied and tenant-scoped by the Next.js server) for
-- the result. `params`/`result` are `jsonb` because a job's shape differs by
-- `kind`: an `ingest_preview` job's `result` is `victron/vrm_csv.py:
-- parse_export()`'s output (small — per-day rows, not the raw CSV, see that
-- module's own header comment) plus the derived `site_id`; an `ingest_commit`
-- job's `result` is an ingestion summary; a `report` job's `result` is
-- `{"storage_path": ...}` pointing at the rendered PDF in Supabase Storage.
--
-- ── Why in-process, not a real queue (Celery/RQ/Redis) ──────────────────
-- At first-customers scale a queue is infrastructure with no payoff: one
-- Render instance, a handful of concurrent uploads at most, and the actual
-- work (`victron/*.py`, unchanged) already runs fine as a plain Python
-- function call. `vrm_api` schedules jobs as FastAPI `BackgroundTasks`,
-- which Starlette runs on a bounded thread pool — real concurrency for
-- pandas/WeasyPrint's CPU-bound work without a broker to operate. The honest
-- cost, paid deliberately: a container restart loses any job that was
-- `running` at the time, with nothing to resume it from. `vrm_api`'s startup
-- sweep (`vrm_api/jobs.py:sweep_stale_jobs()`) fails any `running` job older
-- than 15 minutes with a message telling the caller to retry, so a restart
-- produces a clear failure instead of a spinner that never resolves. The
-- upgrade path — a real worker process reading this same table, or a queue —
-- is written down in PLAN_PHASE14.md §5 and deliberately not taken now.
--
-- ── `customer_id` is a real FK; `site_id` deliberately is NOT ───────────
-- `customer_id` always names a `vrm.customers` row that already exists by
-- the time a job is created (every endpoint resolves/validates it first —
-- `vrm_api/tenancy.py`), so `REFERENCES vrm.customers(id) ON DELETE CASCADE`
-- is safe and correct, same as `vrm.sites.customer_id` (migration 012).
-- `site_id` is plain `text` with no FK: an `ingest_preview` job for a brand
-- new site names a `site_id` that does not exist in `vrm.sites` yet — it is
-- only created if and when `ingest_commit` runs — so a hard FK here would
-- reject the exact row the preview step exists to produce.
--
-- ── The access model this table's callers must keep true ───────────────
-- (Recorded here, not just in code, because it is the answer to a revisit
-- trigger — see below — and that answer belongs on the migration that acts
-- on it, same as migration 021's own trigger note.) All Supabase access
-- happens in Next.js server code or in `vrm_api`; no Supabase credential of
-- any kind reaches a browser; `anon`/`authenticated` keep zero grants on
-- `vrm` (unchanged since migration 012 — nothing below alters that);
-- authorization is enforced at one typed choke point per process
-- (`victron-monitor/web/lib/server/db/` in Next.js,
-- `vrm_api/tenancy.py:assert_owns_site()` in the API) that both re-derive
-- ownership from `vrm.sites` independently rather than trusting each other.
-- Full reasoning: PLAN_PHASE14.md §1.2.
--
-- REVISIT TRIGGER (supersedes migration 021's own, see the pointer added to
-- that file's header): if a browser, a mobile app, or a third party ever
-- needs to query Supabase directly — realtime subscriptions, offline sync,
-- a public API — then granting `authenticated` on `vrm`, issuing per-user
-- JWTs, and writing RLS policies keyed on `auth.uid()` via
-- `vrm.customers.auth_user_id` must all happen together, as one change, with
-- a cross-tenant test suite. Never partially.
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice.

CREATE TABLE IF NOT EXISTS vrm.jobs (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id uuid        NOT NULL REFERENCES vrm.customers(id) ON DELETE CASCADE,
  -- See the header note above — deliberately not a FK into vrm.sites.
  site_id     text,
  kind        text        NOT NULL
                            CHECK (kind IN ('ingest_preview', 'ingest_commit', 'report')),
  status      text        NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'running', 'done', 'failed')),
  params      jsonb       NOT NULL DEFAULT '{}'::jsonb,
  result      jsonb,
  error       text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  started_at  timestamptz,
  finished_at timestamptz
);

-- Drives "my uploads / my reports" listings and a per-customer job count
-- (useful later for the Anthropic-spend watch PLAN_PHASE14.md §5 flags —
-- report jobs are the one thing in this table that costs real money per row).
CREATE INDEX IF NOT EXISTS idx_vrm_jobs_customer
  ON vrm.jobs USING btree (customer_id, created_at DESC);

-- Exactly the predicate sweep_stale_jobs() runs at startup. Partial on
-- status='running' because that is the only state the sweep ever queries —
-- 'queued'/'done'/'failed' jobs are never scanned by it, so indexing the
-- rows it never touches would just be dead weight (mirrors migration 012's
-- reasoning for its own alarm-events partial-ish expression index).
CREATE INDEX IF NOT EXISTS idx_vrm_jobs_running_started
  ON vrm.jobs USING btree (started_at) WHERE status = 'running';

ALTER TABLE vrm.jobs ENABLE ROW LEVEL SECURITY;
-- Zero policies, same as every other vrm.* table since migration 012 — see
-- that migration's header for why this is stronger than it looks: with
-- `anon`/`authenticated` holding no grant on the schema at all, there is no
-- privilege for a policy to police, so none is added purely for its own
-- sake. `vrm_api` and the Next.js server both talk to this table with the
-- secret/service_role key, which bypasses RLS by definition.

-- Table privileges follow migration 012's `ALTER DEFAULT PRIVILEGES IN
-- SCHEMA vrm GRANT ALL ON TABLES TO service_role` automatically for any new
-- table created by the same role; the explicit grant below is
-- belt-and-suspenders in case this migration is ever run by a different
-- role (e.g. directly as `postgres` from the SQL Editor).
GRANT ALL ON vrm.jobs TO service_role;

COMMENT ON TABLE vrm.jobs IS
  'Background work for vrm_api (PLAN_PHASE14.md §1.6): CSV ingestion preview/commit and report rendering, run in-process as FastAPI BackgroundTasks, not a real queue. See this migration''s header for the full reasoning and the access-model revisit trigger it now carries.';
COMMENT ON COLUMN vrm.jobs.site_id IS
  'Plain text, no FK: an ingest_preview job for a brand-new site names a site_id that does not exist in vrm.sites until (if) ingest_commit runs.';
COMMENT ON COLUMN vrm.jobs.params IS
  'The request body that created the job (customer_id/site_id/range/etc.) — kept for the audit trail and for a retry to reuse.';
COMMENT ON COLUMN vrm.jobs.result IS
  'Shape depends on kind: ingest_preview -> parse_export() output + derived site_id; ingest_commit -> ingestion summary; report -> {"storage_path": ...}.';
