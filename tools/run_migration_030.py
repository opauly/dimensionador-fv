"""
Migration 030 helper — trial-ending reminder gate (`vrm.subscriptions.
trial_reminder_sent_at`) for the 2026-08-29 billing fix: a trial that
expires with no payment method on file now gets actively demoted
(`vrm_api/billing.py:apply_entitlements()`) instead of sitting in ONVO's
`trialing` status forever, and every trialing customer gets a "your trial
ends tomorrow" email once, branched on whether a card is on file
(`vrm_api/billing.py:send_trial_ending_reminders()`).

Checks:
  1. The new column exists and is queryable.
  2. A real write-then-read round trip on a disposable subscription row,
     then cleanup.
  3. The column starts NULL on every existing row (additive, no backfill).

It does NOT apply the migration: paste
  `database/migrations/030_trial_reminders.sql`
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_030
"""
from __future__ import annotations

import uuid

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()
    customers = c.schema("vrm").table("customers")
    subscriptions = c.schema("vrm").table("subscriptions")

    print("1. New column exists and is queryable...")
    sample = subscriptions.select("id,trial_reminder_sent_at").limit(3).execute().data
    print(f"   ok — sample: {sample}")

    print("2. Every existing row has it NULL (no backfill)...")
    non_null = (subscriptions.select("id", count="exact")
               .not_.is_("trial_reminder_sent_at", "null").execute())
    assert non_null.count == 0, f"FAIL: {non_null.count} subscription(s) already have a non-NULL value"
    print("   ok — 0 non-NULL rows")

    test_customer_id = str(uuid.uuid4())
    try:
        print("3. Write-then-read round trip (disposable test customer + subscription)...")
        customers.insert({
            "id": test_customer_id, "name": "Migration 030 Test",
            "slug": f"migration-030-test-{uuid.uuid4().hex[:8]}",
            "country": "CR", "plan": "starter", "active": True,
            "provisioning_state": "active", "account_type": "owner",
        }).execute()
        row = subscriptions.insert({
            "customer_id": test_customer_id,
            "onvo_subscription_id": f"migration-030-test-{uuid.uuid4().hex[:8]}",
            "mode": "test", "plan_key": "starter", "status": "trialing",
            "last_synced_at": "2026-08-30T00:00:00+00:00",
        }).execute().data[0]
        sub_id = row["id"]
        now_iso = "2026-08-29T12:00:00+00:00"
        subscriptions.update({"trial_reminder_sent_at": now_iso}).eq("id", sub_id).execute()
        read_back = subscriptions.select("trial_reminder_sent_at").eq("id", sub_id).single().execute().data
        assert read_back["trial_reminder_sent_at"] is not None, f"FAIL: round trip mismatch: {read_back}"
        print(f"   ok — round trip: {read_back}")
    finally:
        subscriptions.delete().eq("customer_id", test_customer_id).execute()
        customers.delete().eq("id", test_customer_id).execute()
        print("   cleanup done")

    print("\nALL CHECKS PASSED — migration 030 is applied correctly.")


if __name__ == "__main__":
    main()
