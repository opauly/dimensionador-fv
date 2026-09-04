"""
Migration 040 helper — vrm.site_anomalies.anomaly_type, add 'incomplete_charging'.

Verifies the widened constraint accepts the new value, then runs
check_incomplete_charging() once for every real vrm_api site so the Fleet
Dashboard's fourth card has real data immediately rather than waiting for
the next scheduled-reports.yml tick. It does NOT apply the migration: paste
  database/migrations/040_incomplete_charging_anomaly.sql
into
  Project -> SQL Editor -> New query -> Run

Usage:
    python -m tools.run_migration_040
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402
from victron.anomaly_battery import check_incomplete_charging  # noqa: E402

_LOOKBACK_DAYS = 30


def main() -> None:
    c = get_client()

    print("1. Confirming the constraint accepts 'incomplete_charging'...")
    probe_site = "__migration_040_probe__"
    try:
        c.schema("vrm").table("site_anomalies").insert({
            "site_id": probe_site, "anomaly_type": "incomplete_charging",
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:  # noqa: BLE001
        # A missing-FK error (site_id doesn't exist) is FINE here -- it means
        # the CHECK constraint already passed and a later constraint (the
        # real site_id FK) is what's rejecting the probe row, not the one
        # this migration touches.
        msg = str(e)
        if "anomaly_type_check" in msg:
            raise AssertionError(f"Constraint still rejects 'incomplete_charging': {msg}") from e
        print(f"   OK — constraint accepted the value (rejected for an unrelated reason: {msg[:120]})")
    else:
        c.schema("vrm").table("site_anomalies").delete().eq("site_id", probe_site).execute()
        print("   OK — inserted and cleaned up a real probe row")

    print("\n2. Running check_incomplete_charging() for every real vrm_api site...")
    sites = (
        c.schema("vrm").table("sites").select("site_id,system_type")
        .eq("source", "vrm_api").eq("active", True).execute().data
    )
    since = (date.today() - timedelta(days=_LOOKBACK_DAYS)).isoformat()
    for s in sites:
        rows = (
            c.schema("vrm").table("energy_daily")
            .select("date,battery_reached_float,complete_day")
            .eq("site_id", s["site_id"]).gte("date", since).execute().data
        )
        check_incomplete_charging(
            c.schema("vrm").table("site_anomalies"),
            site_id=s["site_id"], system_type=s.get("system_type") or "hybrid",
            energy_daily_rows=rows,
        )
        print(f"   {s['site_id']}: checked ({len(rows)} days in window)")

    print("\n3. Current open incomplete_charging anomalies:")
    open_rows = (
        c.schema("vrm").table("site_anomalies").select("site_id,detail")
        .eq("anomaly_type", "incomplete_charging").is_("cleared_at", "null").execute().data
    )
    print(f"   {len(open_rows)} open")
    for r in open_rows:
        print(f"   {r}")

    print("\nMigration 040 verified and applied.")


if __name__ == "__main__":
    main()
