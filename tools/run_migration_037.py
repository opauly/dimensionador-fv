"""
Migration 037 helper — health-score correctness fixes.

Verifies the redefined vrm.compute_daily_health()/monitoring.compute_daily_
health() behave as intended, then recomputes every real site's stored
daily_health rows so the fix applies retroactively, not just to future
syncs. It does NOT apply the migration: paste
  database/migrations/037_health_score_fixes.sql
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_037
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()

    print("1. Spot-checking a known VRM-API site with NULL battery_discharge_kwh...")
    site = c.schema("vrm").table("sites").select("site_id").eq("source", "vrm_api").limit(1).execute().data
    assert site, "no vrm_api sites found to test against"
    test_site_id = site[0]["site_id"]
    ed = (
        c.schema("vrm").table("energy_daily").select("date,battery_discharge_kwh")
        .eq("site_id", test_site_id).order("date", desc=True).limit(1).execute().data
    )
    assert ed, f"no energy_daily rows for {test_site_id}"
    assert ed[0]["battery_discharge_kwh"] is None, "expected NULL battery_discharge_kwh on a vrm_api site"
    row = c.schema("vrm").rpc(
        "compute_daily_health", {"p_site_id": test_site_id, "p_date": ed[0]["date"], "p_dump_type": "vrm_api"}
    ).execute().data
    print(f"   {test_site_id} {ed[0]['date']}: battery_cycles={row.get('battery_cycles')} (expect null, was 0.00 before the fix)")
    assert row.get("battery_cycles") is None, "battery_cycles should be NULL when battery_discharge_kwh is NULL"
    print("   OK — no longer fabricating a 0")

    print("\n2. Recomputing all real vrm_api sites' stored daily_health (last 90 days)...")
    from datetime import date, timedelta
    since = (date.today() - timedelta(days=90)).isoformat()
    sites = c.schema("vrm").table("sites").select("site_id").eq("source", "vrm_api").execute().data
    for s in sites:
        n = c.schema("vrm").rpc(
            "recompute_health", {"p_site_id": s["site_id"], "p_from": since, "p_to": None}
        ).execute().data
        print(f"   {s['site_id']}: recomputed {n} day(s)")

    print("\n3. Recomputing monitoring-schema sites (no bulk recompute_health() there -- per-date loop)...")
    mon_sites = c.schema("monitoring").table("sites").select("site_id").execute().data
    for s in mon_sites:
        rows = (
            c.schema("monitoring").table("energy_daily").select("date,dump_type")
            .eq("site_id", s["site_id"]).gte("date", since).execute().data
        )
        if not rows:
            continue
        for r in rows:
            c.schema("monitoring").rpc(
                "compute_daily_health", {"p_site_id": s["site_id"], "p_date": r["date"], "p_dump_type": r["dump_type"]}
            ).execute()
        print(f"   {s['site_id']}: recomputed {len(rows)} day(s)")

    print("\nMigration 037 verified and applied retroactively.")


if __name__ == "__main__":
    main()
