"""
Migration 039 helper — estimated battery cycling from SOC swing.

Verifies the new estimate fires correctly on a real high-swing day, then
recomputes every VRM-API and monitoring-schema site's stored daily_health
so the new notes/deductions apply retroactively. It does NOT apply the
migration: paste
  database/migrations/039_estimated_battery_cycles.sql
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_039
"""
from __future__ import annotations

from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()

    print("1. Finding a real day with a deep SOC swing to verify against...")
    sites = c.schema("vrm").table("sites").select("site_id").eq("source", "vrm_api").execute().data
    site_ids = [s["site_id"] for s in sites]
    ed = (
        c.schema("vrm").table("energy_daily").select("site_id,date,min_soc,max_soc")
        .in_("site_id", site_ids).not_.is_("min_soc", "null").not_.is_("max_soc", "null")
        .execute().data
    )
    candidate = max(ed, key=lambda r: r["max_soc"] - r["min_soc"])
    swing = (candidate["max_soc"] - candidate["min_soc"]) / 100
    print(f"   {candidate['site_id']} {candidate['date']}: swing={swing:.2f} (min={candidate['min_soc']}, max={candidate['max_soc']})")

    row = c.schema("vrm").rpc(
        "compute_daily_health", {"p_site_id": candidate["site_id"], "p_date": candidate["date"], "p_dump_type": "vrm_api"}
    ).execute().data
    print(f"   notes: {row.get('notes')}")
    if swing > 0.65:
        assert "battery cycling" in (row.get("notes") or "").lower(), "expected a cycling note on a >0.65 swing day"
        print("   OK — estimated cycling note fired as expected")
    else:
        print("   (below 0.65 threshold — no cycling note expected, this is fine)")

    print("\n2. Recomputing all real vrm_api sites' stored daily_health (last 90 days)...")
    since = (date.today() - timedelta(days=90)).isoformat()
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

    print("\n4. How often does the new estimate actually fire now?")
    all_health = c.schema("vrm").table("daily_health").select("notes").in_("site_id", site_ids).execute().data
    with_note = [r for r in all_health if "estimated from SOC swing" in (r["notes"] or "")]
    print(f"   {len(with_note)} of {len(all_health)} rows now show an estimated-cycling note")

    print("\nMigration 039 verified and applied retroactively.")


if __name__ == "__main__":
    main()
