-- Phase 25.4 (adelantado) — gastos recurrentes (PLAN_PHASE25_FINANZAS.md).
--
-- A recurring rule (e.g. Google Workspace, every 1st, "Google Workspace [mes]")
-- creates its fin_transactions row by itself once the date arrives. Each
-- created row remembers its rule and month (recurring_id + period), and the
-- unique index makes it impossible to create the same month twice.
--
-- Safe to run more than once.

CREATE TABLE IF NOT EXISTS fin_recurring (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    timestamptz NOT NULL DEFAULT now(),
    name          text NOT NULL,
    kind          text NOT NULL DEFAULT 'company_expense'
                      CHECK (kind IN ('company_expense', 'owner_draw', 'other_income')),
    category_id   uuid REFERENCES fin_categories(id),
    account_id    uuid NOT NULL REFERENCES fin_accounts(id),
    amount        numeric(14,2) NOT NULL CHECK (amount > 0),   -- in the account's currency
    day_of_month  int NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    memo_template text NOT NULL,                               -- "[mes]" and "[año]" are filled in
    vendor        text,
    start_date    date NOT NULL DEFAULT CURRENT_DATE,
    end_date      date,
    active        boolean NOT NULL DEFAULT true
);

ALTER TABLE fin_transactions ADD COLUMN IF NOT EXISTS recurring_id uuid REFERENCES fin_recurring(id) ON DELETE SET NULL;
ALTER TABLE fin_transactions ADD COLUMN IF NOT EXISTS period       text;   -- 'YYYY-MM'
CREATE UNIQUE INDEX IF NOT EXISTS fin_transactions_recurring_period_uq
    ON fin_transactions (recurring_id, period) WHERE recurring_id IS NOT NULL;
