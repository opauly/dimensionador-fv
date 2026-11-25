-- 074: Invoices sueltos (Finanzas) — cobros a clientes sin un proyecto en la app.
--
-- An invoice has detail lines, is in USD or CRC, takes partial payments and
-- closes itself when the balance reaches 0. It can later be linked to a
-- project: its payments then move into project_payments (and the rest stays
-- as a pending payment there), so the money lives in one place only.
--
-- Additive and idempotent: safe to run twice.

CREATE TABLE IF NOT EXISTS fin_invoices (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    number        int NOT NULL UNIQUE,
    client_id     uuid REFERENCES clients(id) ON DELETE SET NULL,
    client_name   text NOT NULL,
    issue_date    date NOT NULL,
    due_date      date,
    currency      text NOT NULL CHECK (currency IN ('USD', 'CRC')),
    iva_rate      numeric(5,2) NOT NULL DEFAULT 0,       -- percent, e.g. 13
    subtotal      numeric(14,2) NOT NULL DEFAULT 0,      -- in `currency`
    iva           numeric(14,2) NOT NULL DEFAULT 0,
    total         numeric(14,2) NOT NULL DEFAULT 0,
    fx_rate       numeric(10,4),                         -- CRC per USD on issue_date (CRC invoices)
    notes         text,
    status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'paid', 'void', 'linked')),
    project_id    uuid REFERENCES projects(id) ON DELETE SET NULL,
    linked_at     timestamptz,
    created_at    timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fin_invoice_lines (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id   uuid NOT NULL REFERENCES fin_invoices(id) ON DELETE CASCADE,
    description  text NOT NULL,
    quantity     numeric(12,2) NOT NULL DEFAULT 1,
    unit_price   numeric(14,2) NOT NULL DEFAULT 0,     -- in the invoice's currency, before IVA
    sort_order   int NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fin_invoice_payments (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id   uuid NOT NULL REFERENCES fin_invoices(id) ON DELETE CASCADE,
    paid_date    date NOT NULL,
    amount       numeric(14,2) NOT NULL CHECK (amount > 0),   -- in the invoice's currency
    fx_rate      numeric(10,4),                                -- CRC per USD on paid_date
    amount_usd   numeric(12,2) NOT NULL,
    account_id   uuid NOT NULL REFERENCES fin_accounts(id),
    notes        text,
    created_at   timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS fin_invoice_lines_inv_idx ON fin_invoice_lines (invoice_id);
CREATE INDEX IF NOT EXISTS fin_invoice_payments_inv_idx ON fin_invoice_payments (invoice_id);
