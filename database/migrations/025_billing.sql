-- Migration 025: ONVO billing + public signup — the schema half of Phase 16
-- Step 1
--
-- PLAN_PHASE16.md §3 in full, §8 Step 1. Schema and seed data ONLY — no
-- router, no vrm_api/onvo.py or vrm_api/billing.py client code, no
-- frontend. Those are Steps 2+. All new objects live in the `vrm` schema
-- (already exposed to PostgREST, migration 012), same house style as
-- migration 024: idempotent (`CREATE TABLE IF NOT EXISTS` /
-- `ADD COLUMN IF NOT EXISTS`), header records reasoning, not just DDL.
--
-- §3's own count ("six new tables ... five new columns") undercounts
-- against §3's own detailed sub-sections (§0.2b's own errata note in the
-- coder's brief says to trust the detail over the summary line). What is
-- actually built below, and is the authoritative list: SEVEN new tables
-- (§3.1 vrm.plans, §3.2 vrm.billing_customers, §3.3 vrm.subscriptions,
-- §3.4 vrm.subscription_invoices, §3.5 vrm.billing_events, §3.7
-- vrm.signup_requests, §3.8 vrm.rate_limits), FOUR new columns on
-- vrm.customers (§3.6: site_limit_source, billing_status,
-- provisioning_state, origin), and one COMMENT ON correction (§3.6, last
-- bullet). Recorded here rather than silently "fixed" so the discrepancy
-- is visible to the next reader instead of just disappearing.
--
-- ── 1. vrm.plans — the sellable catalogue, joined to a real ONVO price ──
-- One row per (plan_key, billing_interval, currency, mode) that is or was
-- ever sellable. Not a TS constant (lib/plans.ts keeps labels/marketing
-- only) because an onvo_price_id differs between test and live mode,
-- prices change over time, and a customer already on a retired price must
-- keep rendering correctly (`active = false`, still referenced by a live
-- vrm.subscriptions row) — a TS constant cannot express "retired but still
-- honored." `site_limit` here is what a subscription GRANTS; the entitlement
-- writer (Step 2, PLAN_PHASE16.md §4.5) is the only thing that copies it
-- into vrm.customers.site_limit, and only when site_limit_source='plan'
-- (§3.1/§3.6). `self_serve` defaults FALSE — fail-closed, so a
-- hand-inserted or future-migration plan row is never on the public signup
-- form by accident (§3.1). No CHECK on plan_key, same reasoning
-- vrm.customers.plan already uses (migration 012/021): pricing is
-- marketing-owned, changes faster than a migration.
--
-- ── 2. vrm.billing_customers — one row per customer that ever touched
--    billing (§3.2) ──────────────────────────────────────────────────────
-- 1:1 with vrm.customers (PK = customer_id, ON DELETE CASCADE, same
-- pattern vrm.jobs/vrm.sites already use for a real ownership FK — migration
-- 012/023). billing_address is jsonb, mirroring ONVO's own shape verbatim
-- (displayed and round-tripped, never computed on) rather than six columns,
-- so an ONVO field addition never needs a migration. billing_email is
-- deliberately a THIRD email, distinct from auth_email (login) and
-- contact_email (report recipient) — migration 021 already established
-- those two are not the same person; the address that gets a receipt is a
-- third, even when, for a self-serve signup, all three start out identical.
--
-- ── 3. vrm.subscriptions — the mirror (§3.3) ─────────────────────────────
-- `status` carries ONVO's RAW status string with NO CHECK constraint, on
-- purpose, per §3.9's explicit rule — even though Step 0 (§0.2b finding 4)
-- has since closed the full vocabulary (active, past_due, canceled, unpaid,
-- incomplete, incomplete_expired, trialing), a CHECK built on today's known
-- values turns "ONVO added a status we hadn't seen" into a failed sync and
-- a customer stuck in stale state — the worst failure mode for a billing
-- mirror. The entitlement mapping (Step 2, §4.5) lives in code, where an
-- unknown value can be handled loudly and safely instead of fatally.
-- `raw jsonb` keeps the last full ONVO payload verbatim — a production
-- support question answerable without a column-and-redeploy cycle.
--
-- Live-row uniqueness: §3.3 specifies a partial `UNIQUE (customer_id) WHERE
-- status IN (<entitled-or-pending set>)`, "the exact set comes from Step 0",
-- with an explicit named fallback if that turns out impractical:
-- `UNIQUE (customer_id) WHERE canceled_at IS NULL`. Step 0 (§0.2b finding 4)
-- DID close the status vocabulary, but which of those seven values should
-- count as "still blocks a second subscription" is an entitlement-policy
-- judgement (e.g. does a repeatedly-failed `unpaid` subscription block a
-- fresh signup, or should the customer be allowed to start over?) that
-- belongs with Step 2's status->entitlement mapping table, not with this
-- migration guessing it. This migration therefore takes the plan's own
-- named fallback: `UNIQUE (customer_id) WHERE canceled_at IS NULL` —
-- `canceled_at` is stamped exactly once, synchronously, by ONVO's own
-- cancel call (§0.2b finding 12), so this is a real, observable boundary,
-- not a guess. Revisit alongside Step 2/3 if the entitlement mapping wants
-- a narrower set (e.g. excluding `incomplete_expired`).
--
-- ── 4. vrm.subscription_invoices — mirrored renewals (§3.4) ─────────────
-- Read-only from the customer's perspective; populated by reconcile only
-- (Step 2), never by a webhook payload (§0.5's read-through principle).
--
-- ── 5. vrm.billing_events — append-only receipt log (§3.5) ──────────────
-- EVERY webhook delivery gets a row, including ones that fail the shared-
-- secret check (`secret_ok = false`, payload retained) — the only way an
-- attempted forgery is visible at all. No unique constraint on anything
-- from the payload: ONVO's webhook body carries no event id and no
-- timestamp (§0.2b finding 9), so there is nothing to dedupe on — duplicate
-- delivery is harmless under read-through, which is the point. `status`
-- carries no CHECK, per §3.9's blanket rule for this migration (even though
-- this vocabulary, unlike vrm.subscriptions.status, is entirely our own and
-- would otherwise be a reasonable CHECK candidate — the letter of §3.9 is
-- followed here rather than re-litigated).
--
-- ── 6. vrm.customers — four new columns (§3.6) ───────────────────────────
-- Every one of the three CHECK'd columns below defaults to the value that
-- makes EVERY EXISTING ROW behave exactly as it does today — the same
-- protective-default trick migration 024 used for vrm_sync_enabled:
--   - site_limit_source DEFAULT 'manual': stops a real bug before it can
--     happen — the moment Step 2's entitlement writer starts running, the
--     next reconcile would otherwise silently overwrite a hand-negotiated
--     site_limit (migration 021) with the plan's default. 'plan' is set
--     only when a customer subscribes through the portal, or at row-
--     creation time for a self-serve signup (Step 5.5) — never here.
--   - provisioning_state DEFAULT 'active': every existing/admin-created row
--     is a real tenant already; 'pending_subscription' is written only by
--     the signup verify handler (Step 5.5), a state this migration creates
--     zero rows in.
--   - origin DEFAULT 'admin': every row that exists before this migration
--     came from Oscar (invite/admin-create); 'self_serve' is written only
--     by the signup flow (Step 5.5).
-- billing_status is a small, DERIVED, denormalized cache of the entitlement
-- decision, written only by Step 2's apply_entitlements() — no default
-- needed/assumed beyond NULL ("never touched billing"), and no CHECK here
-- either (final vocabulary lands with Step 2, same reasoning as
-- vrm.subscriptions.status).
--
-- ── 7. vrm.signup_requests — staging table for unverified signups (§3.7) ─
-- The core structural decision of the signup design: an unverified signup
-- never touches vrm.customers at all. token_hash (sha256 of a 32-byte
-- random token) is stored — the token itself NEVER is, same reasoning
-- Supabase's own hashed_token uses and the same direction this repo already
-- applies to Vault-stored VRM tokens: a database dump must not be a set of
-- working account-creation links. ip_hash is sha256(ip + SIGNUP_IP_SALT),
-- never the raw IP — many of these rows will be bots or changed-their-mind
-- visitors, not customers; a salted hash is enough for rate-limiting and
-- abuse forensics without being a log of who visited (§3.7). Not built here:
-- the pruning cron (Step 7) and SIGNUP_IP_SALT itself (Step 5.5/§6.1) — this
-- migration only creates somewhere safe for that data to land.
--
-- ── 8. vrm.rate_limits — generic, durable counter (§3.8) ─────────────────
-- A fixed-window counter, deliberately the simple algorithm (no token
-- bucket) — at this product's scale, letting 2x the limit through at a
-- window boundary in the worst case is fine. Composite PK
-- (bucket, key, window_start) IS the uniqueness the upsert relies on.
-- `vrm.increment_rate_limit()` below is the "single upsert, RETURNING
-- count" §3.8 describes, exposed as a callable function so it is one
-- atomic round trip through PostgREST (the only way any application code —
-- lib/server/ratelimit.ts, Step 6.6 — or this migration's own validation
-- script can reach it: PostgREST's own upsert semantics replace a row
-- wholesale, they cannot express "count = count + 1" as a single
-- server-side statement). Deliberately NOT `SECURITY DEFINER` — §3.9
-- forbids new SECURITY DEFINER functions in this migration ("nothing in
-- this phase stores a credential", unlike migration 024's Vault wrappers),
-- and none is needed here: PostgREST always calls this as `service_role`,
-- which already holds ALL on every vrm.* table (migration 012's
-- `ALTER DEFAULT PRIVILEGES`), so a plain SECURITY INVOKER function works.
-- The REVOKE/GRANT pair below is still added, belt-and-suspenders, matching
-- migration 024's discipline even though anon/authenticated already hold
-- zero grants on the vrm schema itself.
--
-- ── What this migration deliberately does NOT do (§3.9) ─────────────────
-- No RLS policies (anon/authenticated hold zero grants on vrm — nothing to
-- police; vrm.signup_requests is written by the service-role key from
-- server-only code, never by anon — the public /signup route is public at
-- the HTTP layer, not the database layer). No SECURITY DEFINER functions.
-- No CHECK on any `status` or `plan_key` column. No backfill that invents a
-- subscription for an existing customer. No change to any existing row's
-- provisioning_state/origin/site_limit_source beyond the DEFAULT itself —
-- `ALTER TABLE ... ADD COLUMN ... DEFAULT` is the entire migration for
-- vrm.customers, and every existing customer keeps behaving exactly as
-- they do today (verified by tools/run_migration_025.py).
--
-- vrm.plans is intentionally left EMPTY by this file — seeding the four
-- real rows (Starter/Growth x monthly/annual) against live ONVO
-- product/price ids is `tools/seed_onvo_plans.py`'s job (PLAN_PHASE16.md
-- §0.6 Q1/Q13/Q14), run once, after this migration is applied.
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice.
-- Afterwards, verify with `python -m tools.run_migration_025`.


