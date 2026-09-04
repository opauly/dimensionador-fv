"""
Migration 041 helper — vrm.plan_limits.live_dashboard (customer-facing
Fleet Dashboard entitlement).

Verifies the new column seeded correctly: true for growth/fleet, false for
every other plan_key. It does NOT apply the migration: paste
  database/migrations/041_dashboard_entitlement.sql
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_041
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402

_EXPECT_TRUE = {"growth", "fleet"}
_EXPECT_FALSE = {"default", "trial", "single_report", "starter"}


def main() -> None:
    c = get_client()

    print("1. Checking vrm.plan_limits.live_dashboard per plan_key...")
    rows = c.schema("vrm").table("plan_limits").select("plan_key,live_dashboard").execute().data
    by_key = {r["plan_key"]: r["live_dashboard"] for r in rows}

    missing = (_EXPECT_TRUE | _EXPECT_FALSE) - set(by_key)
    assert not missing, f"plan_limits is missing expected plan_key rows: {missing}"

    for key in sorted(_EXPECT_TRUE):
        print(f"   {key}: live_dashboard={by_key[key]} (expect True)")
        assert by_key[key] is True, f"{key} should have live_dashboard=true"
    for key in sorted(_EXPECT_FALSE):
        print(f"   {key}: live_dashboard={by_key[key]} (expect False)")
        assert by_key[key] is False, f"{key} should have live_dashboard=false"

    print("\nMigration 041 verified.")


if __name__ == "__main__":
    main()
