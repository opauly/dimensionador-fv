-- Migration 030: trial-ending reminder gate + a durable marker for a
-- trial that genuinely expired without a payment method on file.
--
-- Two real gaps found from a live test, 2026-08-29: (1) a customer whose
-- 7-day trial (created with no payment_method_id — PLAN_PHASE16.md's own
-- "card required upfront" intent is enforced by the SDK widget during
-- signup, not by ONVO's subscription object itself) ends with no card on
-- file just sits in ONVO's `trialing` status forever, since ONVO never
-- attempts a charge it has no card for — nothing in this product actively
-- revoked their access or told them it would happen. (2) there was no
-- "your trial ends tomorrow" notice at all, so a customer who forgot to
-- add a card got no warning before losing access.
--
-- One column, not a new table — same reasoning migration 027's own header
-- gives for `report_cap_notified_period_end`: "have I already notified
-- for THIS thing" is a single fact per subscription, not a log, and
-- `vrm.subscriptions` already IS the one row per live subscription this
-- gate needs. Lives on `vrm.subscriptions`, not `vrm.customers`, because
-- the fact being gated ("did we warn about THIS subscription's trial
-- ending") is a subscription-level fact — `trial_end` itself already
-- lives on this table, not on customers.
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice.

ALTER TABLE vrm.subscriptions
  ADD COLUMN IF NOT EXISTS trial_reminder_sent_at timestamptz;

COMMENT ON COLUMN vrm.subscriptions.trial_reminder_sent_at IS
  'PLAN_PHASE18.md-adjacent billing fix, 2026-08-29. When the "your trial ends tomorrow" reminder was sent for THIS subscription — NULL means never sent. Set once by vrm_api/billing.py:send_trial_ending_reminders(), which only ever sends when this is NULL and trial_end is within its lookahead window, so a subscription is reminded exactly once regardless of how many times the daily sweep runs.';

-- `billing_status` itself has no CHECK constraint to widen (confirmed:
-- migration 016/025 never added one) — `vrm.customers.billing_status` can
-- already hold any text value, including the new local-only
-- `'trial_expired'` value `apply_entitlements()` now writes for a
-- subscription that is `status='trialing'` in ONVO's own eyes but whose
-- `trial_end` has genuinely passed with no payment method on file.
-- Deliberately NOT one of ONVO's own status strings (§0.2b's closed
-- 7-value vocabulary) — this value never comes from ONVO and is never
-- compared against anything ONVO sends; it exists purely so this
-- product's own UI can tell "trial ended, access suspended, add a card"
-- apart from a genuinely still-live trial, which ONVO's raw `trialing`
-- status cannot distinguish on its own.
