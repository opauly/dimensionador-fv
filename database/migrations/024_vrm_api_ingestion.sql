-- Migration 024: VRM API ingestion — token-state columns, tenancy fix,
-- the Vault-backed token wrappers, and the audit column Step 4b needs
--
-- PLAN_PHASE15.md §7 Step 1 ("Migration 024 + Vault, proven end to end with
-- no UI"). This is schema only — no router, no UI, nothing under `vrm_api/`
-- beyond the tiny `vrm_api/secrets.py` wrapper module lands with this step.
-- The customer-facing connect/sync flow is Steps 4/5; this migration exists
-- so that flow has somewhere safe to put a customer's Victron VRM personal
-- access token before any of it is built.
--
-- ── 1. `vrm.customers`: token *state*, not just a revoked flag ──────────
-- Migration 012 added `vrm_token_revoked_at` but nothing ever set it, and it
-- alone can't say *why* a connection is dead or *when it last worked* — the
-- two things a "your VRM connection stopped working" banner (Step 6) and
-- Oscar's admin view both need. `vrm_token_last_checked_at`/`_last_ok_at`/
-- `_last_error` are written by Step 4's sync job on every call, not by this
-- migration (PLAN_PHASE15.md §1.3, §9).
--
-- ── 2. `vrm.sites`: sync bookkeeping, defaulted off ──────────────────────
-- `vrm_sync_enabled` defaults `false` so every existing row (all CSV-sourced
-- today) is unaffected — linking a site to the API is always an explicit
-- act, never an implicit consequence of this migration running.
--
-- ── 3. `vrm.sites.vrm_installation_id` UNIQUE -> UNIQUE (customer_id, ...) ─
-- Migration 012 called the installation id "globally unique." That held in
-- a world with one kind of customer. Phase 13/14 shipped two account types
-- (`vrm.customers.account_type IN ('installer','owner')`, migration 021): an
-- installer's VRM account can contain an installation that is *also*, quite
-- legitimately, one of our `owner` customers' own site. Both are real
-- `vrm.sites` rows for the same `idSite`. A global UNIQUE makes the second
-- one's ingest fail with a Postgres unique violation — and it can fail
-- *today*, on the CSV path, because `vrm_api/routers/ingest.py:_do_commit()`
-- already writes `vrm_installation_id` parsed from the export filename.
-- `UNIQUE (customer_id, vrm_installation_id) WHERE vrm_installation_id IS
-- NOT NULL` is strictly more permissive than the constraint it replaces, so
-- it cannot break an existing row. `site_id` (globally unique, referenced by
-- every child table) is untouched — this is a tenancy fix, not a rekey.
-- Full reasoning: PLAN_PHASE15.md §1.1.
--
-- ── 4. `vrm.jobs.kind` gains `'vrm_sync'` ─────────────────────────────────
-- Step 4's `POST /v1/vrm-sync` creates a job of this kind, run through the
-- same in-process `BackgroundTasks` model `ingest_preview`/`ingest_commit`/
-- `report` jobs already use (migration 023, `vrm_api/jobs.py`). No new job
-- machinery — one more value in an existing CHECK.
--
-- ── 5. The Vault design (PLAN_PHASE15.md §2 in full) ─────────────────────
-- Supabase Vault (`vault.create_secret`/`vault.update_secret`/the decrypting
-- view `vault.decrypted_secrets`) is a first-party feature enabled by
-- default on Supabase projects, confirmed still current (its pgsodium
-- backend was replaced, not deprecated, in March 2025) — this is what
-- migration 012's comment on `vrm_token_secret_id` originally assumed, and
-- that assumption is re-verified here, not re-guessed.
--
-- The obstacle: PostgREST (`database/supabase_client.py`, every `vrm_api`
-- module's only way to reach Postgres) can only route to schemas explicitly
-- exposed in the Data API settings, and `vault` is not exposed there — and
-- must never be, or every secret in the project becomes one PostgREST call
-- away from anything holding a key. So: three `SECURITY DEFINER` functions
-- live in `vrm` (already exposed) and are the *only* way any application
-- code touches Vault:
--
--   vrm.set_customer_vrm_token(p_customer_id uuid, p_token text)   -> void
--   vrm.read_customer_vrm_token(p_customer_id uuid)                -> text
--   vrm.clear_customer_vrm_token(p_customer_id uuid)               -> void
--
-- Hardening, each required and each actually implemented below (not just
-- asserted): `EXECUTE` is `REVOKE`d from `PUBLIC`, `anon`, `authenticated`
-- and `GRANT`ed only to `service_role` (a `SECURITY DEFINER` function with
-- the default `PUBLIC` execute grant is a textbook privilege-escalation
-- hole — Postgres grants EXECUTE to PUBLIC on every new function unless told
-- otherwise, so this is not optional even though `anon`/`authenticated` hold
-- zero grants on the `vrm` schema itself, belt-and-suspenders per
-- PLAN_PHASE15.md §2.2); `SET search_path = ''` with every identifier inside
-- fully schema-qualified, the standard `SECURITY DEFINER` hardening; the
-- Vault secret id NEVER leaves Postgres — `set_...` creates-or-updates the
-- secret AND writes `vrm.customers.vrm_token_secret_id`/`vrm_token_added_at`/
-- clears `vrm_token_revoked_at` in one statement, so `vrm_api` only ever
-- passes a `customer_id` and a token, never a vault id; `read_...` returns
-- `NULL`, never raises, when the customer has no *live* token (no secret, or
-- `vrm_token_revoked_at` is set) — so a sync of a disconnected customer is a
-- clean no-op, not an exception path; secrets are named deterministically
-- (`vrm_token:<customer_id>`) so an orphan is identifiable by inspection; and
-- `clear_...` actually `DELETE`s the `vault.secrets` row, not just the
-- pointer — disconnecting must destroy the credential, not just forget where
-- it was.
--
-- The honest cost, recorded rather than discovered later (PLAN_PHASE15.md
-- §2.3): Vault secrets do NOT survive a `pg_dump`/`pg_restore` into a new
-- Supabase project — the new project has a fresh root encryption key and
-- cannot decrypt copied ciphertext. This conflicts with migration 012's
-- stated goal that `vrm` stay "dumpable into its own Supabase project."
-- Accepted: a token is not derived data and can't be reconstructed anyway;
-- on such a move every customer simply reconnects, and the
-- `vrm_token_revoked_at`/reconnect flow this phase builds is already the
-- mechanism for that. No telemetry is lost — only the credential, which is
-- the correct thing to lose in a project move.
--
-- FALLBACK NOT TAKEN: PLAN_PHASE15.md §2.4 describes an envelope-encryption
-- fallback (AES-256-GCM, a key in `vrm_api`'s own env, ciphertext in a new
-- table) for use ONLY if Vault turns out unavailable on this project. Step
-- 1's validation (this migration + `tools/run_migration_024.py`) is what
-- proves Vault works here; if it doesn't, this header must be edited to say
-- so before that fallback is built — it is not built alongside this as a
-- hedge.
--
-- ── 6. `COMMENT ON`: three clarifications that don't change behaviour ────
-- `vrm.sites.source` (§1.4: "current path, not exclusive" — a csv_upload
-- site can be linked to the API at any time, and a CSV can still be
-- uploaded to an API-linked site as an escape hatch, §5.2); `vrm.daily_health`
-- (§5.3: why it's keyed `(site_id, date, dump_type)` and what
-- `victron/ingest.py` must do about the resulting duplicate-row trap once
-- Step 4 lands — the cleanup itself is Step 4's code change, not this
-- migration's); `vrm.customers.vrm_token_secret_id` (§2.3's pg_dump
-- portability caveat, so the next reader doesn't have to rediscover it).
--
-- ── 7. `vrm.ingestion_log.triggered_by` — added after the rest of this
--       plan, for Step 4b's admin fleet path (§3.3) ──────────────────────
-- `source` says WHICH PATH a row arrived by (`csv_upload`/`vrm_api`);
-- `triggered_by` says WHO/WHAT caused the write (`customer`/`admin`/
-- `schedule`) — independent axes once Oscar's own admin-fleet sync (Step 4b)
-- and a customer's own "Sync now" can both produce a `source='vrm_api'` row
-- for the same site. This is what keeps "why did this report look wrong"
-- (this table's own founding question, migration 012) answerable once two
-- actors can touch one site's data. Existing rows are backfilled to
-- `'admin'` — every row ingested so far came from the Streamlit operator
-- tool, run by Oscar. No `NOT NULL`/`DEFAULT` is added: Step 4/4b's ingest
-- code paths are what set this column going forward; this migration only
-- adds it and backfills history, so `victron/ingest.py`'s current,
-- unmodified insert keeps working (an omitted column is simply `NULL`).
--
-- ── Not done, and stated so nobody adds it ────────────────────────────────
-- No RLS policies: `anon`/`authenticated` hold zero grants on `vrm`
-- (unchanged since migration 012), so there is no privilege for a policy to
-- police (PLAN_PHASE14.md §1.2 rule 3). No new CHECK on `dump_type`/`source`
-- values beyond what already exists — `monitoring` schema parity is
-- migration 012's own founding constraint and isn't reopened here.
--
-- ── REVISIT TRIGGER ───────────────────────────────────────────────────────
-- If Victron ever ships per-installation token scoping, or an OAuth flow,
-- the `set_/read_/clear_` wrappers and the connect flow (Step 4/5) must be
-- revisited TOGETHER: a narrower credential changes PLAN_PHASE15.md §3.2's
-- third tenancy control from "we bind the installation ourselves" to "the
-- credential is already bound," and half-adopting it would leave both
-- mechanisms half-trusted.
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice.
-- Afterwards, verify with `python -m tools.run_migration_024`.


-- ════════════════════════════════════════════════════════════════════
-- 1. vrm.customers — token state (PLAN_PHASE15.md §1.3)
-- ════════════════════════════════════════════════════════════════════
ALTER TABLE vrm.customers
  ADD COLUMN IF NOT EXISTS vrm_token_last_checked_at timestamptz,
  ADD COLUMN IF NOT EXISTS vrm_token_last_ok_at      timestamptz,
  ADD COLUMN IF NOT EXISTS vrm_token_last_error       text;


-- ════════════════════════════════════════════════════════════════════
-- 2. vrm.sites — sync bookkeeping (PLAN_PHASE15.md §1.3)
-- ════════════════════════════════════════════════════════════════════
ALTER TABLE vrm.sites
  ADD COLUMN IF NOT EXISTS vrm_last_synced_at  timestamptz,
  ADD COLUMN IF NOT EXISTS vrm_last_sync_error text,
  -- Defaults false: every existing row is CSV-sourced today, and linking to
  -- the API is always an explicit act (Step 4/5's connect flow), never an
  -- implicit side effect of this migration running.
  ADD COLUMN IF NOT EXISTS vrm_sync_enabled    boolean NOT NULL DEFAULT false;


-- ════════════════════════════════════════════════════════════════════
-- 3. vrm.sites.vrm_installation_id: global UNIQUE -> per-customer UNIQUE
--    (PLAN_PHASE15.md §1.1)
-- ════════════════════════════════════════════════════════════════════
-- Migration 012 declared `vrm_installation_id bigint UNIQUE` inline, with no
-- explicit CONSTRAINT name, so Postgres assigned the default
-- `sites_vrm_installation_id_key`. Rather than assume that name held (the
-- same caution migration 011 took for an unnamed CHECK it had to replace),
-- look it up by definition and drop whatever it's actually called.
DO $$
DECLARE
  c_name text;
BEGIN
  SELECT con.conname INTO c_name
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
  WHERE nsp.nspname = 'vrm'
    AND rel.relname = 'sites'
    AND con.contype = 'u'
    AND pg_get_constraintdef(con.oid) ILIKE '%vrm_installation_id%'
    AND pg_get_constraintdef(con.oid) NOT ILIKE '%customer_id%';

  IF c_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE vrm.sites DROP CONSTRAINT %I', c_name);
  END IF;
END $$;

-- Partial (WHERE ... IS NOT NULL): a site that has never synced/uploaded
-- from a filename carrying an idSite has NULL here, and NULLs must not
-- collide with each other the way two customers' real installation ids
-- must not collide across customers. Strictly more permissive than the
-- constraint it replaces, so no existing row can violate it.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vrm_sites_customer_installation
  ON vrm.sites (customer_id, vrm_installation_id)
  WHERE vrm_installation_id IS NOT NULL;


-- ════════════════════════════════════════════════════════════════════
-- 4. vrm.jobs.kind: add 'vrm_sync' (PLAN_PHASE15.md §6.1)
-- ════════════════════════════════════════════════════════════════════
DO $$
DECLARE
  c_name text;
BEGIN
  SELECT con.conname INTO c_name
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
  WHERE nsp.nspname = 'vrm'
    AND rel.relname = 'jobs'
    AND con.contype = 'c'
    AND pg_get_constraintdef(con.oid) ILIKE '%ingest_preview%';

  IF c_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE vrm.jobs DROP CONSTRAINT %I', c_name);
  END IF;
END $$;

ALTER TABLE vrm.jobs
  ADD CONSTRAINT jobs_kind_check
  CHECK (kind IN ('ingest_preview', 'ingest_commit', 'report', 'vrm_sync'));


-- ════════════════════════════════════════════════════════════════════
-- 5. The Vault wrapper functions (PLAN_PHASE15.md §2.2)
-- ════════════════════════════════════════════════════════════════════
-- `SET search_path = ''` means every identifier below must be fully
-- schema-qualified (vrm.customers, vault.*) — that IS the hardening, not
-- a style preference: an unqualified name under an empty search_path can
-- only resolve via pg_catalog (always implicitly searched), which is
-- exactly what stops a same-named object planted in a schema this
-- function's caller controls from being resolved instead of the real one.

CREATE OR REPLACE FUNCTION vrm.set_customer_vrm_token(p_customer_id uuid, p_token text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_existing_secret_id uuid;
  v_secret_id           uuid;
  -- Deterministic name so an orphaned vault.secrets row (e.g. the pointer on
  -- vrm.customers got cleared some other way) is identifiable by inspection
  -- rather than being an anonymous ciphertext blob.
  v_secret_name         text := 'vrm_token:' || p_customer_id::text;
BEGIN
  SELECT vrm_token_secret_id INTO v_existing_secret_id
  FROM vrm.customers
  WHERE id = p_customer_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'vrm.set_customer_vrm_token: no such customer %', p_customer_id;
  END IF;

  IF v_existing_secret_id IS NOT NULL THEN
    -- Reconnect: update the existing secret in place rather than creating a
    -- second one and orphaning the first.
    PERFORM vault.update_secret(v_existing_secret_id, p_token, v_secret_name);
    v_secret_id := v_existing_secret_id;
  ELSE
    v_secret_id := vault.create_secret(p_token, v_secret_name);
  END IF;

  -- The vault id never leaves this function: `vrm_api` passed a token in,
  -- gets nothing back, and the pointer + timestamps are written here, in the
  -- same statement, so there is no window where vrm.customers.vrm_token_secret_id
  -- and the actual vault.secrets row can disagree because a caller forgot a
  -- second write.
  UPDATE vrm.customers
  SET vrm_token_secret_id  = v_secret_id,
      vrm_token_added_at   = now(),
      vrm_token_revoked_at = NULL
  WHERE id = p_customer_id;
END;
$$;

CREATE OR REPLACE FUNCTION vrm.read_customer_vrm_token(p_customer_id uuid)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_secret_id uuid;
  v_token     text;
BEGIN
  -- "No live token" is deliberately one case, not two: no secret at all, OR
  -- the customer disconnected (vrm_token_revoked_at is set). Either way a
  -- sync job calling this must see a clean NULL and skip, not an exception
  -- — PLAN_PHASE15.md §2.2. This also means an unknown p_customer_id quietly
  -- returns NULL rather than raising, unlike set_/clear_ below: read_ has no
  -- state to corrupt by being permissive here, and a sync job for a
  -- customer that doesn't exist is already impossible upstream (the job row
  -- has a real FK to vrm.customers, migration 023).
  SELECT vrm_token_secret_id INTO v_secret_id
  FROM vrm.customers
  WHERE id = p_customer_id
    AND vrm_token_revoked_at IS NULL;

  IF v_secret_id IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT decrypted_secret INTO v_token
  FROM vault.decrypted_secrets
  WHERE id = v_secret_id;

  RETURN v_token;
END;
$$;

CREATE OR REPLACE FUNCTION vrm.clear_customer_vrm_token(p_customer_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_secret_id uuid;
BEGIN
  SELECT vrm_token_secret_id INTO v_secret_id
  FROM vrm.customers
  WHERE id = p_customer_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'vrm.clear_customer_vrm_token: no such customer %', p_customer_id;
  END IF;

  IF v_secret_id IS NOT NULL THEN
    -- Actually destroy the credential, not just the pointer to it — a
    -- disconnect must be real. NULLing vrm_token_secret_id alone would leave
    -- the ciphertext (and, if the root key were ever compromised, the
    -- plaintext) sitting in vault.secrets indefinitely.
    DELETE FROM vault.secrets WHERE id = v_secret_id;
  END IF;

  UPDATE vrm.customers
  SET vrm_token_secret_id  = NULL,
      vrm_token_revoked_at = now()
  WHERE id = p_customer_id;
END;
$$;

-- Postgres grants EXECUTE to PUBLIC on every new function by default —
-- these explicit REVOKEs are the actual hardening, not a formality. Without
-- them, a SECURITY DEFINER function is a textbook privilege-escalation hole:
-- anyone able to reach PostgREST could call it directly and read or destroy
-- any customer's token, unrelated to whatever vrm_api's own tenancy checks
-- say. anon/authenticated hold zero grants on the vrm schema itself
-- (migration 012), which already blocks them via schema USAGE alone — the
-- REVOKEs below are the belt-and-suspenders half of that, in case this
-- schema's grants are ever loosened without this file being re-read.
REVOKE ALL ON FUNCTION vrm.set_customer_vrm_token(uuid, text)   FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION vrm.read_customer_vrm_token(uuid)        FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION vrm.clear_customer_vrm_token(uuid)       FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION vrm.set_customer_vrm_token(uuid, text)   TO service_role;
GRANT EXECUTE ON FUNCTION vrm.read_customer_vrm_token(uuid)        TO service_role;
GRANT EXECUTE ON FUNCTION vrm.clear_customer_vrm_token(uuid)       TO service_role;


-- ════════════════════════════════════════════════════════════════════
-- 6. Comments — clarify meaning, no behaviour change (PLAN_PHASE15.md §7.6)
-- ════════════════════════════════════════════════════════════════════
COMMENT ON COLUMN vrm.sites.source IS
  'The path this site''s data currently arrives by — NOT an exclusive mode. A csv_upload site can be linked to source=''vrm_api'' at any time (PLAN_PHASE15.md §1.4/§5.2), and a CSV can still be uploaded to a vrm_api-linked site as an escape hatch when the API is down; the more recent upload/sync simply wins per date (vrm.energy_daily is keyed (site_id, date), not (site_id, date, dump_type) — migration 012). Do not infer exclusivity from the column name or add a CHECK that would enforce it.';

COMMENT ON TABLE vrm.daily_health IS
  'Keyed (site_id, date, dump_type) — NOT (site_id, date) — for schema parity with monitoring.daily_health (migration 012); do not change the key, that parity is what lets one report reader serve both schemas. Consequence: the first vrm_api sync of a date that already has a csv_upload health row produces two rows for one day, and database/vrm_report_db.py:bucket_health_days() dedups by keeping the HIGHEST-scoring row, which would silently flatter a mixed-source site''s health score. victron/ingest.py deletes the other dump_type''s row for the same (site_id, date) after every write (PLAN_PHASE15.md §5.3, Step 4) so exactly one row per site per day exists in practice — this comment records the reasoning; the cleanup code is what actually enforces it.';

COMMENT ON COLUMN vrm.customers.vrm_token_secret_id IS
  'Pointer into Supabase Vault (vault.secrets) — never the token itself. Set/read/cleared exclusively through vrm.set_customer_vrm_token / vrm.read_customer_vrm_token / vrm.clear_customer_vrm_token (migration 024); no other code path may touch vault.* on this column''s behalf. Vault secrets do NOT survive a pg_dump/pg_restore into a new Supabase project (the new project has a fresh root encryption key and cannot decrypt copied ciphertext) — this conflicts with this schema''s original "dumpable into its own project" goal (migration 012) and is accepted: a token is not derived data, and on a project move every customer simply reconnects (PLAN_PHASE15.md §2.3).';


-- ════════════════════════════════════════════════════════════════════
-- 7. vrm.ingestion_log.triggered_by (PLAN_PHASE15.md §3.3, added after the
--    rest of this plan for Step 4b's admin fleet path)
-- ════════════════════════════════════════════════════════════════════
-- No NOT NULL/DEFAULT: Step 4/4b's ingest code paths set this explicitly
-- going forward (CSV upload from Streamlit or /admin -> 'admin'; a
-- customer's own CSV upload or "Sync now" -> 'customer'; a scheduled sync,
-- if Step 7 is built -> 'schedule'). Leaving it nullable with no default
-- means victron/ingest.py's current, UNMODIFIED insert keeps writing rows
-- exactly as it does today (an omitted column is simply NULL) — this
-- migration must not require any change to that file to keep CSV ingest
-- working, per PLAN_PHASE15.md's own hard constraint.
ALTER TABLE vrm.ingestion_log
  ADD COLUMN IF NOT EXISTS triggered_by text
    CHECK (triggered_by IN ('customer', 'admin', 'schedule'));

-- Every row ingested before this migration came from the Streamlit operator
-- tool (pages/06_vrm_monitor.py), run by Oscar — i.e. 'admin', in this
-- column's vocabulary. Re-running this UPDATE on an already-backfilled
-- database is a no-op (WHERE triggered_by IS NULL matches nothing once
-- every row has a value), which is what makes it safe to leave in an
-- idempotent migration rather than a one-time script.
UPDATE vrm.ingestion_log
SET triggered_by = 'admin'
WHERE triggered_by IS NULL;

COMMENT ON COLUMN vrm.ingestion_log.triggered_by IS
  'WHO/WHAT caused this write — independent of source (WHICH PATH). customer: the customer''s own CSV upload or "Sync now". admin: Oscar via pages/06_vrm_monitor.py or the Next.js /admin fleet panel. schedule: Step 7''s scheduled sync, if built. Backfilled to ''admin'' for every pre-migration-024 row (all of which came from the Streamlit operator tool). PLAN_PHASE15.md §3.3/§5.4.';
