from __future__ import annotations
"""CRUD for tariff tables. Phase 2 reads; Phase 7 admin writes."""
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
        .select("id, code, name, sector, access_charge_crc, bomberos_pct, iva_threshold_kwh, last_updated")
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


def upsert_tariff_type(data: dict) -> dict:
    raise NotImplementedError("Phase 7")


def replace_tariff_tiers(tariff_type_id: str, tiers: list[dict]) -> None:
    raise NotImplementedError("Phase 7")


def touch_tariff_updated(tariff_type_id: str) -> None:
    raise NotImplementedError("Phase 7")