-- ════════════════════════════════════════════════════════════════════
-- 1. vrm.plans (§3.1)
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.plans (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  -- No CHECK: matches lib/plans.ts:PlanKey today, but pricing is
  -- marketing-owned and changes faster than a migration (same reasoning
  -- as vrm.customers.plan, migration 012/021).
  plan_key         text        NOT NULL,
  billing_interval text        NOT NULL
                                 CHECK (billing_interval IN ('month', 'year')),
  currency         text        NOT NULL,
  amount_minor     bigint      NOT NULL,
  mode             text        NOT NULL
                                 CHECK (mode IN ('test', 'live')),
  onvo_product_id  text        NOT NULL,
  onvo_price_id    text        NOT NULL,
  -- NULL = unlimited, same convention as vrm.customers.site_limit
  -- (migration 021).
  site_limit       int,
  account_types    text[]      NOT NULL,
  -- Fail-closed default: a plan row is NOT on the public /signup form
  -- unless someone deliberately said so (§3.1).
  self_serve       boolean     NOT NULL DEFAULT false,
  active           boolean     NOT NULL DEFAULT true,
  sort_order       int         NOT NULL DEFAULT 0,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (onvo_price_id)
);

-- A retired price row (active=false) stays unique-by-history; only the
-- currently-sellable price per (plan_key, interval, currency, mode) must be
-- singular — a customer already on a retired price keeps their own
-- vrm.subscriptions.onvo_price_id pointing at it (§3.1).
CREATE UNIQUE INDEX IF NOT EXISTS idx_vrm_plans_sellable
  ON vrm.plans (plan_key, billing_interval, currency, mode)
  WHERE active;

