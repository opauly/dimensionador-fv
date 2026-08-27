"""
Migration 028 helper — report module selection (PLAN_PHASE18.md §1): one
nullable text[] column on vrm.sites, one on vrm.customers, each with a CHECK
that only the 9 known module ids may ever appear in it.

Checks:
  1. Both columns exist and are queryable.
  2. Every existing row has it NULL (additive, no backfill — same gate every
     prior Phase 17/18 migration has used).
  3. A real write-then-read round trip on a disposable test customer AND a
     disposable test site under it, then cleanup.
  4. The CHECK constraint actually rejects an unknown module id, on both
     columns — not just documented, verified live.

It does NOT apply the migration: paste
  `database/migrations/028_report_module_selection.sql`
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_028
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

    print("1. Both columns exist and are queryable...")
    cust_rows = customers.select("id, default_report_modules").limit(5).execute().data
    print(f"   ok — vrm.customers sample: {cust_rows}")
    site_rows = sites.select("site_id, report_modules").limit(5).execute().data
    print(f"   ok — vrm.sites sample: {site_rows}")

    print("2. Every existing row has it NULL (no backfill)...")
    non_null_cust = (customers.select("id", count="exact")
                     .not_.is_("default_report_modules", "null").execute())
    assert non_null_cust.count == 0, f"FAIL: {non_null_cust.count} customer(s) already have a non-NULL value"
    non_null_site = (sites.select("site_id", count="exact")
                     .not_.is_("report_modules", "null").execute())
    assert non_null_site.count == 0, f"FAIL: {non_null_site.count} site(s) already have a non-NULL value"
    print("   ok — 0 non-NULL rows on either column")

    print("3. Write-then-read round trip (disposable test customer + site)...")
    test_customer_id = str(uuid.uuid4())
    test_site_id = f"migration-028-test-{uuid.uuid4().hex[:8]}"
    try:
        customers.insert({
            "id": test_customer_id, "name": "Migration 028 Test",
            "slug": f"migration-028-test-{uuid.uuid4().hex[:8]}",
            "country": "CR", "plan": "starter", "active": True,
            "provisioning_state": "active", "account_type": "owner",
        }).execute()
        customers.update({"default_report_modules": ["battery_health", "weather"]}).eq("id", test_customer_id).execute()
        row = customers.select("default_report_modules").eq("id", test_customer_id).single().execute().data
        assert sorted(row["default_report_modules"]) == ["battery_health", "weather"], f"FAIL: customer round trip mismatch: {row}"
        print("   ok — vrm.customers wrote and read back ['battery_health', 'weather']")

        sites.insert({
            "site_id": test_site_id, "customer_id": test_customer_id,
            "display_name": "Migration 028 Test Site", "source": "csv_upload",
            "system_type": "hybrid", "report_language": "en",
            "timezone": "America/Costa_Rica", "country": "CR",
        }).execute()
        sites.update({"report_modules": ["grid_quality", "events", "soc_chart"]}).eq("site_id", test_site_id).execute()
        row = sites.select("report_modules").eq("site_id", test_site_id).single().execute().data
        assert sorted(row["report_modules"]) == ["events", "grid_quality", "soc_chart"], f"FAIL: site round trip mismatch: {row}"
        print("   ok — vrm.sites wrote and read back ['grid_quality', 'events', 'soc_chart']")

        print("4. CHECK constraint rejects an unknown module id...")
        try:
            sites.update({"report_modules": ["not_a_real_module"]}).eq("site_id", test_site_id).execute()
            raise AssertionError("FAIL: an invalid module id was accepted on vrm.sites — CHECK constraint is not enforcing")
        except AssertionError:
            raise
        except Exception as exc:
            print(f"   ok — vrm.sites rejected an invalid module id: {type(exc).__name__}")

        try:
            customers.update({"default_report_modules": ["not_a_real_module"]}).eq("id", test_customer_id).execute()
            raise AssertionError("FAIL: an invalid module id was accepted on vrm.customers — CHECK constraint is not enforcing")
        except AssertionError:
            raise
        except Exception as exc:
            print(f"   ok — vrm.customers rejected an invalid module id: {type(exc).__name__}")
    finally:
        sites.delete().eq("site_id", test_site_id).execute()
        customers.delete().eq("id", test_customer_id).execute()
        print("   cleanup done")

    print("\nALL CHECKS PASSED — migration 028 is applied correctly.")


if __name__ == "__main__":
    main()
