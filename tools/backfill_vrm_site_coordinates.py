"""One-off: backfill latitude/longitude for the vrm.sites rows that lost
theirs during the 2026-09-02 monitoring/vrm duplicate-site consolidation
(tools/consolidate_monitoring_duplicates.py).

Root cause (confirmed 2026-09-03, live query): that consolidation's "first
5" batch (Roberto Villalobos, Karen Montealegre bare + Guarda, Rebeca Ruiz
Casona + Cabaña) did "simple client_id copy + monitoring row removal" per
its own docstring -- unlike the later 4-site batch actually in that file,
which explicitly copies latitude/longitude. Of those 5, Villalobos/
Karen-bare/Casona already have real coordinates today (filled in some other
way); Karen Guarda and Rebeca Cabaña genuinely never got theirs, and their
source monitoring.sites rows are already deleted -- no backup exists
(tools/backup_monitoring_site_data.py's own SITE_IDS only ever covered the
Lori Pickett sites, never these).

Two different sources of truth, both real, neither guessed:
  1. Vista Atenas M1/M2 (vrm.sites) -- monitoring.sites.vista-atenas-lp-m1/m2
     STILL EXIST (explicitly excluded from that consolidation, "never touch
     those") with real geocoded coordinates, identical to what
     vrm.sites.vista-atenas-2-floor-pool (the M3 equivalent) already has --
     confirming this is one physical property, geocoded once. Copied
     directly from the live monitoring.sites rows, not hardcoded here.
  2. Karen Guarda / Rebeca Cabaña -- no source row survives. Same-property
     inference instead: Karen Guarda is a guard house on the same premises
     as karen-montealegre-proyecto-km-ukiyo (which already has real
     coordinates); Rebeca Cabaña is on the same "El Encino" property as
     casona/apartamento/casita, which already share ONE identical
     lat/lon pair between themselves -- the established pattern for this
     property (canton-centroid geocoding, one point per property, not
     per-building, per REQUIREMENTS.md's own geocode_cr() caveat). These
     two values ARE hardcoded below, sourced from their real sibling sites
     at run time, not fabricated independently.

Explicitly NOT covered here, on purpose:
  - jorge-ramirez-proyecto-jr -- no monitoring.sites row ever existed for
    this site (not part of migration 011's import), no location/city field
    on vrm.sites to geocode from, and no client/project/proposal row in
    `public` either (checked live -- Jorge Ramírez is a hardcoded reference
    example in proposals/generator.py, not a real DB row). Needs a real
    address from Oscar before this can be filled in responsibly.
  - test-portal-qa-proyecto-gv -- a QA fixture, not a real site. Coordinates
    would be fabricated with no physical meaning; recommend excluding it
    from anomaly detection scope entirely rather than geocoding it.

Idempotent: only writes a row whose latitude/longitude are currently NULL.

Usage:
    python -m tools.backfill_vrm_site_coordinates
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()
    vrm_sites = c.schema("vrm").table("sites")

    print("1. Vista Atenas M1/M2 -- copying from the live monitoring.sites rows...")
    mon = (c.schema("monitoring").table("sites")
          .select("site_id,latitude,longitude")
          .in_("site_id", ["vista-atenas-lp-m1", "vista-atenas-lp-m2"])
          .execute().data)
    mon_by_id = {r["site_id"]: r for r in mon}
    vista_pairs = [
        ("vista-atenas-lp-m1", "vista-atenas-vista-atenas-lp-m1-houses"),
        ("vista-atenas-lp-m2", "vista-atenas-vista-atenas-lp-m2-studios"),
    ]
    for mon_id, vrm_id in vista_pairs:
        src = mon_by_id.get(mon_id)
        assert src and src.get("latitude") is not None, f"expected real coordinates on monitoring.sites.{mon_id}"
        current = vrm_sites.select("latitude,longitude").eq("site_id", vrm_id).execute().data
        assert current, f"vrm.sites.{vrm_id} not found"
        if current[0]["latitude"] is not None:
            print(f"   {vrm_id}: already has coordinates, skipping")
            continue
        vrm_sites.update({"latitude": src["latitude"], "longitude": src["longitude"]}).eq("site_id", vrm_id).execute()
        print(f"   {vrm_id}: set to ({src['latitude']}, {src['longitude']}) from monitoring.sites.{mon_id}")

    print("\n2. Karen Guarda / Rebeca Cabaña -- same-property inference from a real sibling site...")
    sibling_pairs = [
        ("karen-montealegre-proyecto-km-ukiyo", "karen-montealegre-proyecto-km-ukiyo-guarda"),
        ("rebeca-ruiz-el-encino-casona", "rebeca-ruiz-el-encino-cabana"),
    ]
    for sibling_id, target_id in sibling_pairs:
        sibling = vrm_sites.select("latitude,longitude").eq("site_id", sibling_id).execute().data
        assert sibling and sibling[0].get("latitude") is not None, f"expected real coordinates on vrm.sites.{sibling_id}"
        lat, lon = sibling[0]["latitude"], sibling[0]["longitude"]
        current = vrm_sites.select("latitude,longitude").eq("site_id", target_id).execute().data
        assert current, f"vrm.sites.{target_id} not found"
        if current[0]["latitude"] is not None:
            print(f"   {target_id}: already has coordinates, skipping")
            continue
        vrm_sites.update({"latitude": lat, "longitude": lon}).eq("site_id", target_id).execute()
        print(f"   {target_id}: set to ({lat}, {lon}), same property as {sibling_id}")

    print("\n3. Confirming final coverage across all 13 real source='vrm_api' sites...")
    rows = vrm_sites.select("site_id,latitude,longitude").eq("source", "vrm_api").execute().data
    missing = [r["site_id"] for r in rows if r.get("latitude") is None]
    print(f"   {len(rows) - len(missing)}/{len(rows)} now have coordinates.")
    if missing:
        print(f"   Still missing (expected -- see this script's own docstring): {missing}")

    print("\nDone.")


if __name__ == "__main__":
    main()
