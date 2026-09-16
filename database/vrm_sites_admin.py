from __future__ import annotations
"""Minimal `vrm` schema writes needed to register one of Oscar's own Victron
sites from the admin "new site" form (database/site_registration_db.py).

Forked out of victron/ingest.py rather than imported from it: victron/ is
moving to its own repo (VRM Monitor split), while this admin-portfolio
registration path is Dimensionador's own CRM feature and stays here. Only
the handful of functions this one caller needs were copied — this is not a
general-purpose vrm.customers/vrm.sites client, and nothing here should grow
scope beyond "register a new site for an existing public.clients row."
"""
import re
import unicodedata

from database.supabase_client import get_client

SCHEMA = "vrm"


def _t(name: str):
    return get_client().schema(SCHEMA).table(name)


def slugify(value: str) -> str:
    """Lowercase ASCII slug, matching vrm.customers.slug's CHECK constraint.

    Accents are transliterated (i -> i), not stripped — kept identical to
    victron/ingest.py's slugify() so a site registered from either path
    produces the same site_id for the same name.
    """
    decomposed = unicodedata.normalize("NFKD", str(value).strip().lower())
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    if not s or not s[0].isalnum():
        raise ValueError(f"Cannot build a slug from {value!r}")
    return s


def upsert_customer(name: str, slug: str | None = None, **fields) -> dict:
    """Create or update a vrm.customers row by slug."""
    slug = slugify(slug or name)
    existing = _t("customers").select("*").eq("slug", slug).limit(1).execute().data
    payload = {"name": name, "slug": slug, **fields}
    if existing:
        row = _t("customers").update(payload).eq("slug", slug).execute().data
        return (row or existing)[0]
    return _t("customers").insert(payload).execute().data[0]


def upsert_site(customer_id: str, site_id: str, display_name: str, **fields) -> dict:
    """Create or update a vrm.sites row by site_id."""
    existing = _t("sites").select("*").eq("site_id", site_id).limit(1).execute().data
    payload = {"customer_id": customer_id, "site_id": site_id,
               "display_name": display_name, **fields}
    if existing:
        row = _t("sites").update(payload).eq("site_id", site_id).execute().data
        return (row or existing)[0]
    return _t("sites").insert(payload).execute().data[0]


_ADMIN_PORTFOLIO_SLUG = "pauly-co-portfolio"


def get_or_create_admin_portfolio_customer() -> dict:
    """The one shared vrm.customers tenant every admin-managed Victron site already
    uses (confirmed live, 2026-09-09: all of them point at this same customer_id) —
    never create a second one. This is an implementation detail of "register a new
    site for one of Oscar's own clients", not a real VRM Monitor product-tenant
    decision — nothing here should ever surface this row as something to pick or edit."""
    return upsert_customer("Pauly & Co Portfolio", slug=_ADMIN_PORTFOLIO_SLUG, origin="admin")
