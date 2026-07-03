-- Pauly&Co Solar Tool — Supabase Schema
-- Run this in the Supabase SQL editor (Project → SQL Editor → New query)

-- Equipment catalog -----------------------------------------------------------

CREATE TABLE IF NOT EXISTS panels (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand           text NOT NULL,
    model           text NOT NULL,
    wp              int NOT NULL,
    voc             numeric NOT NULL,
    vmp             numeric NOT NULL,
    isc             numeric NOT NULL,
    imp             numeric NOT NULL,
    temp_coeff_pmax numeric NOT NULL,
    width_m         numeric NOT NULL,
    height_m        numeric NOT NULL,
    area_m2         numeric GENERATED ALWAYS AS (width_m * height_m) STORED,
    weight_kg       numeric,
    warranty_product_yr int NOT NULL DEFAULT 12,
    warranty_power_yr   int NOT NULL DEFAULT 25,
    cost_usd        numeric,
    datasheet_path  text,
    notes           text,
    created_at      timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inverters (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand           text NOT NULL,
    model           text NOT NULL,
    kw              numeric NOT NULL,
    type            text NOT NULL CHECK (type IN ('string_inverter', 'microinverter', 'hybrid')),
    vmax            numeric,
    vmin_mppt       numeric,
    vmax_mppt       numeric,
    imax_mppt       numeric,
    mppt_channels   int,
    phase           text CHECK (phase IN ('single', 'three')),
    output_v        numeric,
    warranty_yr     int NOT NULL DEFAULT 5,
    cost_usd        numeric,
    datasheet_path  text,
    notes           text,
    created_at      timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS batteries (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand           text NOT NULL,
    model           text NOT NULL,
    chemistry       text NOT NULL,
    capacity_kwh    numeric NOT NULL,
    capacity_ah     numeric,
    voltage_v       numeric NOT NULL,
    dod_pct         int NOT NULL DEFAULT 80,
    cycles          int,
    warranty_yr     int NOT NULL DEFAULT 10,
    cost_usd        numeric,
    notes           text,
    created_at      timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS charge_controllers (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand           text NOT NULL,
    model           text NOT NULL,
    type            text NOT NULL CHECK (type IN ('MPPT', 'PWM')),
    vin_max         numeric NOT NULL,
    vout            numeric NOT NULL,
    imax_in         numeric NOT NULL,
    imax_out        numeric NOT NULL,
    cost_usd        numeric,
    notes           text,
    created_at      timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS monitoring_devices (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    brand           text NOT NULL,
    model           text NOT NULL,
    compatible_with text,
    cost_usd        numeric,
    created_at      timestamptz DEFAULT now()
);

-- Client contact book ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS clients (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    phone       text,
    email       text,
    notes       text,
    created_at  timestamptz DEFAULT now()
);

-- Tariffs ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS distributors (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL UNIQUE,
    abbreviation    text NOT NULL,
    coverage_area   text
);

CREATE TABLE IF NOT EXISTS tariff_types (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    distributor_id      uuid NOT NULL REFERENCES distributors(id) ON DELETE CASCADE,
    code                text NOT NULL,
    name                text NOT NULL,
    sector              text NOT NULL CHECK (sector IN ('residential', 'commercial', 'industrial')),
    access_charge_crc   numeric NOT NULL DEFAULT 0,
    bomberos_pct        numeric NOT NULL DEFAULT 0.0175,
    iva_threshold_kwh   int NOT NULL DEFAULT 280,
    last_updated        timestamptz DEFAULT now(),
    UNIQUE (distributor_id, code)
);

CREATE TABLE IF NOT EXISTS tariff_tiers (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tariff_type_id  uuid NOT NULL REFERENCES tariff_types(id) ON DELETE CASCADE,
    from_kwh        int NOT NULL,
    to_kwh          int,
    rate_crc        numeric NOT NULL,
    is_fixed        boolean NOT NULL DEFAULT false,
    sort_order      int NOT NULL
);

-- Proposals -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS proposals (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at              timestamptz DEFAULT now(),
    updated_at              timestamptz DEFAULT now(),
    client_id               uuid REFERENCES clients(id),
    client_name             text NOT NULL,
    system_type             text NOT NULL CHECK (system_type IN ('grid_zero', 'off_grid', 'hybrid')),
    status                  text NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft', 'active', 'won', 'lost', 'cancelled')),
    current_version_number  int NOT NULL DEFAULT 1,
    quote_number            int
);

CREATE TABLE IF NOT EXISTS proposal_versions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id     uuid NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    version_number  int NOT NULL,
    created_at      timestamptz DEFAULT now(),
    locked_at       timestamptz,
    locked          boolean NOT NULL DEFAULT false,
    version_note    text,
    sent_to_client  boolean NOT NULL DEFAULT false,
    total_usd       numeric(10,2),
    data            jsonb NOT NULL DEFAULT '{}',
    pdf_path        text
);

-- Projects --------------------------------------------------------------------

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

-- App settings ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS app_settings (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL,
    updated_at  timestamptz DEFAULT now()
);

-- Indexes ---------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_proposal_versions_proposal_id  ON proposal_versions(proposal_id);
CREATE INDEX IF NOT EXISTS idx_proposals_status               ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_project_payments_project_id    ON project_payments(project_id);
CREATE INDEX IF NOT EXISTS idx_project_expenses_project_id    ON project_expenses(project_id);
CREATE INDEX IF NOT EXISTS idx_project_labor_project_id       ON project_labor(project_id);
CREATE INDEX IF NOT EXISTS idx_project_invoice_items_project  ON project_invoice_items(project_id);
CREATE INDEX IF NOT EXISTS idx_tariff_types_distributor_id    ON tariff_types(distributor_id);
CREATE INDEX IF NOT EXISTS idx_tariff_tiers_tariff_type_id    ON tariff_tiers(tariff_type_id);

-- Default app settings --------------------------------------------------------

INSERT INTO app_settings (key, value) VALUES
    ('company_info', '{
        "name": "Pauly & Co.",
        "license": "",
        "phone": "",
        "email": "",
        "website": "",
        "contact_name": "Oscar Pauly",
        "contact_title": "Ingeniero Solar",
        "bank_local": "",
        "bank_international": ""
    }'),
    ('defaults', '{
        "iva_rate": 0.0,
        "tariff_escalation": 0.05,
        "proposal_validity_days": 15,
        "onvo_commission": 0.024
    }'),
    ('exchange_rate_cache', '{"rate": null, "cached_at": null}')
ON CONFLICT (key) DO NOTHING;
