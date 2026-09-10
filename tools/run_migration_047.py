"""
Migration 047 helper — auto-create a property for every new site.

Inserts a disposable test site into monitoring.sites (no property_id given) and
confirms the trigger created and linked a property, then cleans both up. It does NOT
apply the migration: paste
  database/migrations/047_auto_create_site_property.sql
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_047
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402

_TEST_SITE_ID = "__migration_047_test_site__"


def main() -> None:
    c = get_client()

    print("1. Inserting a disposable site with no property_id...")
    site = c.schema("monitoring").table("sites").insert({
        "site_id": _TEST_SITE_ID, "display_name": "__migration_047_test__",
    }).execute().data[0]

    try:
        property_id = site.get("property_id")
        assert property_id, f"expected the trigger to set property_id, got {site!r}"
        print(f"   property_id set automatically: {property_id}")

        prop = c.table("site_properties").select("*").eq("id", property_id).single().execute().data
        assert prop["name"] == "__migration_047_test__", f"expected the site's display_name as the property name, got {prop!r}"
        print(f"   auto-created property name: {prop['name']!r} (correct)")

        print("\nMigration 047 verified.")
    finally:
        c.schema("monitoring").table("sites").delete().eq("site_id", _TEST_SITE_ID).execute()
        if site.get("property_id"):
            c.table("site_properties").delete().eq("id", site["property_id"]).execute()
        print("   test site + auto-created property cleaned up")


if __name__ == "__main__":
    main()
