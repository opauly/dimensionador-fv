from __future__ import annotations
"""Site register & preventive maintenance (Phase 10).

A "property" (`public.site_properties`) groups one or more sites that share one
physical location and one maintenance visit — e.g. Rebeca Ruiz's 5 El Encino sites
are 5 rows in `vrm.sites` but 1 property with 1 visit schedule. Sites can live in
EITHER `monitoring.sites` (Oscar's own Node-RED/Cerbo-GX fleet) or `vrm.sites` (VRM
Monitor's VRM-API/CSV sites) — confirmed live (2026-09-07) that 9 of the register's
real sites now live only in `vrm.sites`, moved there by an unrelated duplicate-site
consolidation after this schema was first scoped. Every function here is schema-blind
on purpose, following the exact merge pattern
`pages/05_admin.py:_client_sites_linker()` already established for client-linking
(`database/monitoring_sites_db.py` + `database/vrm_sites_db.py`) — this module is
that same pattern applied to property-linking instead.
"""
from database.supabase_client import get_client

# monitoring.sites (migration 011) and vrm.sites (migration 012) don't carry the same
# columns — monitoring.sites has panel_count/inverter_count/battery_count/
# monitoring_urls, vrm.sites has none of those (pv_kwp instead, a kW rating, not a
# panel count) — so each schema needs its own select list, not one shared string.
_COMMON_FIELDS = "site_id, display_name, location, commissioned_at, property_id"
_MONITORING_FIELDS = f"{_COMMON_FIELDS}, panel_count, inverter_count, battery_count, monitoring_urls, client_id"
_VRM_FIELDS = f"{_COMMON_FIELDS}, pv_kwp, public_client_id"

# Lori Pickett's 3 monitoring.sites rows (vista-atenas-lp-m1/m2/m3) are confirmed dead
# leftovers (Oscar, 2026-09-08): a legacy Node-RED write path predating her real
# vrm.sites rows for the same 3 meters. Every other client in the register is
# single-schema — this is a one-off, hand-verified exclusion, not a general
# monitoring-vs-vrm rule (there's no reliable way to auto-detect "these two rows are
# the same physical meter" across schemas). Excluded here, at the source, rather than
# left visible-but-unlinked — the maintenance register should never have to think
# about them at all.
_EXCLUDED_MONITORING_SITE_IDS = {"vista-atenas-lp-m1", "vista-atenas-lp-m2", "vista-atenas-lp-m3"}


def list_all_sites_for_maintenance() -> list[dict]:
    """Every site from both schemas, tagged with which schema/client-column it came
    from, for the property-linker UI and property detail pages."""
    monitoring_sites = (
        get_client()
        .schema("monitoring")
        .table("sites")
        .select(_MONITORING_FIELDS)
        .order("display_name")
        .execute()
    ).data or []
    monitoring_sites = [s for s in monitoring_sites if s["site_id"] not in _EXCLUDED_MONITORING_SITE_IDS]

    vrm_sites = (
        get_client()
        .schema("vrm")
        .table("sites")
        .select(_VRM_FIELDS)
        .order("display_name")
        .execute()
    ).data or []

    return [
        {**s, "schema_name": "monitoring", "client_id": s.get("client_id")}
        for s in monitoring_sites
    ] + [
        {**s, "schema_name": "vrm", "client_id": s.get("public_client_id")}
        for s in vrm_sites
    ]


def link_site_to_property(site_id: str, schema_name: str, property_id: str | None) -> None:
    """`property_id=None` unlinks the site from any property."""
    if schema_name not in ("monitoring", "vrm"):
        raise ValueError(f"unknown schema_name: {schema_name!r}")
    (
        get_client()
        .schema(schema_name)
        .table("sites")
        .update({"property_id": property_id})
        .eq("site_id", site_id)
        .execute()
    )


def create_property(name: str, interval_days: int = 365) -> dict:
    """No client/location here — both are derived from whichever sites end up linked
    to this property (see module docstring). Link a site to it right after creating."""
    payload = {"name": name, "maintenance_interval_days": interval_days}
    result = get_client().table("site_properties").insert(payload).execute()
    return result.data[0]


