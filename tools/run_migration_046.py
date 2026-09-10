"""
Migration 046 helper — bundled visits + manual due-date overrides.

Verifies the new column/table exist and exercises the override path of
get_property_maintenance_status() against a disposable property. It does NOT apply
the migration: paste
  database/migrations/046_maintenance_bundling_and_overrides.sql
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_046
"""
from __future__ import annotations

from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()

    print("1. Checking new objects exist...")
    c.table("site_properties").select("next_due_override").limit(1).execute()
    print("   site_properties.next_due_override: reachable")
    c.table("maintenance_visit_groups").select("*").limit(1).execute()
    print("   public.maintenance_visit_groups: reachable")
    c.table("maintenance_visits").select("visit_group_id").limit(1).execute()
    print("   maintenance_visits.visit_group_id: reachable")

    print("\n2. Exercising the override path of get_property_maintenance_status()...")
    prop = c.table("site_properties").insert({
        "name": "__migration_046_test__", "maintenance_interval_days": 365,
    }).execute().data[0]
    prop_id = prop["id"]
    try:
        future_override = (date.today() + timedelta(days=10)).isoformat()
        c.table("site_properties").update({"next_due_override": future_override}).eq("id", prop_id).execute()
        result = c.rpc("get_property_maintenance_status", {"p_property_id": prop_id}).execute().data
        assert result and result[0]["next_due_date"] == future_override, f"expected override date, got {result!r}"
        assert result[0]["status"] == "due_soon", f"expected due_soon, got {result!r}"
        print(f"   override 10 days out -> next_due_date={result[0]['next_due_date']}, status={result[0]['status']!r} (correct)")
    finally:
        c.table("site_properties").delete().eq("id", prop_id).execute()
        print("   test property cleaned up")

    print("\nMigration 046 verified.")


if __name__ == "__main__":
    main()
