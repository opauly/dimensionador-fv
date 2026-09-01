"""
Migration 032 helper — `vrm.ingestion_log.critical_alerts_written`.

Checks:
  1. The column is now selectable (PostgREST's schema cache picked it up).
  2. A real ingest_parsed() call succeeds end-to-end against a disposable
     site, confirming the exact insert that's been crashing since
     2026-08-29 (commit fd6775a) now works.

It does NOT apply the migration: paste
  `database/migrations/032_ingestion_log_critical_alerts.sql`
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_032
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402
from victron import ingest as victron_ingest  # noqa: E402


def main() -> None:
    c = get_client()
    log = c.schema("vrm").table("ingestion_log")

    print("1. Column is selectable...")
    sample = log.select("id,critical_alerts_written").limit(1).execute().data
    print(f"   ok — sample: {sample}")

    print("2. Real ingest_parsed() round trip on a disposable site...")
    customer = victron_ingest.upsert_customer(
        "Migration 032 Test", account_type="owner", origin="admin", active=False,
    )
    site_id = f"migration-032-test-{uuid.uuid4().hex[:8]}"
    victron_ingest.upsert_site(customer["id"], site_id, "Migration 032 Test Site",
                               source="csv_upload")
    today = date.today()
    parsed = {
        "rows": [{
            "site_id": site_id, "date": (today - timedelta(days=1)).isoformat(),
            "dump_type": "csv_upload", "pv_kwh": 1.0, "load_kwh": 1.0,
        }],
        "alarm_events": [],
        "critical_alerts": [],
        "period_start": (today - timedelta(days=1)).isoformat(),
        "period_end": today.isoformat(),
        "sample_count": 1,
        "warnings": [],
        "missing_signals": [],
        "unscored_alarms": {},
    }
    result = victron_ingest.ingest_parsed(parsed, site_id, "migration-032-test.csv")
    print(f"   ok — ingest_parsed() returned: {result}")

    print("3. Cleanup...")
    c.schema("vrm").table("energy_daily").delete().eq("site_id", site_id).execute()
    c.schema("vrm").table("daily_health").delete().eq("site_id", site_id).execute()
    c.schema("vrm").table("ingestion_log").delete().eq("site_id", site_id).execute()
    c.schema("vrm").table("sites").delete().eq("site_id", site_id).execute()
    c.schema("vrm").table("customers").delete().eq("id", customer["id"]).execute()
    print("   done.")

    print("\nMigration 032 verified.")


if __name__ == "__main__":
    main()
