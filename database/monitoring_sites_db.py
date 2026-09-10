from __future__ import annotations
"""Read/write access to monitoring.sites from the solar tool's admin panel.

Uses the same service_role client as the rest of the app, switched to the
`monitoring` schema — no separate credentials or grants needed, migration
004 already grants service_role full access schema-wide.
"""
from database.supabase_client import get_client


def list_monitoring_sites() -> list[dict]:
    result = (
        get_client()
        .schema("monitoring")
        .table("sites")
        .select("id, site_id, display_name, client_id, active, brand")
        .order("display_name")
        .execute()
    )
    return result.data or []


def set_site_client(site_id: str, client_id: str | None) -> None:
    """site_id here is monitoring.sites.site_id (the text slug), not the
    bigint id column."""
    (
        get_client()
        .schema("monitoring")
        .table("sites")
        .update({"client_id": client_id})
        .eq("site_id", site_id)
        .execute()
    )


def create_monitoring_site(client_id: str, site_id: str, **fields) -> dict:
    """New non-Victron site, client_id required from the start
    (database/site_registration_db.py:register_new_site() is the intended caller —
    that's where client_id becomes non-optional). **fields carries whatever other
    monitoring.sites columns the caller has values for (display_name, location,
    latitude/longitude, country, timezone, system_type, pv_kwp, owner,
    commissioned_at, report_language, active, brand, panel_count, inverter_count,
    battery_count, battery_nominal_kwh, battery_dod_pct, monitoring_urls) — passed
    straight through as an insert payload, the same shape victron/ingest.py:upsert_site()
    already uses, for the same reason: the table is the source of truth for which
    fields exist, not this function. `battery_usable_kwh` is a generated column
    (migration 019, mirrors vrm.sites) and must never be in **fields. `brand` is
    NOT NULL with no default (migration 033, applied 2026-09-10) — always required."""
    payload = {"client_id": client_id, "site_id": site_id, **fields}
    result = get_client().schema("monitoring").table("sites").insert(payload).execute()
    return result.data[0]
