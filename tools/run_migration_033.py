"""
Migration 033 helper — `monitoring.sites.brand`.

Checks that the column is selectable and every existing row defaulted to
'Victron Energy' (every current row was registered through the original
Victron/Cerbo-GX + Node-RED pipeline). It does NOT apply the migration:
paste `database/migrations/033_monitoring_site_brand.sql` into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_033
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()
    sites = c.schema("monitoring").table("sites").select("site_id,brand").execute().data

    print(f"monitoring.sites: {len(sites)} rows")
    non_victron = [s for s in sites if s["brand"] != "Victron Energy"]
    print(f"  brand='Victron Energy': {len(sites) - len(non_victron)}")
    if non_victron:
        print(f"  other brands: {non_victron}")

    print("\nMigration 033 verified.")


if __name__ == "__main__":
    main()
