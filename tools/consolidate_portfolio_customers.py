"""
One-off: consolidate the 7 placeholder vrm.customers rows (real
installations added via admin VRM-fleet linking, never invited, no
subscription — Lori Pickett, Rebeca Ruiz, Karen Montealegre, Roberto
Villalobos, Emtec CR, Giancarlo Vargas, Jorge Ramírez) into one dedicated
internal customer, "Pauly & Co Portfolio" (origin='admin').

Reassigns their 13 vrm.sites rows' customer_id, then deletes the 7 now-empty
customer rows. Does NOT touch site data, snapshots, energy_daily,
daily_health, alarm_events, or critical_alerts — only the customer_id FK and
the customer rows themselves. Refuses if any target customer has a real
auth_user_id (would mean it's not actually a placeholder).

Usage:
    python -m tools.consolidate_portfolio_customers
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402
from victron import ingest as victron_ingest  # noqa: E402

TARGET_NAMES = [
    "Lori Pickett", "Rebeca Ruiz", "Karen Montealegre", "Roberto Villalobos",
    "Emtec CR", "Giancarlo Vargas", "Jorge Ramírez",
]


def main() -> None:
    c = get_client()

    old_customers = (
        c.schema("vrm").table("customers")
        .select("id,name,auth_user_id")
        .in_("name", TARGET_NAMES)
        .execute().data
    )
    print(f"Found {len(old_customers)} customers to consolidate:")
    for cu in old_customers:
        assert cu["auth_user_id"] is None, f"REFUSING: {cu['name']} has an auth_user_id"
        print(f'  {cu["name"]!r} ({cu["id"]})')
    old_ids = [cu["id"] for cu in old_customers]

    sites_before = (
        c.schema("vrm").table("sites").select("site_id,customer_id")
        .in_("customer_id", old_ids).execute().data
    )
    print(f"\n{len(sites_before)} sites to reassign")

    portfolio = victron_ingest.upsert_customer(
        "Pauly & Co Portfolio", account_type="owner", origin="admin", active=True,
    )
    print(f"\nPortfolio customer: {portfolio['id']}")

    result = (
        c.schema("vrm").table("sites").update({"customer_id": portfolio["id"]})
        .in_("customer_id", old_ids).execute().data
    )
    print(f"Reassigned {len(result)} sites to Portfolio customer")

    deleted = c.schema("vrm").table("customers").delete().in_("id", old_ids).execute().data
    print(f"Deleted {len(deleted)} now-empty customer rows: {[d['name'] for d in deleted]}")

    remaining = (
        c.schema("vrm").table("sites").select("site_id", count="exact")
        .in_("customer_id", old_ids).execute().count
    )
    print(f"\nSanity check: sites still pointing at deleted customer ids = {remaining} (should be 0)")


if __name__ == "__main__":
    main()