CREATE INDEX IF NOT EXISTS idx_vrm_plans_self_serve
  ON vrm.plans (mode, self_serve, active)
  WHERE self_serve AND active;

ALTER TABLE vrm.plans ENABLE ROW LEVEL SECURITY;
GRANT ALL ON vrm.plans TO service_role;

COMMENT ON TABLE vrm.plans IS
  'The sellable catalogue and its join to a real ONVO product/price (PLAN_PHASE16.md §3.1). One row per (plan_key, billing_interval, currency, mode) that is or was ever sellable — a retired row (active=false) is kept, not deleted, because a customer already subscribed to it must keep rendering correctly. site_limit here is what a paid subscription GRANTS; vrm.customers.site_limit is what canAddSite() actually ENFORCES; vrm_api/billing.py:apply_entitlements() (Step 2) is the only thing that copies one to the other, and only when vrm.customers.site_limit_source = ''plan''.';
COMMENT ON COLUMN vrm.plans.self_serve IS
  'May a stranger buy this from /signup with no session (PLAN_PHASE16.md §0.6 Q14)? Defaults false — fail-closed. Enforced server-side in the public plan-list query AND again in the subscribe endpoint when the subscriber is provisioning_state=''pending_subscription'' (§3.1) — an EXISTING customer changing plans is not restricted by it (Oscar can hand-place someone on a non-self-serve plan).';


