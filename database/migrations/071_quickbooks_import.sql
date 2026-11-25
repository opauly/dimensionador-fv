-- Phase 25.2 — QuickBooks import (PLAN_PHASE25_FINANZAS.md).
--
-- The Journal export is staged first (fin_import_batches / _jobs / _items),
-- Oscar reviews the suggested classification, and only then is it written to
-- the real tables. Every row written by an import carries import_batch_id, so a
-- whole import can be undone in one go (projects cascade to their payments and
-- expenses).
--
-- Safe to run more than once.

-- ── Where imported rows come from ────────────────────────────────────────
ALTER TABLE projects          ADD COLUMN IF NOT EXISTS title           text;
ALTER TABLE projects          ADD COLUMN IF NOT EXISTS source          text NOT NULL DEFAULT 'app';
ALTER TABLE projects          ADD COLUMN IF NOT EXISTS external_ref    text;
ALTER TABLE projects          ADD COLUMN IF NOT EXISTS import_batch_id uuid;
ALTER TABLE project_payments  ADD COLUMN IF NOT EXISTS external_ref    text;
ALTER TABLE project_payments  ADD COLUMN IF NOT EXISTS import_batch_id uuid;
ALTER TABLE project_expenses  ADD COLUMN IF NOT EXISTS external_ref    text;
ALTER TABLE project_expenses  ADD COLUMN IF NOT EXISTS import_batch_id uuid;
ALTER TABLE fin_transactions  ADD COLUMN IF NOT EXISTS import_batch_id uuid;

CREATE INDEX IF NOT EXISTS projects_import_batch_idx         ON projects (import_batch_id);
CREATE INDEX IF NOT EXISTS project_payments_import_batch_idx ON project_payments (import_batch_id);
CREATE INDEX IF NOT EXISTS project_expenses_import_batch_idx ON project_expenses (import_batch_id);
CREATE INDEX IF NOT EXISTS fin_transactions_import_batch_idx ON fin_transactions (import_batch_id);

-- ── Staging ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fin_import_batches (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    timestamptz NOT NULL DEFAULT now(),
    filename      text,
    status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'committed', 'undone')),
    committed_at  timestamptz,
    summary       jsonb NOT NULL DEFAULT '{}'::jsonb   -- QuickBooks totals, for the cuadre
);

-- One per QuickBooks invoice: becomes a completed project, other income,
-- is matched to a project that already exists in the app, or is skipped.
CREATE TABLE IF NOT EXISTS fin_import_jobs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id      uuid NOT NULL REFERENCES fin_import_batches(id) ON DELETE CASCADE,
    job_key       text NOT NULL,
    invoice_no    text,
    invoice_date  date,
    customer      text NOT NULL,
    description   text,
    total_usd     numeric(12,2) NOT NULL DEFAULT 0,
    iva_usd       numeric(12,2) NOT NULL DEFAULT 0,
    action        text NOT NULL DEFAULT 'project'
                      CHECK (action IN ('project', 'income', 'existing', 'skip')),
    existing_project_id uuid,
    title         text,
    UNIQUE (batch_id, job_key)
);

-- One per money movement (a payment slice, or one expense line with its share of IVA).
CREATE TABLE IF NOT EXISTS fin_import_items (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id      uuid NOT NULL REFERENCES fin_import_batches(id) ON DELETE CASCADE,
    external_ref  text NOT NULL,
    tx_date       date NOT NULL,
    qb_type       text NOT NULL,            -- Payment / Expense
    qb_account    text,
    payee         text,
    memo          text,
    amount_usd    numeric(12,2) NOT NULL,
    kind          text NOT NULL CHECK (kind IN ('client_payment', 'project_expense', 'company_expense',
                                                'owner_draw', 'other_income', 'skip')),
    job_key       text,                     -- client_payment / project_expense
    rubro         text,                     -- project_expense
    category_id   uuid REFERENCES fin_categories(id),
    confidence    text NOT NULL DEFAULT 'baja' CHECK (confidence IN ('alta', 'baja', 'ninguna')),
    reason        text,
    reviewed      boolean NOT NULL DEFAULT false,
    UNIQUE (batch_id, external_ref)
);
CREATE INDEX IF NOT EXISTS fin_import_items_batch_idx ON fin_import_items (batch_id, tx_date);
