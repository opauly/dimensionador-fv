-- 070: Finanzas — cuentas, categorías, movimientos de empresa y tipo de cambio
-- (PLAN_PHASE25_FINANZAS.md, fase 25.1).
--
-- Project money stays where it already lives (project_payments,
-- project_expenses, project_labor.advances). fin_transactions only holds the
-- money that is NOT a project's: company expenses, owner draws, other income
-- and transfers between accounts. The Finanzas page merges both into one view.
--
-- Additive and idempotent: safe to run twice.

CREATE TABLE IF NOT EXISTS fin_accounts (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name             text NOT NULL UNIQUE,
    currency         text NOT NULL CHECK (currency IN ('USD', 'CRC')),
    opening_balance  numeric(14,2) NOT NULL DEFAULT 0,   -- in the account's own currency
    opening_date     date,
    is_default       boolean NOT NULL DEFAULT false,     -- the USD account project money lands in
    active           boolean NOT NULL DEFAULT true,
    sort_order       int NOT NULL DEFAULT 0,
    created_at       timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fin_categories (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('company_expense', 'other_income', 'owner_draw')),
    active      boolean NOT NULL DEFAULT true,
    sort_order  int NOT NULL DEFAULT 0,
    created_at  timestamptz DEFAULT now(),
    UNIQUE (kind, name)
);

CREATE TABLE IF NOT EXISTS fin_transactions (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tx_date          date NOT NULL,
    kind             text NOT NULL
                         CHECK (kind IN ('company_expense', 'other_income', 'owner_draw', 'transfer')),
    account_id       uuid NOT NULL REFERENCES fin_accounts(id),
    to_account_id    uuid REFERENCES fin_accounts(id),        -- transfers only
    category_id      uuid REFERENCES fin_categories(id),
    description      text NOT NULL,
    vendor           text,
    currency         text NOT NULL CHECK (currency IN ('USD', 'CRC')),
    amount           numeric(14,2) NOT NULL CHECK (amount > 0),  -- in `currency`, always positive
    fx_rate          numeric(10,4),                            -- CRC per USD on tx_date
    amount_usd       numeric(12,2) NOT NULL,
    to_amount        numeric(14,2),                            -- transfers: what arrived, in the destination's currency
    notes            text,
    receipt_path     text,
    source           text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'quickbooks')),
    external_ref     text UNIQUE,                              -- dedupe key for imports
    created_at       timestamptz DEFAULT now(),
    CHECK (kind <> 'transfer' OR (to_account_id IS NOT NULL AND to_account_id <> account_id AND to_amount > 0))
);

CREATE INDEX IF NOT EXISTS fin_transactions_date_idx ON fin_transactions (tx_date);

CREATE TABLE IF NOT EXISTS fin_fx_rates (
    rate_date    date PRIMARY KEY,
    crc_per_usd  numeric(10,4) NOT NULL,
    source       text NOT NULL DEFAULT 'hacienda',  -- 'hacienda' | 'manual'
    created_at   timestamptz DEFAULT now()
);

-- Project money can now say which account it moved through, and project
-- expenses paid in colones keep their original amount. All nullable: NULL
-- account = the default USD account; NULL currency = USD.
ALTER TABLE project_payments
    ADD COLUMN IF NOT EXISTS account_id uuid REFERENCES fin_accounts(id);
ALTER TABLE project_expenses
    ADD COLUMN IF NOT EXISTS account_id uuid REFERENCES fin_accounts(id),
    ADD COLUMN IF NOT EXISTS currency text CHECK (currency IN ('USD', 'CRC')),
    ADD COLUMN IF NOT EXISTS amount_original numeric(14,2),
    ADD COLUMN IF NOT EXISTS fx_rate numeric(10,4);

-- ── Seeds ────────────────────────────────────────────────────────────────
INSERT INTO fin_accounts (name, currency, is_default, sort_order) VALUES
    ('BAC San José (USD)', 'USD', true, 1),
    ('Cuenta en colones (CRC)', 'CRC', false, 2)
ON CONFLICT (name) DO NOTHING;

INSERT INTO fin_categories (kind, name, sort_order) VALUES
    ('company_expense', 'Oficina', 1),
    ('company_expense', 'Software y suscripciones', 2),
    ('company_expense', 'Vehículo y combustible', 3),
    ('company_expense', 'Seguros', 4),
    ('company_expense', 'Contador y legal', 5),
    ('company_expense', 'Comisiones bancarias', 6),
    ('company_expense', 'Impuestos', 7),
    ('company_expense', 'Marketing', 8),
    ('company_expense', 'Herramientas', 9),
    ('company_expense', 'Capacitación', 10),
    ('company_expense', 'Teléfono e internet', 11),
    ('company_expense', 'Otros', 99),
    ('other_income', 'Mantenimientos', 1),
    ('other_income', 'Visitas técnicas', 2),
    ('other_income', 'Monitoreo', 3),
    ('other_income', 'Intereses', 4),
    ('other_income', 'Otros', 99),
    ('owner_draw', 'Retiro personal', 1),
    ('owner_draw', 'Pago de tarjetas', 2)
ON CONFLICT (kind, name) DO NOTHING;