-- ════════════════════════════════════════════════════════════════════
-- 2. vrm.billing_customers (§3.2)
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.billing_customers (
  customer_id                uuid        PRIMARY KEY
                                           REFERENCES vrm.customers(id) ON DELETE CASCADE,
  onvo_customer_id           text        NOT NULL UNIQUE,
  mode                       text        NOT NULL,
  billing_name               text,
  billing_email              text,
  -- Mirrors ONVO's own shape verbatim ({city,country,line1,line2,
  -- postalCode,state}) — displayed and round-tripped, never computed on,
  -- so an ONVO field addition never needs a migration (§3.2).
  billing_address            jsonb       NOT NULL DEFAULT '{}'::jsonb,
  default_payment_method_id  text,
  pm_brand                   text,
  pm_last4                   text,
  pm_exp_month                int,
  pm_exp_year                 int,
  last_synced_at             timestamptz,
  created_at                 timestamptz NOT NULL DEFAULT now(),
  updated_at                 timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE vrm.billing_customers ENABLE ROW LEVEL SECURITY;
GRANT ALL ON vrm.billing_customers TO service_role;

COMMENT ON TABLE vrm.billing_customers IS
  'One row per vrm.customers that has ever touched billing (PLAN_PHASE16.md §3.2) — 1:1, keyed by customer_id, cascade-deleted with the customer. billing_email is deliberately a THIRD email, distinct from vrm.customers.auth_email (login) and contact_email (report recipient) — for a self-serve signup all three start out identical but remain three columns, never aliased.';


-- ════════════════════════════════════════════════════════════════════
-- 3. vrm.subscriptions — the mirror (§3.3)
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.subscriptions (
  id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id           uuid        NOT NULL REFERENCES vrm.customers(id) ON DELETE CASCADE,
  onvo_subscription_id  text        NOT NULL UNIQUE,
  mode                  text        NOT NULL,
  -- Resolved from onvo_price_id via vrm.plans; NULL if unrecognized — the
  -- sync must never fail just because a price predates this table or was
  -- never seeded (§3.3).
  plan_key              text,
  onvo_price_id         text,
  billing_interval      text,
  currency              text,
  amount_minor          bigint,
  -- ONVO's RAW status string. NO CHECK — see this migration's header.
  status                text        NOT NULL,
  cancel_at_period_end  boolean     NOT NULL DEFAULT false,
  cancel_at             timestamptz,
  canceled_at           timestamptz,
  current_period_start  timestamptz,
  current_period_end    timestamptz,
  trial_start           timestamptz,
  trial_end             timestamptz,
  latest_invoice_id     text,
  latest_invoice_status text,
  -- The last full payload as ONVO returned it — not laziness, an
  -- integration against an API whose full response shape isn't fully known
  -- (§3.3).
  raw                   jsonb       NOT NULL DEFAULT '{}'::jsonb,
  last_synced_at        timestamptz NOT NULL,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vrm_subscriptions_customer
  ON vrm.subscriptions USING btree (customer_id, created_at DESC);

-- One customer, at most one non-canceled subscription — the database's own
-- backstop for §5.4's application-level duplicate guard. See this
-- migration's header for why this is canceled_at IS NULL (the plan's own
-- named fallback) rather than an explicit status IN (...) list.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vrm_subscriptions_one_live_per_customer
  ON vrm.subscriptions (customer_id)
  WHERE canceled_at IS NULL;

