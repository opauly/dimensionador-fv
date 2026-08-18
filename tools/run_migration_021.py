"""
Migration 021 helper — VRM Monitor customer portal auth linkage.

Checks whether the new `vrm.customers` columns are present, reachable
through PostgREST. It does NOT apply the migration: paste
`database/migrations/021_vrm_portal_auth.sql` into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_021
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client

SQL_PATH = "database/migrations/021_vrm_portal_auth.sql"

NEW_COLUMNS = [
    "auth_user_id", "auth_email", "invited_at", "activated_at",
    "account_type", "site_limit", "ui_language",
]

db = get_client()
vrm = db.schema("vrm")

print("Checking migration 021 — vrm.customers auth linkage columns …\n")

missing: list[str] = []
for col in NEW_COLUMNS:
    try:
        vrm.table("customers").select(col).limit(1).execute()
        print(f"  ✅ vrm.customers.{col:14s} present")
    except Exception as exc:  # noqa: BLE001 — surfacing the raw PostgREST error is the point
        missing.append(col)
        print(f"  ❌ vrm.customers.{col:14s} MISSING — {str(exc)[:120]}")

print()

if not missing:
    print("─" * 68)
    print("Ready. All migration 021 columns are present.")
    print("(The two partial unique indexes can't be checked over PostgREST —")
    print(" they don't change what's selectable — but they're part of the")
    print(" same idempotent SQL file, so if the columns above are present the")
    print(" migration has been run.)")
    print("─" * 68)
    raise SystemExit(0)

print("─" * 68)
print("Not ready. Paste the SQL below into the Supabase SQL Editor and run it")
print(f"(source: {SQL_PATH}). It is idempotent — safe to run even if some")
print("objects already exist.")
print("─" * 68)
print()
with open(SQL_PATH) as f:
    print(f.read())
raise SystemExit(1)
