"""
Migration 042 helper — vrm.get_marketing_stats() (marketing page stats
banner: sites monitored, installed kWp, cumulative kWh tracked).

Calls the new function and cross-checks it against a plain row-fetch
computed independently, so a bug in the SQL aggregate can't slip through
just because the function itself ran without error. It does NOT apply the
migration: paste
  database/migrations/042_marketing_stats.sql
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_042
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()

    print("1. Calling vrm.get_marketing_stats()...")
    row = c.schema("vrm").rpc("get_marketing_stats", {}).execute().data
    assert row, "get_marketing_stats() returned no rows"
    stats = row[0] if isinstance(row, list) else row
    print(f"   sites_monitored={stats['sites_monitored']}")
    print(f"   installed_kwp={stats['installed_kwp']}")
    print(f"   kwh_tracked={stats['kwh_tracked']}")

    print("\n2. Cross-checking against a plain row fetch...")
    sites = c.schema("vrm").table("sites").select("pv_kwp").eq("active", True).execute().data
    expected_sites = len(sites)
    expected_kwp = sum((s["pv_kwp"] or 0) for s in sites)

    total_kwh = 0.0
    offset = 0
    page = 1000
    while True:
        rows = c.schema("vrm").table("energy_daily").select("pv_kwh").range(offset, offset + page - 1).execute().data
        if not rows:
            break
        total_kwh += sum((r["pv_kwh"] or 0) for r in rows)
        if len(rows) < page:
            break
        offset += page

    print(f"   expected sites_monitored={expected_sites}, installed_kwp={expected_kwp:.2f}, kwh_tracked={total_kwh:.1f}")

    assert stats["sites_monitored"] == expected_sites, "sites_monitored mismatch"
    assert abs(float(stats["installed_kwp"]) - expected_kwp) < 0.01, "installed_kwp mismatch"
    assert abs(float(stats["kwh_tracked"]) - total_kwh) < 1.0, "kwh_tracked mismatch"

    print("\nMigration 042 verified — RPC output matches an independent row-fetch sum.")


if __name__ == "__main__":
    main()
