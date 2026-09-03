"""
Migration 038 helper — `vrm.site_anomalies`, Fleet Dashboard Phase 3b
(2026-09-03, PLAN_PHASE19_FLEET_P3.md §2/§3): one open row per
(site_id, anomaly_type), written by `victron/anomaly_silence.py` via
`vrm_api/routers/vrm_fleet.py:post_refresh_snapshots()`.

Checks:
  1. The table exists and is queryable.
  2. A real write-then-read round trip (open an anomaly, confirm the partial
     UNIQUE index on (site_id, anomaly_type) WHERE cleared_at IS NULL
     actually rejects a second concurrently-open row for the same site+type
     — the same invariant the app layer is also expected to maintain by
     checking-before-writing, verified here at the DB level too), then clear
     it and confirm a second open row is allowed once the first is cleared,
     then cleanup, on a disposable site.

It does NOT apply the migration: paste
  `database/migrations/038_site_anomalies.sql`
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_038
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()
    customers = c.schema("vrm").table("customers")
    sites = c.schema("vrm").table("sites")
    anomalies = c.schema("vrm").table("site_anomalies")

    print("1. Table exists and is queryable...")
    sample = anomalies.select("id,site_id,anomaly_type,cleared_at").limit(3).execute().data
    print(f"   ok — sample: {sample}")

    test_customer_id = str(uuid.uuid4())
    test_site_id = f"migration-038-test-{uuid.uuid4().hex[:8]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        print("2. Write-then-read round trip (disposable site)...")
        customers.insert({
            "id": test_customer_id, "name": "Migration 038 Test",
            "slug": f"migration-038-test-{uuid.uuid4().hex[:8]}",
            "country": "CR", "plan": "starter", "active": True,
            "provisioning_state": "active", "account_type": "owner",
        }).execute()
        sites.insert({
            "site_id": test_site_id, "customer_id": test_customer_id,
            "display_name": "Migration 038 Test Site", "source": "vrm_api",
            "system_type": "hybrid", "report_language": "en",
            "timezone": "America/Costa_Rica", "country": "CR",
        }).execute()

        row = anomalies.insert({
            "site_id": test_site_id, "anomaly_type": "unexpected_silence",
            "detected_at": now_iso, "detail": {"minutes_silent": 30},
        }).execute().data[0]
        assert row["cleared_at"] is None, f"FAIL: expected cleared_at NULL on open row: {row}"
        print(f"   ok — opened: {row}")

        print("3. Partial UNIQUE index rejects a second concurrently-open row for the same (site_id, anomaly_type)...")
        rejected = False
        try:
            anomalies.insert({
                "site_id": test_site_id, "anomaly_type": "unexpected_silence",
                "detected_at": now_iso, "detail": {"minutes_silent": 0},
            }).execute()
        except Exception as exc:  # noqa: BLE001 — expecting a Postgres unique-violation here
            rejected = True
            print(f"   ok — second open row rejected as expected: {exc}")
        assert rejected, "FAIL: a second OPEN row for the same (site_id, anomaly_type) was accepted — the partial UNIQUE index is not doing its job."

        print("4. Update detail in place on the existing open row (the real write pattern)...")
        anomalies.update({"detail": {"minutes_silent": 45}}).eq("id", row["id"]).execute()
        row2 = anomalies.select("*").eq("id", row["id"]).single().execute().data
        assert row2["detail"]["minutes_silent"] == 45, f"FAIL: update-in-place did not stick: {row2}"
        print(f"   ok — updated in place: {row2}")

        print("5. Clear it, then confirm a second open row for the same site+type is now allowed...")
        anomalies.update({"cleared_at": datetime.now(timezone.utc).isoformat()}).eq("id", row["id"]).execute()
        row3 = anomalies.insert({
            "site_id": test_site_id, "anomaly_type": "unexpected_silence",
            "detected_at": now_iso, "detail": {"minutes_silent": 15},
        }).execute().data[0]
        assert row3["cleared_at"] is None, f"FAIL: new row should be open: {row3}"
        print(f"   ok — new open row accepted after the first cleared: {row3}")
    finally:
        anomalies.delete().eq("site_id", test_site_id).execute()
        sites.delete().eq("site_id", test_site_id).execute()
        customers.delete().eq("id", test_customer_id).execute()
        print("   cleanup done")

    print("\nALL CHECKS PASSED — migration 038 is applied correctly.")


if __name__ == "__main__":
    main()
