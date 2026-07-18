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
        .select("id, site_id, display_name, client_id, active")
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
