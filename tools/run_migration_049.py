"""
Migration 049 helper — single-margin profit distribution catalog changes.

Does NOT apply the migration: paste
  database/migrations/049_cost_distribution_markup.sql
into
  Project -> SQL Editor -> New query -> Run
(after editing the placeholder $300 Diseño cost to your actual number, if you want a
different starting value).

This script only verifies the result against the live service_defaults table.

Usage:
    python -m tools.run_migration_049
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402


def main() -> None:
    c = get_client()
    rows = c.table("service_defaults").select("*").execute().data
    by_item = {r["item"]: r for r in rows}

    print("1. markup_eligible present on every row...")
    for r in rows:
        assert "markup_eligible" in r, f"missing markup_eligible on {r['item']!r}"
    print(f"   {len(rows)} rows checked")

    print("\n2. Permiso de Interconexión is the only pass-through row...")
    permiso = by_item.get("Permiso de Interconexión")
    assert permiso is not None, "Permiso de Interconexión row not found"
    assert permiso["markup_eligible"] is False, f"expected markup_eligible=False, got {permiso['markup_eligible']!r}"
    for item, r in by_item.items():
        if item != "Permiso de Interconexión":
            assert r["markup_eligible"] is True, f"expected markup_eligible=True for {item!r}, got {r['markup_eligible']!r}"
    print("   confirmed: Permiso de Interconexión markup_eligible=False, every other row True")

    print("\n3. Diseño Eléctrico y Administración has a nonzero starting cost...")
    diseno = by_item.get("Diseño Eléctrico y Administración")
    assert diseno is not None, "Diseño Eléctrico y Administración row not found"
    assert float(diseno["unit_cost_usd"] or 0) > 0, "expected a nonzero unit_cost_usd"
    print(f"   unit_cost_usd = {diseno['unit_cost_usd']}")

    print("\n4. Estructura de montaje exists and applies to every system type...")
    estructura = by_item.get("Estructura de montaje")
    assert estructura is not None, "Estructura de montaje row not found"
    assert estructura.get("system_types") is None, f"expected system_types=NULL (applies everywhere), got {estructura.get('system_types')!r}"
    assert estructura["markup_eligible"] is True
    print(f"   system_types = {estructura.get('system_types')!r} (applies to all), markup_eligible = True")

    print("\nMigration 049 verified.")


if __name__ == "__main__":
    main()
