"""
Migration 023 helper — vrm.jobs (VRM Monitor portal web, PLAN_PHASE14.md §2 Step 5).

Checks whether `vrm.jobs` is reachable through PostgREST. It does NOT apply
the migration: paste `database/migrations/023_vrm_portal_web.sql` into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_023
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client

SQL_PATH = "database/migrations/023_vrm_portal_web.sql"

db = get_client()
vrm = db.schema("vrm")

print("Checking migration 023 — vrm.jobs …\n")

try:
    vrm.table("jobs").select("id").limit(1).execute()
    print("  ✅ vrm.jobs is reachable")
    print()
    print("─" * 68)
    print("Ready. vrm_api's job-backed endpoints (POST /v1/ingest/*, "
          "POST /v1/reports, GET /v1/jobs/{id}) can run against this database.")
    print("─" * 68)
    raise SystemExit(0)
except SystemExit:
    raise
except Exception as exc:  # noqa: BLE001 — surfacing the raw PostgREST error is the point
    print(f"  ❌ vrm.jobs MISSING — {str(exc)[:160]}")

print()
print("─" * 68)
print("Not ready. Paste the SQL below into the Supabase SQL Editor and run it")
print(f"(source: {SQL_PATH}). It is idempotent — safe to run even if some")
print("objects already exist.")
print("─" * 68)
print()
with open(SQL_PATH) as f:
    print(f.read())
raise SystemExit(1)
