"""
Migration 022 helper — projects.contract_iva_usd.

Checks whether the column is present, reachable through PostgREST. It does
NOT apply the migration: paste
  `database/migrations/022_project_contract_iva.sql`
into
  Project → SQL Editor → New query → Run

Usage:
    python -m tools.run_migration_022
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client

SQL_PATH = "database/migrations/022_project_contract_iva.sql"

db = get_client()

print("Checking migration 022 — projects.contract_iva_usd …\n")

try:
    db.table("projects").select("contract_iva_usd").limit(1).execute()
    print("  ✅ projects.contract_iva_usd present")
    ready = True
except Exception as exc:  # noqa: BLE001
    print(f"  ❌ projects.contract_iva_usd MISSING — {str(exc)[:150]}")
    ready = False

print()
if ready:
    print("─" * 68)
    print("Ready. Migration 022 has been applied.")
    print("─" * 68)
    raise SystemExit(0)

print("─" * 68)
print(f"Not ready. Paste the SQL below into the Supabase SQL Editor (source: {SQL_PATH}).")
print("It is idempotent — safe to run even if the column already exists.")
print("─" * 68)
print()
print("ALTER TABLE projects ADD COLUMN IF NOT EXISTS contract_iva_usd numeric(10,2) NOT NULL DEFAULT 0;")
print()
print("─" * 68)
raise SystemExit(1)
