-- POINTER (2026-08-17): the REVISIT TRIGGER below fired — there is now a JS
-- frontend. The answer lives in migration 023's header and
-- PLAN_PHASE14.md §1.2, not here; this file's SQL body is unchanged below
-- because it has already been applied to the live database.
--
-- Migration 021: VRM Monitor customer portal — auth linkage on vrm.customers
--
-- Phase 13 (PLAN_PHASE13.md) turns VRM Monitor from a tool Oscar operates on
-- customers' behalf into a product customers log into. This migration adds
-- the columns that link a `vrm.customers` row to a Supabase Auth user. It
-- does NOT add RLS policies and does NOT touch `monitoring`, `public`, or
-- anything under `app.py`/`pages/` — those are untouched by this phase.
--
-- ── Why a soft pointer, not a foreign key (PLAN_PHASE13.md §1.3) ──────
-- `auth_user_id` deliberately has NO `REFERENCES auth.users(id)`. This
-- mirrors `vrm.sites.public_client_id`'s existing precedent (migration 012):
-- the `vrm` schema is designed to be dumpable into its own Supabase project
-- without cross-schema constraints to untangle. A dangling `auth_user_id` is
-- harmless — it just resolves to "this customer can't log in" — whereas an
-- `ON DELETE CASCADE` from `auth.users` would mean deleting a login deletes
-- the customer's telemetry history, which is categorically the wrong blast
-- radius for an auth housekeeping action.
--
-- ── Why 1:1 columns on the row, not a companion table ──────────────────
-- The relationship is one login per customer, by explicit product decision
-- (§1.3, non-goals §4: "Multiple users per customer"). A companion table
-- would add a join to the single hottest query in the app (resolve session
-- -> tenant) to model a relationship that will never be anything but 1:1.
-- The two partial unique indexes below are what actually prevent two
-- customers from sharing a login, since there is no FK doing it.
--
-- ── Why RLS policies are still deliberately absent ─────────────────────
-- `vrm.*` has been RLS-enabled-with-zero-policies since migration 012,
-- specifically so this moment wouldn't need a policy sprint. It still
-- doesn't: the portal talks to Supabase exclusively through
-- `database/supabase_client.py:get_client()` (service_role), which bypasses
-- RLS by definition, so policies here would protect nothing the app
-- actually does — they'd just be a second, unused door. Real tenant
-- isolation is enforced in application code, at the single choke point
-- `vrm_portal/db.py` (Phase 13 Step 2): every tenant-facing function takes
-- `customer_id` as its required first argument, and site-keyed operations
-- go through `assert_owns_site()`.
--
-- REVISIT TRIGGER: the moment anything other than this Streamlit process
-- talks to Supabase on a customer's behalf — a mobile app, a JS frontend, a
-- public API — per-user JWTs + real RLS policies become mandatory and this
-- decision must be reopened. Not before.
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice.

ALTER TABLE vrm.customers
  -- Soft pointer to auth.users(id) — see the "no FK" note above. Populated
  -- once Oscar sends an invite (Step 5) or links an existing auth user by
  -- hand (this step's own validation does the latter).
  ADD COLUMN IF NOT EXISTS auth_user_id uuid,
  -- The login email. Kept separate from contact_email: a customer's login
  -- and the address that receives their weekly report are not guaranteed
  -- to be the same person or inbox.
  ADD COLUMN IF NOT EXISTS auth_email   text,
  ADD COLUMN IF NOT EXISTS invited_at   timestamptz,
  ADD COLUMN IF NOT EXISTS activated_at timestamptz,
  -- Drives portal copy ("Your sites" vs "Your customers' sites") and which
  -- PLANS entries (vrm_portal/plans.py) are offered — mirrors the landing
  -- page's existing installer/owner account-type toggle.
  ADD COLUMN IF NOT EXISTS account_type text NOT NULL DEFAULT 'owner'
                             CHECK (account_type IN ('installer','owner')),
  -- NULL = unlimited (the 'fleet' plan). Enforced in vrm_portal/db.py, not
  -- here — a hand-negotiated deal just needs this value changed, not a
  -- migration. Defaulted from vrm_portal/plans.py:PLANS at customer-create
  -- time (Step 5), overridable by Oscar per customer.
  ADD COLUMN IF NOT EXISTS site_limit   int,
  -- Portal UI language for this customer's own dashboard. Confirmed default
  -- English (PLAN_PHASE13.md §0.3 Q2); admin views stay Spanish regardless
  -- of this column. 'en'/'es' only — mirrors report_language's own two-value
  -- vocabulary on vrm.sites (migration 012), not the fuller COUNTRIES set.
  ADD COLUMN IF NOT EXISTS ui_language  text NOT NULL DEFAULT 'en'
                             CHECK (ui_language IN ('es','en'));

-- Partial (WHERE ... IS NOT NULL) so customers who have never been invited
-- (auth_user_id/auth_email both NULL) don't collide with each other under a
-- plain UNIQUE constraint, which would treat every NULL as a duplicate of
-- every other NULL... except Postgres actually already treats NULLs as
-- distinct under UNIQUE, so the partial form here is belt-and-suspenders
-- clarity (and a smaller index) rather than a correctness requirement.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vrm_customers_auth_user
  ON vrm.customers (auth_user_id) WHERE auth_user_id IS NOT NULL;

-- lower(auth_email): email comparisons in this product are case-insensitive
-- everywhere else (Supabase Auth itself lowercases on sign-in), so this
-- index needs to match that or a same-address-different-case second invite
-- would silently create a second login for one inbox.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vrm_customers_auth_email
  ON vrm.customers (lower(auth_email)) WHERE auth_email IS NOT NULL;
