-- Migration 048: project_payments.onvo_commission_pct — stop lying by default
--
-- Phase 22 §1.10.3. project_payments.onvo_commission_pct has been NOT NULL
-- DEFAULT 0.024 since migration 020, and nothing in the codebase has ever
-- written or read that column, onvo_iva_pct, or net_deposited. That means
-- every existing row currently asserts a 2.4% ONVO card-processing
-- commission that nobody actually chose or charged. Phase 22 finally builds
-- the Pagos/ONVO UI that reads this column, so the data has to stop lying
-- before that UI ships.
--
-- Run in two gated halves — see PLAN_PHASE22_PROJECTS_JINJA.md §1.10.3 for
-- the full guardrails:
--
--   (a) is safe to run immediately and unconditionally: it only changes what
--       NEW rows default to, and touches no existing data.
--   (b) is a destructive backfill of EXISTING rows and must NOT run until a
--       human has reviewed scripts/audit_onvo_defaults.py's candidate list
--       and confirmed (or excluded) which historical payments, if any, were
--       genuinely taken via ONVO card. Do not run (b) blind.

-- (a) Stop future rows from inheriting a commission nobody chose. A payment
--     is a bank transfer until someone says otherwise.
ALTER TABLE project_payments ALTER COLUMN onvo_commission_pct SET DEFAULT 0;
ALTER TABLE project_payments ALTER COLUMN onvo_iva_pct         SET DEFAULT 0;

-- (b) Backfill only rows that provably were never classified by a human: the
--     exact default signature. Rows the new UI has touched
--     (net_deposited IS NOT NULL) are never modified, which also makes this
--     statement safely re-runnable.
UPDATE project_payments
   SET onvo_commission_pct = 0,
       onvo_iva_pct        = 0
 WHERE onvo_commission_pct = 0.024
   AND onvo_iva_pct  IS NULL
   AND net_deposited IS NULL;
