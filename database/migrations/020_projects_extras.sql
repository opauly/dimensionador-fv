-- Migration 020: Projects module — migration trail + INGRESOS extras
--
-- The five `project_*` tables (projects, project_payments, project_expenses,
-- project_labor, project_invoice_items) have existed live in Supabase, empty,
-- since they were first added straight to schema.sql — with no migration
-- file behind them. This migration closes that gap: it re-declares all five
-- with CREATE TABLE IF NOT EXISTS, verbatim from schema.sql (a clean no-op
-- against the live DB), so from here on the projects tables have a migration
-- trail like everything else in this repo. It then adds the genuinely new
-- objects needed to start building the Projects module (Phase 6):
--
--   * project_extras — INGRESOS "Extras" (additional work orders billed on
--     top of the base contract). Deliberately its own table, not a reuse of
--     project_invoice_items (the factura electrónica *decomposition* of the
--     base contract) and not client-side only — see PLAN_PHASE6.md §1.1 for
--     the full reasoning. total_with_iva mirrors project_expenses' generated
--     column exactly, so "never write a generated column" applies uniformly.
--   * created_at on project_payments, project_expenses, project_labor and
--     project_invoice_items — projects already has one; these four didn't.
--   * a partial unique index on projects(proposal_id) enforcing "only one
--     project per proposal" while still allowing unlimited proposal-less
--     (manually created) projects — see PLAN_PHASE6.md §6.
--   * an index on project_extras(project_id), matching every other
--     project_* child table.
--
-- Run once in the Supabase SQL Editor. Safe to run multiple times — every
-- statement is IF NOT EXISTS / idempotent.

-- ── Pre-existing tables, re-declared verbatim (no-op against the live DB) ──

CREATE TABLE IF NOT EXISTS projects (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id         uuid REFERENCES proposals(id),
    version_id          uuid REFERENCES proposal_versions(id),
    created_at          timestamptz DEFAULT now(),
    client_name         text NOT NULL,
    system_type         text NOT NULL,
    status              text NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'completed', 'paused', 'cancelled')),
    contract_usd        numeric(10,2) NOT NULL,
    contract_iva_rate   numeric(4,3) NOT NULL DEFAULT 0,
    notes               text
);

CREATE TABLE IF NOT EXISTS project_payments (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    payment_number      int NOT NULL,
    amount_usd          numeric(10,2) NOT NULL,
    paid                boolean NOT NULL DEFAULT false,
    paid_date           date,
    bank_account        text,
    onvo_commission_pct numeric(5,4) NOT NULL DEFAULT 0.024,
    onvo_iva_pct        numeric(5,4),
    net_deposited       numeric(10,2),
    notes               text
);

CREATE TABLE IF NOT EXISTS project_expenses (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category        text NOT NULL
                        CHECK (category IN ('banco','equipo','materiales','mano_de_obra','viaticos','extras')),
    description     text NOT NULL,
    amount_usd      numeric(10,2) NOT NULL,
    iva_rate        numeric(4,3) NOT NULL DEFAULT 0,
    total_with_iva  numeric(10,2) GENERATED ALWAYS AS (amount_usd * (1 + iva_rate)) STORED,
    paid            boolean NOT NULL DEFAULT false,
    expense_date    date,
    budgeted_usd    numeric(10,2),
    receipt_path    text,
    notes           text
);

CREATE TABLE IF NOT EXISTS project_labor (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    worker_name     text NOT NULL,
    role            text,
    quoted_amount   numeric(10,2) NOT NULL DEFAULT 0,
    advances        jsonb NOT NULL DEFAULT '[]',
    total_advanced  numeric(10,2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS project_invoice_items (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    description text NOT NULL,
    category    text NOT NULL CHECK (category IN ('equipos','materiales','servicios')),
    iva_rate    numeric(4,3) NOT NULL DEFAULT 0,
    amount_usd  numeric(10,2) NOT NULL,
    iva_amount  numeric(10,2) GENERATED ALWAYS AS (amount_usd * iva_rate) STORED,
    total_usd   numeric(10,2) GENERATED ALWAYS AS (amount_usd * (1 + iva_rate)) STORED
);

-- ── New: INGRESOS "Extras" (PLAN_PHASE6.md §1.1) ───────────────────────────

CREATE TABLE IF NOT EXISTS project_extras (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    description     text NOT NULL,
    amount_usd      numeric(10,2) NOT NULL,          -- ex-IVA
    iva_rate        numeric(4,3) NOT NULL DEFAULT 0,
    total_with_iva  numeric(10,2) GENERATED ALWAYS AS (amount_usd * (1 + iva_rate)) STORED,
    approved        boolean NOT NULL DEFAULT true,
    extra_date      date,
    notes           text,
    created_at      timestamptz DEFAULT now()
);

-- ── New: created_at on the four child tables that were missing one ─────────
-- (projects already has one; not touched here.)

ALTER TABLE project_payments      ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();
ALTER TABLE project_expenses      ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();
ALTER TABLE project_labor         ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();
ALTER TABLE project_invoice_items ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();

-- ── New: one project per proposal, unlimited proposal-less projects ────────
-- REQUIREMENTS §3.2 "only one version per proposal can be promoted". The
-- partial WHERE clause is what lets manually-created projects (proposal_id
-- IS NULL — see PLAN_PHASE6.md §6) exist in any number without tripping this.

CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_proposal_unique
    ON projects(proposal_id) WHERE proposal_id IS NOT NULL;

-- ── New: index on project_extras, matching every other project_* child table ─

CREATE INDEX IF NOT EXISTS idx_project_extras_project_id ON project_extras(project_id);
