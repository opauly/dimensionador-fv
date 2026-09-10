"""
Migration 045 helper — Phase 10 site register schema (site_properties,
site_credentials, maintenance_visits, vrm.sites.property_id,
get_property_maintenance_status()).

Verifies every new object is present and reachable, and exercises the status
function against a disposable property + visit created and torn down by this
script itself. It does NOT apply the migration: paste
  database/migrations/045_site_maintenance_register.sql
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_045
"""
from __future__ import annotations

from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()

    print("1. Checking new tables exist...")
    for table in ("site_properties", "site_credentials", "maintenance_visits"):
        c.table(table).select("*").limit(1).execute()
        print(f"   public.{table}: reachable")

    print("\n2. Checking vrm.sites.property_id exists...")
    c.schema("vrm").table("sites").select("property_id").limit(1).execute()
    print("   vrm.sites.property_id: reachable")

    print("\n3. Exercising get_property_maintenance_status() against a disposable property...")
    prop = c.table("site_properties").insert({
        "name": "__migration_045_test__",
        "maintenance_interval_days": 365,
    }).execute().data[0]
    prop_id = prop["id"]
    try:
        # No visit, no linked site -> nothing to compute yet.
        empty = c.rpc("get_property_maintenance_status", {"p_property_id": prop_id}).execute().data
        assert empty == [], f"expected no row with nothing to base a status on, got {empty!r}"
        print("   no visit + no linked site -> empty result (correct)")

        overdue_date = (date.today() - timedelta(days=400)).isoformat()
        c.table("maintenance_visits").insert({
            "property_id": prop_id, "visit_date": overdue_date,
        }).execute()
        result = c.rpc("get_property_maintenance_status", {"p_property_id": prop_id}).execute().data
        assert result and result[0]["status"] == "overdue", f"expected overdue, got {result!r}"
        print(f"   visit 400 days ago -> status={result[0]['status']!r} (correct)")
    finally:
        c.table("maintenance_visits").delete().eq("property_id", prop_id).execute()
        c.table("site_properties").delete().eq("id", prop_id).execute()
        print("   test property + visit cleaned up")

    print("\nMigration 045 verified.")


if __name__ == "__main__":
    main()
