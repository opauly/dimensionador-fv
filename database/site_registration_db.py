from __future__ import annotations
"""Unified new-site registration, tied to a public.clients row from the start.

Sites previously got created through several disconnected paths — Node-RED
provisioning writes directly to monitoring.sites, pages/06_vrm_monitor.py's manual
form and its CSV upload write to vrm.sites via victron/ingest.py — and none of them
required a link back to public.clients (Dimensionador's own CRM). That's exactly how
Emtec CR, Proyecto gV, and Proyecto JR ended up as vrm.sites rows with no
public_client_id (confirmed live, 2026-09-09). This module is the one entry point
that makes that link mandatory: pages/05_admin.py's per-client "new site" form is the
only caller, so a client is already in hand before this is ever invoked.

Deliberately separate from victron/ingest.py (which stays VRM-only in scope) and from
database/site_properties_db.py (which stays maintenance-register-only in scope,
untouched here — migration 047's trigger creates the maintenance property for
whatever this module inserts, automatically, regardless of which path).
"""
from database.clients_db import get_client_by_id
from database.monitoring_sites_db import create_monitoring_site
from victron.ingest import slugify, get_or_create_admin_portfolio_customer, upsert_site


def _site_id_for(client_name: str, display_name: str) -> str:
    """Namespaced by client, same reasoning victron/ingest.py:make_site_id() already
    gives for vrm.sites: two different clients can each plausibly pick a site name
    like "Casa Principal," and site_id is UNIQUE on both schemas."""
    return f"{slugify(client_name)}-{slugify(display_name)}"


def register_new_site(client_id: str, display_name: str, *, is_victron: bool, **fields) -> dict:
    """The one function the new-site UI calls.

    `is_victron=False` -> `create_monitoring_site()`, `client_id` set directly.
    `is_victron=True` -> resolves the shared admin-portfolio vrm.customers tenant
    (never a new one) and calls `upsert_site(..., public_client_id=client_id)`.

    `fields` is whatever the caller collected for that site type (see
    pages/05_admin.py:_client_new_site_form()) — passed straight through as an
    insert payload either way. `battery_usable_kwh` must never be in `fields` for
    either path — it's a generated column on BOTH vrm.sites and monitoring.sites
    (migration 019 made it generated on both), computed from `battery_nominal_kwh`/
    `battery_dod_pct`; Postgres rejects a direct write to it on either table.
    """
    client = get_client_by_id(client_id)
    if not client:
        raise ValueError(f"no client with id {client_id!r}")

    site_id = _site_id_for(client["name"], display_name)

    if is_victron:
        portfolio = get_or_create_admin_portfolio_customer()
        return upsert_site(
            portfolio["id"], site_id, display_name,
            public_client_id=client_id,
            **fields,
        )

    return create_monitoring_site(client_id, site_id, display_name=display_name, **fields)