def seed_properties_from_unlinked_sites() -> int:
    """Creates one property per currently-unlinked site (either schema) and links it —
    every site already in monitoring.sites/vrm.sites is real installed equipment Oscar
    maintains, so a fresh register should start pre-populated from it rather than
    require retyping structure that already exists. 1:1 is the deliberately safe
    default: several real sites are one physical property with one shared visit (e.g.
    Rebeca Ruiz's 5 El Encino sites) but that grouping isn't reliably recoverable from
    the data alone (see module docstring / PHASES.md's Karen Montealegre example) — use
    `merge_properties()` afterward for the cases you know should collapse into one.
    Idempotent: only acts on sites with no `property_id` yet, so safe to run again
    after creating new sites elsewhere.

    Returns the number of properties created.
    """
    unlinked = [s for s in list_all_sites_for_maintenance() if not s.get("property_id")]
    for s in unlinked:
        prop = create_property(name=s.get("display_name") or s["site_id"])
        link_site_to_property(s["site_id"], s["schema_name"], prop["id"])
    return len(unlinked)


def merge_properties(source_id: str, target_id: str) -> None:
    """Moves every site and visit from `source_id` onto `target_id`, then deletes
    `source_id` — for collapsing the seed's 1-site-per-property default into one shared
    property once you know several sites really are the same physical location."""
    if source_id == target_id:
        raise ValueError("cannot merge a property into itself")

    all_sites = list_all_sites_for_maintenance()
    for s in all_sites:
        if s.get("property_id") == source_id:
            link_site_to_property(s["site_id"], s["schema_name"], target_id)

    get_client().table("maintenance_visits").update(
        {"property_id": target_id}
    ).eq("property_id", source_id).execute()

    get_client().table("site_properties").delete().eq("id", source_id).execute()


def delete_property(property_id: str) -> None:
    """Unlinks every site first (so they go back to "unvinculado" rather than
    disappearing), then deletes the property. Its `maintenance_visits` cascade-delete
    via the FK (migration 045) — fine here since a property being deleted is either a
    seeded duplicate nobody wants or was just merged elsewhere, never a property with
    visit history worth keeping under a different name (use `merge_properties()` for
    that case instead)."""
    all_sites = list_all_sites_for_maintenance()
    for s in all_sites:
        if s.get("property_id") == property_id:
            link_site_to_property(s["site_id"], s["schema_name"], None)
    get_client().table("site_properties").delete().eq("id", property_id).execute()


def _derive_client_and_location(property_id: str, all_sites: list[dict]) -> dict:
    """First non-null client_id/location among the property's linked sites — not an
    aggregate, just "whatever this property's sites agree on" for display. A property
    with no linked site yet gets None for both, which the UI shows honestly as
    "not set up" rather than a guess."""
    linked = [s for s in all_sites if s.get("property_id") == property_id]
    client_id = next((s["client_id"] for s in linked if s.get("client_id")), None)
    location = next((s["location"] for s in linked if s.get("location")), None)
    return {"client_id": client_id, "location": location, "site_count": len(linked)}


def list_properties(client_id: str | None = None) -> list[dict]:
    """Enriched with derived `client_id`/`location`/`site_count` from currently-linked
    sites — computed fresh on every call, so it can never go stale (see module
    docstring). `client_id` filters AFTER enrichment since it isn't a stored column."""
    properties = get_client().table("site_properties").select("*").order("name").execute().data or []
    all_sites = list_all_sites_for_maintenance()
    enriched = [{**p, **_derive_client_and_location(p["id"], all_sites)} for p in properties]
    if client_id:
        enriched = [p for p in enriched if p["client_id"] == client_id]
    return enriched


def get_property(property_id: str, all_sites: list[dict] | None = None) -> dict | None:
    result = (
        get_client().table("site_properties").select("*").eq("id", property_id).execute()
    )
    if not result.data:
        return None
    property_row = result.data[0]
    all_sites = all_sites if all_sites is not None else list_all_sites_for_maintenance()
    return {**property_row, **_derive_client_and_location(property_id, all_sites)}


def get_property_bundle(property_id: str) -> dict:
    """One call per detail-page render, mirroring `projects_db.py:get_project_bundle()`."""
    all_sites = list_all_sites_for_maintenance()
    sites = [s for s in all_sites if s.get("property_id") == property_id]
    return {
        "property": get_property(property_id, all_sites=all_sites),
        "sites": sites,
        "visits": list_visits(property_id),
    }


