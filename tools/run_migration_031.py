"""
Migration 031 helper — `vrm.site_snapshots`, Fleet Dashboard Phase 2
(2026-08-30): one row per site, upserted by the ~15-minute live-snapshot
sweep (`vrm_api/routers/vrm_fleet.py:post_refresh_snapshots()`).

Checks:
  1. The table exists and is queryable.
  2. A real write-then-read round trip (upsert, re-upsert to confirm the
     PRIMARY KEY behaves as an upsert key not a duplicate-row insert), then
     cleanup, on a disposable site.

It does NOT apply the migration: paste
  `database/migrations/031_site_snapshots.sql`
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_031
"""
from __future__ import annotations

import uuid

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()
    customers = c.schema("vrm").table("customers")
    sites = c.schema("vrm").table("sites")
    snapshots = c.schema("vrm").table("site_snapshots")

    print("1. Table exists and is queryable...")
    sample = snapshots.select("site_id,captured_at,pv_power_w,soc_pct").limit(3).execute().data
    print(f"   ok — sample: {sample}")

    test_customer_id = str(uuid.uuid4())
    test_site_id = f"migration-031-test-{uuid.uuid4().hex[:8]}"
    try:
        print("2. Write-then-upsert round trip (disposable site)...")
        customers.insert({
            "id": test_customer_id, "name": "Migration 031 Test",
            "slug": f"migration-031-test-{uuid.uuid4().hex[:8]}",
            "country": "CR", "plan": "starter", "active": True,
            "provisioning_state": "active", "account_type": "owner",
        }).execute()
        sites.insert({
            "site_id": test_site_id, "customer_id": test_customer_id,
            "display_name": "Migration 031 Test Site", "source": "vrm_api",
            "system_type": "hybrid", "report_language": "en",
            "timezone": "America/Costa_Rica", "country": "CR",
        }).execute()

        snapshots.upsert({
            "site_id": test_site_id, "captured_at": "2026-08-30T12:00:00+00:00",
            "pv_power_w": 1234.5, "soc_pct": 88.0,
            "raw": {"PVP": 1234.5, "SOC": 88.0},
        }).execute()
        row = snapshots.select("*").eq("site_id", test_site_id).single().execute().data
        assert row["pv_power_w"] == 1234.5, f"FAIL: round trip mismatch: {row}"
        print(f"   ok — first upsert: {row}")

        # Re-upsert with a different value — PRIMARY KEY on site_id means
        # this must REPLACE, not add a second row.
        snapshots.upsert({
            "site_id": test_site_id, "captured_at": "2026-08-30T12:15:00+00:00",
            "pv_power_w": 999.0, "soc_pct": 89.0,
        }).execute()
        rows_after = snapshots.select("site_id").eq("site_id", test_site_id).execute().data
        assert len(rows_after) == 1, f"FAIL: expected exactly 1 row after re-upsert, got {len(rows_after)}"
        row2 = snapshots.select("*").eq("site_id", test_site_id).single().execute().data
        assert row2["pv_power_w"] == 999.0, f"FAIL: re-upsert did not replace the value: {row2}"
        print(f"   ok — re-upsert replaced in place (still 1 row): {row2}")
    finally:
        snapshots.delete().eq("site_id", test_site_id).execute()
        sites.delete().eq("site_id", test_site_id).execute()
        customers.delete().eq("id", test_customer_id).execute()
        print("   cleanup done")

    print("\nALL CHECKS PASSED — migration 031 is applied correctly.")


if __name__ == "__main__":
    main()
