-- Migration 041: vrm.plan_limits.live_dashboard
--
-- Entitlement gate for the customer-facing Fleet Dashboard (`/app/dashboard`,
-- 2026-09-03) — the same feature that has existed admin-only at
-- `/admin/fleet` since Fleet Dashboard Phase 1-3. Same shape as
-- `white_label` (migration 026): a boolean per plan_key, resolved by
-- `lib/server/db/reportLimits.ts:getDashboardAllowed()` the identical way
-- `getWhiteLabelAllowed()` already resolves `white_label` there.
--
-- Oscar's decision (2026-09-03): Growth + Fleet only. Starter stays
-- report-only (PDF weekly/monthly, unchanged) — this becomes Growth's
-- headline upsell over Starter, the same tier boundary white_label already
-- draws. Worth noting: `lib/plans.ts`'s `PLANS.growth.accountTypes` is
-- `['installer']` only, so this feature is reachable only by installer
-- accounts, never a single-site `owner` subscriber, under today's plan
-- structure — not something this migration changes, just inherited from
-- how Growth/Fleet are already scoped.
--
-- Idempotent: `ADD COLUMN IF NOT EXISTS` and an `UPDATE` (not `INSERT`,
-- since every plan_key row already exists from migration 026) — safe to
-- run twice.

ALTER TABLE vrm.plan_limits
  ADD COLUMN IF NOT EXISTS live_dashboard boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN vrm.plan_limits.live_dashboard IS
  'Gates whether `/app/dashboard` (the customer-facing Fleet Dashboard: health scores, live PV/load/battery/SOC readings, and the 4 AI Insight anomaly checks) shows real content or the upgrade upsell for this tier. Not a UI condition alone — `app/api/pipeline/vrm-fleet/site-shape|site-savings` re-check it server-side too, same "hiding the editor is UX, never the control" rule `white_label` already follows (PLAN_PHASE17.md §4.2).';

UPDATE vrm.plan_limits SET live_dashboard = true WHERE plan_key IN ('growth', 'fleet');
