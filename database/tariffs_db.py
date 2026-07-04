from __future__ import annotations
"""CRUD for tariff tables. Phase 2 reads; admin writes."""
from database.supabase_client import get_client


def list_distributors() -> list[dict]:
    result = (
        get_client()
        .table("distributors")
        .select("id, name, abbreviation, coverage_area")
        .order("abbreviation")
        .execute()
    )
    return result.data or []


def get_tariff_type(distributor_id: str, code: str) -> dict | None:
    result = (
        get_client()
        .table("tariff_types")
        .select("*")
        .eq("distributor_id", distributor_id)
        .eq("code", code)
        .single()
        .execute()
    )
    return result.data


def list_tariff_types(distributor_id: str) -> list[dict]:
    result = (
        get_client()
        .table("tariff_types")
        .select("id, code, name, sector, access_charge_crc, bomberos_pct, iva_threshold_kwh, demand_rate_crc, demand_threshold_kw, last_updated")
        .eq("distributor_id", distributor_id)
        .order("code")
        .execute()
    )
    return result.data or []


def get_tariff_tiers(tariff_type_id: str) -> list[dict]:
    result = (
        get_client()
        .table("tariff_tiers")
        .select("id, from_kwh, to_kwh, rate_crc, is_fixed, sort_order")
        .eq("tariff_type_id", tariff_type_id)
        .order("sort_order")
        .execute()
    )
    return result.data or []


def get_tariff_info(distributor_abbrev: str, code: str) -> dict | None:
    """Return tariff_type row + its tiers for a distributor abbreviation and tariff code."""
    db = get_client()
    dist = (
        db.table("distributors")
        .select("id, name, abbreviation")
        .eq("abbreviation", distributor_abbrev)
        .single()
        .execute()
    )
    if not dist.data:
        return None
    tt = (
        db.table("tariff_types")
        .select("id, code, name, sector, access_charge_crc, bomberos_pct, iva_threshold_kwh, demand_rate_crc, demand_threshold_kw, last_updated")
        .eq("distributor_id", dist.data["id"])
        .eq("code", code)
        .single()
        .execute()
    )
    if not tt.data:
        return None
    tiers = get_tariff_tiers(tt.data["id"])
    return {**tt.data, "distributor": dist.data, "tiers": tiers}


def get_tre_info(distributor_abbrev: str) -> dict | None:
    return get_tariff_info(distributor_abbrev, "T-RE")


def upsert_tariff_type_row(
    distributor_abbrev: str,
    code: str,
    name: str,
    sector: str,
    access_charge_crc: float,
    demand_rate_crc: float = 0.0,
    demand_threshold_kw: int = 0,
    bomberos_pct: float = 0.0175,
    iva_threshold_kwh: int = 280,
) -> str:
    """Insert or update a tariff_type row. Returns the tariff_type_id."""
    from datetime import date
    db = get_client()
    dist = (
        db.table("distributors")
        .select("id")
        .eq("abbreviation", distributor_abbrev)
        .single()
        .execute()
    )
    if not dist.data:
        raise ValueError(f"Distributor not found: {distributor_abbrev}")
    dist_id = dist.data["id"]

    existing = (
        db.table("tariff_types")
        .select("id")
        .eq("distributor_id", dist_id)
        .eq("code", code)
        .execute()
    )
    payload = {
        "access_charge_crc": access_charge_crc,
        "demand_rate_crc": demand_rate_crc,
        "demand_threshold_kw": demand_threshold_kw,
        "last_updated": date.today().isoformat(),
    }
    if existing.data:
        tt_id = existing.data[0]["id"]
        db.table("tariff_types").update(payload).eq("id", tt_id).execute()
    else:
        payload.update({
            "distributor_id": dist_id,
            "code": code,
            "name": name,
            "sector": sector,
            "bomberos_pct": bomberos_pct,
            "iva_threshold_kwh": iva_threshold_kwh,
        })
        result = db.table("tariff_types").insert(payload).execute()
        tt_id = result.data[0]["id"]

    return tt_id


def replace_tariff_tiers(tariff_type_id: str, tiers: list[dict]) -> None:
    db = get_client()
    db.table("tariff_tiers").delete().eq("tariff_type_id", tariff_type_id).execute()
    if tiers:
        db.table("tariff_tiers").insert([
            {
                "tariff_type_id": tariff_type_id,
                "from_kwh": t["from_kwh"],
                "to_kwh": t["to_kwh"],
                "rate_crc": t["rate_crc"],
                "is_fixed": t.get("is_fixed", False),
                "sort_order": t["sort_order"],
            }
            for t in tiers
        ]).execute()
