"""
Migration 020 helper — Projects module migration trail + project_extras.

Checks whether the migration's new objects are present, reachable through
PostgREST. It does NOT apply the migration: paste
`database/migrations/020_projects_extras.sql` into
  Project → SQL Editor → New query → Run

Usage:
    python -m tools.run_migration_020
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client

SQL_PATH = "database/migrations/020_projects_extras.sql"

# The five tables that already exist live in Supabase (declared with
# CREATE TABLE IF NOT EXISTS in the migration — expected to be no-ops).
EXISTING_TABLES = [
    "projects", "project_payments", "project_expenses",
    "project_labor", "project_invoice_items",
]

# Tables that get a new created_at column in this migration.
CREATED_AT_TARGETS = [
    "project_payments", "project_expenses", "project_labor", "project_invoice_items",
]

db = get_client()

print("Checking migration 020 — Projects module migration trail …\n")

missing_tables: list[str] = []
missing_created_at: list[str] = []
extras_missing = False

print("── Pre-existing project tables (should already be reachable) ──")
for table in EXISTING_TABLES:
    try:
        res = db.table(table).select("*").limit(1).execute()
        print(f"  ✅ {table:22s} reachable ({len(res.data or [])} row(s) sampled)")
    except Exception as exc:  # noqa: BLE001 — surfacing the raw PostgREST error is the point
        missing_tables.append(table)
        print(f"  ❌ {table:22s} NOT reachable — {str(exc)[:120]}")

print()
print("── New: project_extras table ──")
try:
    res = db.table("project_extras").select("*").limit(1).execute()
    print(f"  ✅ project_extras         reachable ({len(res.data or [])} row(s) sampled)")
except Exception as exc:  # noqa: BLE001
    extras_missing = True
    print(f"  ❌ project_extras         NOT reachable — {str(exc)[:120]}")

print()
print("── New: created_at columns ──")
for table in CREATED_AT_TARGETS:
    try:
        # select created_at specifically, not `*` — a missing column errors
        # differently (and more informatively) than a missing table.
        db.table(table).select("created_at").limit(1).execute()
        print(f"  ✅ {table}.created_at present")
    except Exception as exc:  # noqa: BLE001
        missing_created_at.append(table)
        print(f"  ❌ {table}.created_at MISSING — {str(exc)[:120]}")

print()

if not missing_tables and not extras_missing and not missing_created_at:
    print("─" * 68)
    print("Ready. All migration 020 objects are present.")
    print("(The unique index on projects(proposal_id) and the index on")
    print(" project_extras(project_id) can't be checked over PostgREST — ")
    print(" they don't change what's selectable — but they're part of the")
    print(" same idempotent SQL file, so if the tables/columns above are")
    print(" present the migration has been run.)")
    print("─" * 68)
    raise SystemExit(0)

print("─" * 68)
print("Not ready. Paste the SQL below into the Supabase SQL Editor and run it")
print(f"(source: {SQL_PATH}). It is idempotent — safe to run even if some")
print("objects already exist.")
print("─" * 68)
print()
print("""
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

CREATE TABLE IF NOT EXISTS project_extras (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    description     text NOT NULL,
    amount_usd      numeric(10,2) NOT NULL,
    iva_rate        numeric(4,3) NOT NULL DEFAULT 0,
    total_with_iva  numeric(10,2) GENERATED ALWAYS AS (amount_usd * (1 + iva_rate)) STORED,
    approved        boolean NOT NULL DEFAULT true,
    extra_date      date,
    notes           text,
    created_at      timestamptz DEFAULT now()
);

ALTER TABLE project_payments      ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();
ALTER TABLE project_expenses      ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();
ALTER TABLE project_labor         ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();
ALTER TABLE project_invoice_items ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_proposal_unique
    ON projects(proposal_id) WHERE proposal_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_project_extras_project_id ON project_extras(project_id);
""")
print("─" * 68)
print(f"(Full file with explanatory comments: {SQL_PATH})")
raise SystemExit(1)
