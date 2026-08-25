-- Migration 027: one durable column for Cap B's "notify once per billing
-- period" gate — PLAN_PHASE17.md §0.6 Q7, §8 Step 8.
--
-- Q7's recommendation is explicit: send ONE notification email per customer
-- per billing period when they first hit the scheduled-run cap, never one
-- per skipped run. That needs a durable "have I already notified for THIS
-- period" flag that survives for as long as a billing period does — up to
-- ~30 days for a monthly plan.
--
-- `vrm.rate_limits` (migration 025) was the obvious first choice — it
-- already exists, and `vrm.increment_rate_limit()` is exactly the "atomic
-- upsert-and-return, only the first caller sees 1" primitive this needs.
-- It is the WRONG choice: `POST /v1/billing/prune-signups` (migration 025's
-- own Step 7 sweep) deletes any `rate_limits` row whose `window_start` is
-- more than `_RATE_LIMIT_RETENTION` (2 days) old, unconditionally — a
-- policy that is entirely correct for Cap A's own hour/day buckets and
-- entirely wrong for a ~30-day billing period. A cap-notification row keyed
-- there would be pruned on day 3 of the period, silently resetting the gate
-- and sending a second (third, fourth, ...) email for the same period —
-- exactly the "flood them" outcome Q7 says not to do. Found and fixed
-- during Step 8's own build, before it ever shipped.
--
-- One column, not a new table: `vrm.customers` already IS the one row per
-- customer this gate needs, and "the last billing period we notified this
-- customer about" is a single fact, not a log. `NULL` means "never
-- notified" — every existing customer starts there, no backfill needed.
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice.

ALTER TABLE vrm.customers
  ADD COLUMN IF NOT EXISTS report_cap_notified_period_end date;

COMMENT ON COLUMN vrm.customers.report_cap_notified_period_end IS
  'PLAN_PHASE17.md §0.6 Q7 / §8 Step 8 — the period_end (Cap B''s own billing-period window, vrm_api/report_limits.py:resolve_billing_period()) of the most recent billing period this customer was sent the "you''ve reached your scheduled report limit" notice for. NULL = never notified. Compared for equality against the CURRENT period''s own end date by vrm_api/report_delivery.py:notify_cap_reached_once() — a match means "already sent this period, skip"; a non-match sends and updates this column. A plain durable column, not vrm.rate_limits (that table''s own 2-day prune sweep would silently reset a ~30-day gate — see this migration''s own header for why that was tried first and rejected).';
