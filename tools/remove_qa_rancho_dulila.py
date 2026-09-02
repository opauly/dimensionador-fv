"""One-off: delete the QA-artifact duplicate of Roberto Villalobos's Rancho
DuliLa (test-portal-qa-rancho-dulila, vrm_installation_id 855465, same
installation as roberto-villalobos-rancho-dulila which already lives
correctly under Pauly & Co Portfolio). Confirmed 2026-09-02.

Usage:
    python -m tools.remove_qa_rancho_dulila
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402

SITE_ID = "test-portal-qa-rancho-dulila"
CHILD_TABLES = [
    "energy_daily", "daily_health", "alarm_events", "critical_alerts",
    "ingestion_log", "site_snapshots", "report_runs",
]


def main() -> None:
    c = get_client()
    site = c.schema("vrm").table("sites").select("site_id,vrm_installation_id").eq("site_id", SITE_ID).execute().data
    if not site:
        print(f"{SITE_ID} already gone — nothing to do")
        return
    print(f"Deleting {site[0]}")
    for t in CHILD_TABLES:
        n = len(c.schema("vrm").table(t).delete().eq("site_id", SITE_ID).execute().data or [])
        if n:
            print(f"  removed {n} row(s) from vrm.{t}")
    c.schema("vrm").table("sites").delete().eq("site_id", SITE_ID).execute()
    print(f"Removed vrm.sites.{SITE_ID}")


if __name__ == "__main__":
    main()
