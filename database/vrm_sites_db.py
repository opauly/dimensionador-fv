from __future__ import annotations
"""Read/write access to vrm.sites' `public_client_id` link, for the
Dimensionador "Clientes" admin panel (pages/05_admin.py).

`vrm.sites.public_client_id` (migration 012) was a soft pointer to
`public.clients` from the start — deliberately no FK, so the `vrm` schema
stays dumpable into its own Supabase project without cross-schema
constraints to untangle (see that migration's own comment) — but nothing
ever read or wrote it until now. Mirrors `monitoring_sites_db.py`'s own
shape exactly; kept as a separate module rather than folded into it since
the two live in different schemas with a different column name for the same
concept (`public_client_id` here, `client_id` there).
"""
from database.supabase_client import get_client


def list_vrm_sites_for_linking() -> list[dict]:
    result = (
        get_client()
        .schema("vrm")
        .table("sites")
        .select("site_id, display_name, public_client_id, active")
        .order("display_name")
        .execute()
    )
    return result.data or []


def set_site_public_client(site_id: str, client_id: str | None) -> None:
    (
        get_client()
        .schema("vrm")
        .table("sites")
        .update({"public_client_id": client_id})
        .eq("site_id", site_id)
        .execute()
    )
