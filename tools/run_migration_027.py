"""
Migration 027 helper — Cap B's "notify once per billing period" durable
column (PLAN_PHASE17.md §0.6 Q7, §8 Step 8): one nullable date column on
vrm.customers.

Checks:
  1. vrm.customers.report_cap_notified_period_end exists and is queryable.
  2. Every existing customer row has it NULL (the migration changed nobody's
     behaviour — same "additive, no backfill" gate every other Phase 17
     migration has used).
  3. A real write-then-read round trip: set it on a disposable test
     customer, read it back, confirm it matches, delete the test customer.

It does NOT apply the migration: paste
  `database/migrations/027_report_cap_notification.sql`
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_027
"""
from __future__ import annotations

import uuid

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()
    customers = c.schema("vrm").table("customers")

    print("1. Column exists and is queryable...")
    rows = customers.select("id, report_cap_notified_period_end").limit(5).execute().data
    print(f"   ok — sample: {rows}")

    print("2. Every existing customer has it NULL (no backfill)...")
    non_null = (customers.select("id", count="exact")
               .not_.is_("report_cap_notified_period_end", "null")
               .execute())
    assert non_null.count == 0, f"FAIL: {non_null.count} customer(s) already have a non-NULL value — unexpected before this migration's own writer ever runs"
    print("   ok — 0 non-NULL rows")

    print("3. Write-then-read round trip on a disposable test customer...")
    test_id = str(uuid.uuid4())
    try:
        customers.insert({
            "id": test_id, "name": "Migration 027 Test", "slug": f"migration-027-test-{uuid.uuid4().hex[:8]}",
            "country": "CR", "plan": "starter", "active": True,
            "provisioning_state": "active", "account_type": "owner",
        }).execute()
        customers.update({"report_cap_notified_period_end": "2026-08-31"}).eq("id", test_id).execute()
        row = customers.select("report_cap_notified_period_end").eq("id", test_id).single().execute().data
        assert row["report_cap_notified_period_end"] == "2026-08-31", f"FAIL: round trip mismatch: {row}"
        print("   ok — wrote and read back 2026-08-31")
    finally:
        customers.delete().eq("id", test_id).execute()
        print("   cleanup done")

    print("\nALL CHECKS PASSED — migration 027 is applied correctly.")


if __name__ == "__main__":
    main()
