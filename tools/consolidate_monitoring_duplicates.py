"""
One-off: resolve the remaining 4 of 9 monitoring.sites rows confirmed
(2026-09-02, one pairing at a time with Oscar) to duplicate real
installations already tracked in vrm.sites under the "Pauly & Co
Portfolio" customer.

The first 5 (Roberto Villalobos, Karen Montealegre bare + Guarda, Rebeca
Ruiz Casona + Cabaña — simple client_id copy + monitoring row removal)
already ran successfully. This file now covers only the remaining 4:

  2. New "no internet, Victron, can never sync" vrm.sites rows created
     (source='csv_upload', no vrm_installation_id — will show "Never
     synced" in Fleet Dashboard, not "Stale"):
     karen-montealegre-porton, rebeca-ruiz-porton-cabana
  3. QA-artifact vrm.sites rows deleted (with their data) and replaced by
     a proper official vrm.sites row reusing the same vrm_installation_id
     (Apartamento's QA row had 33 real synced days; Casita's had 0 — both
     get deleted regardless, the QA customer itself is disposable):
     rebeca-ruiz-el-encino-apartamento (installation 523804),
     rebeca-ruiz-el-encino-casita (installation 524935)
     -> after this runs, use /admin/vrm-fleet's existing per-site Sync
        button (From/To date fields) to backfill these two's history.

`battery_usable_kwh` is a GENERATED column on vrm.sites (migration 019:
computed from battery_nominal_kwh * battery_dod_pct / 100) — unlike
monitoring.sites where it's a plain stored column. Pass the nominal/DoD
pair instead of the computed value; never insert battery_usable_kwh
directly on the vrm side.

Explicitly excludes Lori Pickett's 3 monitoring sites (vista-atenas-lp-*) —
those have real, irreplaceable history with no equivalent in vrm. Never
touch those.

Refuses if the Portfolio customer doesn't already exist, or if a target
monitoring row is already gone (already handled).

Usage:
    python -m tools.consolidate_monitoring_duplicates
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402
from victron import ingest as victron_ingest  # noqa: E402

CHILD_TABLES = [
    "energy_daily", "daily_health", "alarm_events", "critical_alerts",
    "ingestion_log", "site_snapshots", "report_runs",
]


def _delete_vrm_site_and_children(c, site_id: str) -> None:
    for t in CHILD_TABLES:
        c.schema("vrm").table(t).delete().eq("site_id", site_id).execute()
    c.schema("vrm").table("sites").delete().eq("site_id", site_id).execute()


def main() -> None:
    c = get_client()

    portfolio = c.schema("vrm").table("customers").select("id").eq("name", "Pauly & Co Portfolio").execute().data
    assert portfolio, "Portfolio customer not found — run tools.consolidate_portfolio_customers first"
    portfolio_id = portfolio[0]["id"]
    print(f"Portfolio customer: {portfolio_id}\n")

    # ── New "no internet" vrm.sites rows ──
    no_internet = [
        {
            "mon_id": "karen-montealegre-porton",
            "vrm_site_id": "karen-montealegre-porton",
            "display_name": "Proyecto KM Ukiyo (Portón)",
        },
        {
            "mon_id": "rebeca-ruiz-porton-cabana",
            "vrm_site_id": "rebeca-ruiz-el-encino-porton-cabana",
            "display_name": "El Encino (Portón cabaña)",
        },
    ]
    for item in no_internet:
        mon = c.schema("monitoring").table("sites").select("*").eq("site_id", item["mon_id"]).execute().data
        if not mon:
            print(f"monitoring.sites.{item['mon_id']} already gone — skipping\n")
            continue
        m = mon[0]
        victron_ingest.upsert_site(
            portfolio_id, item["vrm_site_id"], item["display_name"],
            source="csv_upload", vrm_sync_enabled=False,
            pv_kwp=m.get("pv_kwp"),
            battery_nominal_kwh=m.get("battery_nominal_kwh"), battery_dod_pct=m.get("battery_dod_pct"),
            location=m.get("location"), latitude=m.get("latitude"), longitude=m.get("longitude"),
            commissioned_at=m.get("commissioned_at"), country=m.get("country"),
            public_client_id=m.get("client_id"),
        )
        print(f"Created vrm.sites.{item['vrm_site_id']} (Never synced, no vrm_installation_id)")
        c.schema("monitoring").table("sites").delete().eq("site_id", item["mon_id"]).execute()
        print(f"Removed monitoring.sites.{item['mon_id']}\n")

    # ── QA-artifact replacement ──
    qa_replacements = [
        {
            "qa_vrm_id": "test-portal-qa-el-encino-apartamento",
            "mon_id": "rebeca-ruiz-apartamento",
            "new_vrm_id": "rebeca-ruiz-el-encino-apartamento",
            "display_name": "El Encino (Apartamento)",
        },
        {
            "qa_vrm_id": "test-portal-qa-el-encino-casita",
            "mon_id": "rebeca-ruiz-casita",
            "new_vrm_id": "rebeca-ruiz-el-encino-casita",
            "display_name": "El Encino (Casita)",
        },
    ]
    for item in qa_replacements:
        qa = c.schema("vrm").table("sites").select("vrm_installation_id").eq("site_id", item["qa_vrm_id"]).execute().data
        if not qa:
            print(f"QA site {item['qa_vrm_id']} already gone — skipping\n")
            continue
        installation_id = qa[0]["vrm_installation_id"]
        assert installation_id, f"QA site {item['qa_vrm_id']} has no vrm_installation_id to reuse"

        mon = c.schema("monitoring").table("sites").select("*").eq("site_id", item["mon_id"]).execute().data
        assert mon, f"monitoring site {item['mon_id']} not found"
        m = mon[0]

        _delete_vrm_site_and_children(c, item["qa_vrm_id"])
        print(f"Deleted QA site {item['qa_vrm_id']} and its data")

        victron_ingest.upsert_site(
            portfolio_id, item["new_vrm_id"], item["display_name"],
            source="vrm_api", vrm_installation_id=installation_id, vrm_sync_enabled=True,
            pv_kwp=m.get("pv_kwp"),
            battery_nominal_kwh=m.get("battery_nominal_kwh"), battery_dod_pct=m.get("battery_dod_pct"),
            location=m.get("location"), latitude=m.get("latitude"), longitude=m.get("longitude"),
            commissioned_at=m.get("commissioned_at"), country=m.get("country"),
            public_client_id=m.get("client_id"),
        )
        print(f"Created official vrm.sites.{item['new_vrm_id']} (installation {installation_id}, ready to sync)")
        c.schema("monitoring").table("sites").delete().eq("site_id", item["mon_id"]).execute()
        print(f"Removed monitoring.sites.{item['mon_id']}\n")

    print("Done. Use /admin/vrm-fleet's per-site Sync button to backfill history for:")
    print("  - rebeca-ruiz-el-encino-apartamento")
    print("  - rebeca-ruiz-el-encino-casita")


if __name__ == "__main__":
    main()
