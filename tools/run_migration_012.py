"""
Migration 012 helper — `vrm` schema (VRM CSV ingestion path).

Checks whether the schema is present, reachable through PostgREST, and wired
up correctly. It does NOT apply the migration: paste
`database/migrations/012_vrm_schema.sql` into
  Project → SQL Editor → New query → Run

Usage:
    python -m tools.run_migration_012
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client

SQL_PATH = "database/migrations/012_vrm_schema.sql"
TABLES = ["customers", "sites", "energy_daily", "alarm_events",
          "daily_health", "ingestion_log"]

db = get_client()
vrm = db.schema("vrm")

print("Checking `vrm` schema …\n")

missing: list[str] = []
for table in TABLES:
    try:
        res = vrm.table(table).select("*").limit(1).execute()
        print(f"  ✅ vrm.{table:15s} reachable ({len(res.data or [])} row(s) sampled)")
    except Exception as exc:  # noqa: BLE001 — surfacing the raw PostgREST error is the point
        missing.append(table)
        msg = str(exc)
        if "schema must be one of" in msg or "does not exist" in msg:
            print(f"  ❌ vrm.{table:15s} NOT reachable — {msg[:120]}")
        else:
            print(f"  ❌ vrm.{table:15s} error — {msg[:120]}")

print()
if missing:
    print("─" * 68)
    print("Not ready. Two separate things can cause this:")
    print()
    print(f"  1. The migration hasn't been run. Paste {SQL_PATH}")
    print("     into the Supabase SQL Editor and run it.")
    print()
    print("  2. The migration ran, but `vrm` is not exposed to PostgREST.")
    print("     Settings → API → Data API → Exposed schemas → add `vrm`.")
    print("     PostgREST does not route by URL path — an unexposed schema is")
    print("     invisible even though the tables exist. This is the same step")
    print("     `monitoring` needed.")
    print("─" * 68)
    raise SystemExit(1)

print("─" * 68)
print("Schema reachable. Checking the health-score wiring …")
print("─" * 68)

try:
    episodes = db.schema("vrm").rpc(
        "count_alarm_episodes", {"p_site_id": "__nonexistent__", "p_date": "2026-01-01"}
    ).execute()
    print(f"  ✅ vrm.count_alarm_episodes() callable (returned {episodes.data})")
except Exception as exc:  # noqa: BLE001
    print(f"  ❌ vrm.count_alarm_episodes() not callable — {str(exc)[:160]}")

try:
    health = db.schema("vrm").rpc(
        "compute_daily_health",
        {"p_site_id": "__nonexistent__", "p_date": "2026-01-01",
         "p_dump_type": "csv_upload"},
    ).execute()
    # No such row, so NULL is the correct answer — it proves the function
    # exists and runs, which is all this check is for.
    print(f"  ✅ vrm.compute_daily_health() callable (returned {health.data})")
except Exception as exc:  # noqa: BLE001
    print(f"  ❌ vrm.compute_daily_health() not callable — {str(exc)[:160]}")

print()
print("Ready. Next: create a site row, then ingest a CSV.")