ALTER TABLE vrm.subscriptions ENABLE ROW LEVEL SECURITY;
GRANT ALL ON vrm.subscriptions TO service_role;

COMMENT ON TABLE vrm.subscriptions IS
  'The read-through mirror of an ONVO subscription (PLAN_PHASE16.md §3.3, §0.5). Written ONLY by vrm_api/billing.py:reconcile_customer() (Step 2) — never by applying a webhook payload directly. status has no CHECK constraint on purpose: an unrecognized value must be a loud, safe log line in the entitlement mapping, never a failed sync.';
COMMENT ON COLUMN vrm.subscriptions.status IS
  'ONVO''s raw status string, no CHECK (see table comment). Closed vocabulary observed live at Step 0 (PLAN_PHASE16.md §0.2b finding 4): active, past_due, canceled, unpaid, incomplete, incomplete_expired, trialing — but ONVO can add a value with no notice, which is exactly why this stays unconstrained.';
COMMENT ON INDEX vrm.idx_vrm_subscriptions_one_live_per_customer IS
  'PLAN_PHASE16.md §3.3''s own named fallback (canceled_at IS NULL) rather than an explicit status IN (...) enumeration — which of the seven known statuses should still block a second subscription is an entitlement-policy judgement that belongs with Step 2''s status->entitlement mapping, not this migration. canceled_at is stamped exactly once, synchronously, by ONVO''s own cancel call (§0.2b finding 12), so this is a real boundary, not a guess.';


-- ════════════════════════════════════════════════════════════════════
-- 4. vrm.subscription_invoices — mirrored renewals (§3.4)
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.subscription_invoices (
  id                     uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id            uuid        NOT NULL REFERENCES vrm.customers(id) ON DELETE CASCADE,
  subscription_id        uuid        REFERENCES vrm.subscriptions(id) ON DELETE CASCADE,
  onvo_invoice_id        text        NOT NULL UNIQUE,
  status                 text,
  currency               text,
  total_minor            bigint,
  subtotal_minor         bigint,
  original_total_minor   bigint,
  period_start           timestamptz,
  period_end             timestamptz,
  attempt_count          int,
  last_payment_attempt   timestamptz,
  next_payment_attempt   timestamptz,
  payment_intent_id      text,
  raw                    jsonb       NOT NULL DEFAULT '{}'::jsonb,
  created_at             timestamptz NOT NULL DEFAULT now(),
  last_synced_at         timestamptz
);

CREATE INDEX IF NOT EXISTS idx_vrm_subscription_invoices_customer
  ON vrm.subscription_invoices USING btree (customer_id, period_start DESC);
CREATE INDEX IF NOT EXISTS idx_vrm_subscription_invoices_subscription
  ON vrm.subscription_invoices USING btree (subscription_id, period_start DESC);

ALTER TABLE vrm.subscription_invoices ENABLE ROW LEVEL SECURITY;
GRANT ALL ON vrm.subscription_invoices TO service_role;

COMMENT ON TABLE vrm.subscription_invoices IS
  'Mirrored renewals/invoices (PLAN_PHASE16.md §3.4). Read-only from the customer''s perspective. Populated by vrm_api/billing.py:reconcile_customer() (Step 2) only, never by a webhook payload directly (§0.5).';