def get_maintenance_status(property_id: str) -> dict | None:
    """Wraps `public.get_property_maintenance_status()` (migration 045) — the
    Postgres-side source of truth. The overdue LIST view uses
    `calculations/maintenance.py:compute_status()` instead (same logic, no
    per-property round trip); this is for the property detail page, and for
    anything cross-checking the two agree."""
    result = get_client().rpc(
        "get_property_maintenance_status", {"p_property_id": property_id}
    ).execute()
    return result.data[0] if result.data else None


def set_due_override(property_id: str, override_date: str | None) -> None:
    """`override_date=None` clears it, reverting to the computed schedule. A one-time
    nudge to the current cycle (migration 046) — cleared automatically by `add_visit()`/
    `add_bundled_visit()` once a real visit supersedes it."""
    get_client().table("site_properties").update(
        {"next_due_override": override_date}
    ).eq("id", property_id).execute()


def add_visit(
    property_id: str, visit_date: str, amount_usd: float | None = None,
    technician: str = "", notes: str = "",
) -> dict:
    payload = {
        "property_id": property_id,
        "visit_date": visit_date,
        "amount_usd": amount_usd,
        "technician": technician,
        "notes": notes,
    }
    result = get_client().table("maintenance_visits").insert(payload).execute()
    set_due_override(property_id, None)
    return result.data[0]


def add_bundled_visit(
    client_id: str, property_ids: list[str], visit_date: str,
    amount_usd: float | None = None, technician: str = "", notes: str = "",
) -> dict:
    """One trip, one charge, covering several properties for the same client — the
    charge lives only on the returned group row (migration 046 decision: splitting it
    per property would fabricate a number that was never actually charged per site).
    Each covered property gets its own `maintenance_visits` row (amount_usd=NULL,
    tagged with the group) so its own schedule still recomputes from `visit_date`, and
    its `next_due_override` (if any) is cleared, same as a normal `add_visit()`."""
    group = get_client().table("maintenance_visit_groups").insert({
        "client_id": client_id, "visit_date": visit_date,
        "amount_usd": amount_usd, "technician": technician, "notes": notes,
    }).execute().data[0]

    for property_id in property_ids:
        get_client().table("maintenance_visits").insert({
            "property_id": property_id, "visit_date": visit_date,
            "amount_usd": None, "technician": technician, "notes": notes,
            "visit_group_id": group["id"],
        }).execute()
        set_due_override(property_id, None)

    return group


def list_visit_groups(client_id: str | None = None) -> list[dict]:
    q = get_client().table("maintenance_visit_groups").select("*")
    if client_id:
        q = q.eq("client_id", client_id)
    result = q.order("visit_date", desc=True).execute()
    return result.data or []


def get_visit_group(visit_group_id: str) -> dict | None:
    """The group plus how many properties it covers — for a property's own visit
    history to show "part of a $X visit covering N properties" instead of its own
    (deliberately NULL) amount."""
    result = get_client().table("maintenance_visit_groups").select("*").eq("id", visit_group_id).execute()
    if not result.data:
        return None
    group = result.data[0]
    covered = (
        get_client().table("maintenance_visits").select("property_id")
        .eq("visit_group_id", visit_group_id).execute()
    ).data or []
    group["property_count"] = len(covered)
    return group


def list_visits(property_id: str) -> list[dict]:
    result = (
        get_client()
        .table("maintenance_visits")
        .select("*")
        .eq("property_id", property_id)
        .order("visit_date", desc=True)
        .execute()
    )
    return result.data or []


def get_credentials(site_id: str, schema_name: str) -> dict | None:
    result = (
        get_client()
        .table("site_credentials")
        .select("*")
        .eq("site_id", site_id)
        .eq("schema_name", schema_name)
        .execute()
    )
    return result.data[0] if result.data else None


def save_credentials(site_id: str, schema_name: str, credentials: str, notes: str = "") -> dict:
    payload = {
        "site_id": site_id, "schema_name": schema_name,
        "credentials": credentials, "notes": notes,
    }
    result = (
        get_client()
        .table("site_credentials")
        .upsert(payload, on_conflict="site_id,schema_name")
        .execute()
    )
    return result.data[0]
