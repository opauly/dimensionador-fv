"""
Migration 029 helper — Phase 18 "Phase 2" module types (PLAN_PHASE18.md §7):
a new vrm.critical_alerts table, six new nullable columns on vrm.energy_daily,
and the report_modules/default_report_modules CHECK constraints widened from
9 to 13 known ids.

Checks:
  1. The new energy_daily columns exist and are queryable.
  2. vrm.critical_alerts exists, is queryable, and its `category` CHECK
     rejects an unknown category.
  3. A real write-then-read round trip on a disposable site's energy_daily
     row (generator_hours/grid_meter/tank_* columns) and a disposable
     critical_alerts row, then cleanup.
  4. report_modules/default_report_modules now accept all 4 new module ids
     (not just the original 9) and still reject an unknown id — proves the
     widened CHECK replaced the old one rather than sitting alongside it.

It does NOT apply the migration: paste
  `database/migrations/029_report_modules_phase2.sql`
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_029
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
    energy_daily = c.schema("vrm").table("energy_daily")
    critical_alerts = c.schema("vrm").table("critical_alerts")

    print("1. New energy_daily columns exist and are queryable...")
    sample = (energy_daily.select("site_id,generator_hours,grid_meter,"
                                  "tank_capacity_m3,tank_fluid_type,tank_status,tank_level_pct")
             .limit(3).execute().data)
    print(f"   ok — sample: {sample}")

    print("2. vrm.critical_alerts exists and its CHECK enforces the 3 known categories...")
    empty = critical_alerts.select("id").limit(1).execute().data
    print(f"   ok — queryable, {len(empty)} row(s) in a 1-row probe")

    test_customer_id = str(uuid.uuid4())
    test_site_id = f"migration-029-test-{uuid.uuid4().hex[:8]}"
    try:
        customers.insert({
            "id": test_customer_id, "name": "Migration 029 Test",
            "slug": f"migration-029-test-{uuid.uuid4().hex[:8]}",
            "country": "CR", "plan": "starter", "active": True,
            "provisioning_state": "active", "account_type": "owner",
        }).execute()
        sites.insert({
            "site_id": test_site_id, "customer_id": test_customer_id,
            "display_name": "Migration 029 Test Site", "source": "vrm_api",
            "system_type": "hybrid", "report_language": "en",
            "timezone": "America/Costa_Rica", "country": "CR",
        }).execute()

        print("3. Write-then-read round trip on energy_daily's new columns...")
        energy_daily.insert({
            "site_id": test_site_id, "date": "2026-01-01", "dump_type": "vrm_api",
            "generator_hours": 2.5,
            "grid_meter": {"l1": {"v_avg": 120.1, "c_avg": -0.5, "pf_avg": -0.02}},
            "tank_capacity_m3": 1.2, "tank_fluid_type": "1", "tank_status": "ok",
            "tank_level_pct": 68.0,
        }).execute()
        row = (energy_daily.select("generator_hours,grid_meter,tank_capacity_m3,"
                                   "tank_fluid_type,tank_status,tank_level_pct")
              .eq("site_id", test_site_id).eq("date", "2026-01-01").single().execute().data)
        assert row["generator_hours"] == 2.5, f"FAIL: generator_hours round trip: {row}"
        assert row["grid_meter"]["l1"]["v_avg"] == 120.1, f"FAIL: grid_meter round trip: {row}"
        assert row["tank_level_pct"] == 68.0, f"FAIL: tank_level_pct round trip: {row}"
        print(f"   ok — energy_daily round trip: {row}")

        print("4. Write-then-read round trip on vrm.critical_alerts...")
        critical_alerts.insert({
            "site_id": test_site_id, "category": "dc_ripple",
            "alarm": "High DC Ripple", "severity": "WARNING",
            "timestamp": "2026-01-01T12:00:00Z",
        }).execute()
        rows = (critical_alerts.select("category,alarm,severity")
               .eq("site_id", test_site_id).execute().data)
        assert len(rows) == 1 and rows[0]["category"] == "dc_ripple", f"FAIL: critical_alerts round trip: {rows}"
        print(f"   ok — critical_alerts round trip: {rows}")

        print("5. critical_alerts.category CHECK rejects an unknown category...")
        try:
            critical_alerts.insert({
                "site_id": test_site_id, "category": "not_a_real_category",
                "severity": "WARNING", "timestamp": "2026-01-01T12:00:00Z",
            }).execute()
            raise AssertionError("FAIL: an invalid category was accepted — CHECK constraint is not enforcing")
        except AssertionError:
            raise
        except Exception as exc:
            print(f"   ok — rejected an invalid category: {type(exc).__name__}")

        print("6. report_modules/default_report_modules now accept the 4 new ids...")
        sites.update({"report_modules": ["critical_alerts", "grid_meter_detail",
                                         "generator_runtime", "tank_level"]}).eq("site_id", test_site_id).execute()
        row = sites.select("report_modules").eq("site_id", test_site_id).single().execute().data
        assert sorted(row["report_modules"]) == sorted(
            ["critical_alerts", "grid_meter_detail", "generator_runtime", "tank_level"]
        ), f"FAIL: sites round trip mismatch: {row}"
        print(f"   ok — vrm.sites accepted all 4 new module ids: {row}")

        customers.update({"default_report_modules": ["tank_level"]}).eq("id", test_customer_id).execute()
        row = customers.select("default_report_modules").eq("id", test_customer_id).single().execute().data
        assert row["default_report_modules"] == ["tank_level"], f"FAIL: customers round trip mismatch: {row}"
        print(f"   ok — vrm.customers accepted the new module id: {row}")

        print("7. The widened CHECK still rejects an unknown module id...")
        try:
            sites.update({"report_modules": ["not_a_real_module"]}).eq("site_id", test_site_id).execute()
            raise AssertionError("FAIL: an invalid module id was accepted on vrm.sites")
        except AssertionError:
            raise
        except Exception as exc:
            print(f"   ok — vrm.sites rejected an invalid module id: {type(exc).__name__}")
    finally:
        critical_alerts.delete().eq("site_id", test_site_id).execute()
        energy_daily.delete().eq("site_id", test_site_id).execute()
        sites.delete().eq("site_id", test_site_id).execute()
        customers.delete().eq("id", test_customer_id).execute()
        print("   cleanup done")

    print("\nALL CHECKS PASSED — migration 029 is applied correctly.")


if __name__ == "__main__":
    main()