-- ════════════════════════════════════════════════════════════════════
-- 5. vrm.billing_events — append-only receipt log (§3.5)
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.billing_events (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  received_at     timestamptz NOT NULL DEFAULT now(),
  event_type      text,
  payload         jsonb       NOT NULL,
  secret_ok       boolean     NOT NULL,
  -- Resolved during processing, both nullable — an unmatched event
  -- (e.g. from the Solar Design Tool's unrelated ONVO traffic on the same
  -- account) is normal, never dropped, never an error (§4.2).
  customer_id     uuid        REFERENCES vrm.customers(id) ON DELETE SET NULL,
  subscription_id text,
  -- 'received' | 'applied' | 'ignored' | 'error' — NO CHECK, per this
  -- migration's blanket "no CHECK on status" rule (§3.9), even though this
  -- vocabulary is our own, not ONVO's.
  status          text        NOT NULL DEFAULT 'received',
  processed_at    timestamptz,
  error           text
);

CREATE INDEX IF NOT EXISTS idx_vrm_billing_events_received
  ON vrm.billing_events USING btree (received_at DESC);
-- Exactly what §4.4's sweeper scans: rows stuck in 'error' get retried.
CREATE INDEX IF NOT EXISTS idx_vrm_billing_events_error
  ON vrm.billing_events (received_at) WHERE status = 'error';

ALTER TABLE vrm.billing_events ENABLE ROW LEVEL SECURITY;
GRANT ALL ON vrm.billing_events TO service_role;

COMMENT ON TABLE vrm.billing_events IS
  'Append-only receipt log for every ONVO webhook delivery (PLAN_PHASE16.md §3.5) — including ones that fail the shared-secret check (secret_ok=false, payload retained), the only way an attempted forgery is visible at all. No unique constraint on anything from the payload: ONVO''s webhook body carries no event id and no timestamp, so there is nothing to dedupe on. Cap/prune separately (Step 7) so a flood cannot fill this table.';


-- ════════════════════════════════════════════════════════════════════
-- 6. vrm.signup_requests — staging table for unverified signups (§3.7)
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.signup_requests (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Stored lowercased by the application layer — the index below assumes it.
  email         text        NOT NULL,
  -- sha256 of a 32-byte random token. The token itself is NEVER stored.
  token_hash    text        NOT NULL UNIQUE,
  -- Company or personal name, as typed; the slug is derived at redemption
  -- (Step 5.5), not here.
  name          text        NOT NULL,
  account_type  text        NOT NULL
                              CHECK (account_type IN ('installer', 'owner')),
  -- A UI preselect only, re-validated at subscribe time — never trusted
  -- as-is (§3.1's self_serve enforcement happens again downstream).
  plan_id       uuid        REFERENCES vrm.plans(id) ON DELETE SET NULL,
  ui_language   text        NOT NULL DEFAULT 'en'
                              CHECK (ui_language IN ('en', 'es')),
  -- sha256(ip + SIGNUP_IP_SALT). Never the raw IP.
  ip_hash       text,
  -- Truncated to 200 chars by the application layer — diagnostics only.
  user_agent    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  -- Set exactly once, atomically, at redemption.
  consumed_at   timestamptz,
  -- The row this became, once redeemed. Diagnostics + support only.
  customer_id   uuid        REFERENCES vrm.customers(id) ON DELETE SET NULL
);

-- Rate-limit lookups (§3.7/§3.8's "this table is the rate-limit substrate
-- too" — counting rows in a window).
CREATE INDEX IF NOT EXISTS idx_vrm_signup_requests_email
  ON vrm.signup_requests (lower(email));
CREATE INDEX IF NOT EXISTS idx_vrm_signup_requests_created
  ON vrm.signup_requests (created_at);

ALTER TABLE vrm.signup_requests ENABLE ROW LEVEL SECURITY;
GRANT ALL ON vrm.signup_requests TO service_role;

COMMENT ON TABLE vrm.signup_requests IS
  'Staging table for an unverified public signup (PLAN_PHASE16.md §3.7, §0.6 Q6). The core structural decision of the signup design: an unverified signup never creates a vrm.customers row, a Supabase auth user, or any ONVO object. Not a queue, not an audit log — pruned aggressively by Step 7''s cron (unconsumed rows past expires_at+7d, consumed rows past consumed_at+30d). Written exclusively by server-only code with the service-role key; the public /signup route is public at the HTTP layer only, never the database layer.';
COMMENT ON COLUMN vrm.signup_requests.token_hash IS
  'sha256 of a 32-byte random token. The token itself is NEVER stored — same reasoning Supabase''s own hashed_token uses: a database dump must not be a set of working account-creation links. The token exists only in the verification email and the URL the visitor clicks.';
COMMENT ON COLUMN vrm.signup_requests.ip_hash IS
  'sha256(ip + SIGNUP_IP_SALT), never the raw IP — many of these rows are bots or changed-their-mind visitors, not customers. Enough for rate-limiting and abuse forensics without being a log of who visited. Rotating SIGNUP_IP_SALT resets the rate-limit history — acceptable, worth knowing.';


-- ════════════════════════════════════════════════════════════════════
-- 7. vrm.rate_limits — generic, durable counter (§3.8)
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.rate_limits (
  -- e.g. 'signup_email' | 'signup_ip' | 'signup_global' | 'onvo_webhook'
  bucket       text        NOT NULL,
  -- The hashed/normalized subject; '' for a global bucket.
  key          text        NOT NULL,
  -- Timestamp truncated to the window (a FIXED window, not sliding —
  -- deliberately the simple algorithm, §3.8).
  window_start timestamptz NOT NULL,
  count        int         NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket, key, window_start)
);

ALTER TABLE vrm.rate_limits ENABLE ROW LEVEL SECURITY;
GRANT ALL ON vrm.rate_limits TO service_role;

COMMENT ON TABLE vrm.rate_limits IS
  'A generic, durable, fixed-window counter (PLAN_PHASE16.md §3.8) — replaces an in-process counter, which would be near-useless on a serverless Next.js deployment where each invocation may be a fresh process. Incremented exclusively through vrm.increment_rate_limit(), a single atomic upsert-and-return. Pruned by the same Step 7 cron that prunes vrm.signup_requests.';

-- The "single upsert (ON CONFLICT ... DO UPDATE SET count = count + 1
-- RETURNING count)" §3.8 describes, exposed as a callable function so it is
-- ONE atomic round trip through PostgREST — the only way lib/server/
-- ratelimit.ts (Step 6.6) or vrm_api's own webhook rate limit (§6.5) can
-- reach it, since PostgREST's own upsert semantics replace a row wholesale
-- and cannot express "count = count + 1" as a single server-side statement.
-- Deliberately NOT SECURITY DEFINER (§3.9 forbids a new one in this
-- migration, and none is needed: PostgREST always calls this as
-- service_role, which already holds ALL on every vrm.* table via
-- migration 012's ALTER DEFAULT PRIVILEGES).
CREATE OR REPLACE FUNCTION vrm.increment_rate_limit(
  p_bucket text, p_key text, p_window_start timestamptz
) RETURNS int
LANGUAGE sql
AS $$
  INSERT INTO vrm.rate_limits (bucket, key, window_start, count)
  VALUES (p_bucket, p_key, p_window_start, 1)
  ON CONFLICT (bucket, key, window_start)
  DO UPDATE SET count = vrm.rate_limits.count + 1
  RETURNING count;
$$;

-- Belt-and-suspenders, matching migration 024's discipline, even though
-- anon/authenticated already hold zero grants on the vrm schema itself.
REVOKE ALL ON FUNCTION vrm.increment_rate_limit(text, text, timestamptz) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION vrm.increment_rate_limit(text, text, timestamptz) TO service_role;

COMMENT ON FUNCTION vrm.increment_rate_limit(text, text, timestamptz) IS
  'Atomic upsert-and-return for vrm.rate_limits (PLAN_PHASE16.md §3.8) — one round trip, so a check and an increment can never race. Not SECURITY DEFINER: PostgREST always calls this as service_role, which already holds ALL on vrm.rate_limits.';


-- ════════════════════════════════════════════════════════════════════
-- 8. vrm.customers — four new columns (§3.6)
-- ════════════════════════════════════════════════════════════════════
ALTER TABLE vrm.customers
  -- Stops a real bug: once Step 2's entitlement writer runs, the next
  -- reconcile would otherwise silently overwrite a hand-negotiated
  -- site_limit (migration 021). Default 'manual' protects every existing
  -- row by construction — the entitlement writer must not touch site_limit
  -- unless this is 'plan'.
  ADD COLUMN IF NOT EXISTS site_limit_source text NOT NULL DEFAULT 'manual'
    CHECK (site_limit_source IN ('manual', 'plan')),
  -- A small, DERIVED, denormalized cache of the entitlement decision,
  -- written only by Step 2's apply_entitlements() — exists so
  -- /admin/customers and the portal banner can render without joining and
  -- re-deriving. No CHECK: final vocabulary lands with Step 2, same
  -- reasoning as vrm.subscriptions.status.
  ADD COLUMN IF NOT EXISTS billing_status text,
  -- 'active' = a real tenant (the default — every existing/admin-created
  -- row is unaffected). 'pending_subscription' = an email-verified signup
  -- that has not yet produced an entitled subscription; written by exactly
  -- two things: the signup verify handler (sets it) and
  -- apply_entitlements() (clears it, §4.5 rule 8).
  ADD COLUMN IF NOT EXISTS provisioning_state text NOT NULL DEFAULT 'active'
    CHECK (provisioning_state IN ('pending_subscription', 'active')),
  -- Did a human vet this account? 'admin' (default — every existing row)
  -- vs 'self_serve' (written only by the signup flow, Step 5.5). Never used
  -- in an authorization decision — diagnostics/admin-filter only.
  ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'admin'
    CHECK (origin IN ('admin', 'self_serve'));

COMMENT ON COLUMN vrm.customers.plan IS
  'Free text, still no CHECK (pricing is marketing-owned and changes faster than a migration — migration 012). Written by three things as of PLAN_PHASE16.md: (a) an admin, via /admin/customers (human override, always legitimate); (b) vrm_api/billing.py:apply_entitlements() (Step 2), for any customer with site_limit_source=''plan''; (c) the signup verification handler (Step 5.5), which INSERTS a brand-new row with plan=''trial'' and never touches it again. plan=''trial'' now means one of two different things, distinguished by provisioning_state, not by this column: a legacy/hand-created customer with no billing relationship at all (provisioning_state=''active''), or a self-serve signup that verified their email but has not yet produced an entitled subscription (provisioning_state=''pending_subscription'', site_limit=0). Do not "simplify" these into one state.';
COMMENT ON COLUMN vrm.customers.site_limit_source IS
  'PLAN_PHASE16.md §3.6. ''manual'' (default) = a human (Oscar, via /admin) set site_limit by hand and vrm_api/billing.py:apply_entitlements() (Step 2) must NEVER overwrite it. ''plan'' = site_limit tracks vrm.plans.site_limit for the customer''s current subscription; set at portal-subscribe time or at signup-verify time (Step 5.5) — a signup row created with the ''manual'' default would have site_limit frozen at 0 forever, because the entitlement writer would politely refuse to raise it. That is exactly the bug this default direction exists to prevent.';
COMMENT ON COLUMN vrm.customers.billing_status IS
  'PLAN_PHASE16.md §3.6. A cache of a cache: derived from vrm.subscriptions (the real mirror) by vrm_api/billing.py:apply_entitlements() (Step 2) only. Exists so /admin/customers and the portal banner can render without joining and re-deriving. Never written by anything else, never authoritative.';
COMMENT ON COLUMN vrm.customers.provisioning_state IS
  'PLAN_PHASE16.md §3.6. ''active'' (default) = a real tenant. ''pending_subscription'' = an email-verified signup (Step 5.5) with no entitled subscription yet — can sign in (resolveRole() requires active=true, a separate column with a separate meaning), but requireCustomer() sends it straight to /app/billing and site_limit is 0. Written by exactly two things: the signup verify handler (sets it) and apply_entitlements() (clears it, on the first reconcile that observes an entitled subscription — §4.5 rule 8, logged as signup.promoted). Plus one admin escape hatch (Step 6) for "their card works but the promotion never fired."';
COMMENT ON COLUMN vrm.customers.origin IS
  'PLAN_PHASE16.md §3.6. ''admin'' (default) = Oscar invited/created this account by hand. ''self_serve'' = created via the public /signup flow (Step 5.5). Cheap, permanent, answers "did a human vet this account?" and feeds /admin/customers'' pending-signups filter (Step 6). Never used in an authorization decision.';
