from __future__ import annotations
"""CRUD for equipment catalog tables. Phase 7 for admin UI; Phase 2 reads are earlier."""
from database.supabase_client import get_client


def list_panels() -> list[dict]:
    result = (
        get_client()
        .table("panels")
        .select("id, brand, model, wp, voc, vmp, isc, imp, temp_coeff_pmax, width_m, height_m, warranty_product_yr, warranty_power_yr, cost_usd, notes")
        .order("brand")
        .execute()
    )
    return result.data or []


def get_panel(panel_id: str) -> dict | None:
    result = (
        get_client()
        .table("panels")
        .select("*")
        .eq("id", panel_id)
        .single()
        .execute()
    )
    return result.data


def upsert_panel(data: dict) -> dict:
    """Insert or update a panel. Include 'id' to update an existing row."""
    row = {k: v for k, v in data.items() if v is not None and k != "id"}
    if data.get("id"):
        result = get_client().table("panels").update(row).eq("id", data["id"]).execute()
    else:
        result = get_client().table("panels").insert(row).execute()
    return result.data[0]


def delete_panel(panel_id: str) -> None:
    get_client().table("panels").delete().eq("id", panel_id).execute()


def list_inverters() -> list[dict]:
    result = (
        get_client()
        .table("inverters")
        .select("id, brand, model, kw, type, vmax, vmin_mppt, vmax_mppt, imax_mppt, mppt_channels, phase, output_v, warranty_yr, cost_usd, notes")
        .order("brand")
        .execute()
    )
    return result.data or []


def get_inverter(inverter_id: str) -> dict | None:
    result = (
        get_client()
        .table("inverters")
        .select("*")
        .eq("id", inverter_id)
        .single()
        .execute()
    )
    return result.data


def upsert_inverter(data: dict) -> dict:
    """Insert or update an inverter. Include 'id' to update an existing row."""
    row = {k: v for k, v in data.items() if v is not None and k != "id"}
    if data.get("id"):
        result = get_client().table("inverters").update(row).eq("id", data["id"]).execute()
    else:
        result = get_client().table("inverters").insert(row).execute()
    return result.data[0]


def delete_inverter(inverter_id: str) -> None:
    get_client().table("inverters").delete().eq("id", inverter_id).execute()


def list_batteries() -> list[dict]:
    raise NotImplementedError("Phase 5")


def upsert_battery(data: dict) -> dict:
    raise NotImplementedError("Phase 7")


def list_charge_controllers() -> list[dict]:
    raise NotImplementedError("Phase 5")


def upsert_charge_controller(data: dict) -> dict:
    raise NotImplementedError("Phase 7")


def list_monitoring_devices() -> list[dict]:
    result = (
        get_client()
        .table("monitoring_devices")
        .select("id, brand, model, compatible_with, cost_usd")
        .order("brand")
        .execute()
    )
    return result.data or []


# ── Service defaults ──────────────────────────────────────────────────────────

def list_service_defaults() -> list[dict]:
    result = (
        get_client()
        .table("service_defaults")
        .select("id, item, item_en, unit_cost_usd, iva_pct, specs, specs_en, enabled, sort_order")
        .order("sort_order")
        .execute()
    )
    return result.data or []


def upsert_service_default(data: dict) -> dict:
    """Insert or update a service default. Include 'id' to update an existing row."""
    row = {k: v for k, v in data.items() if k != "id" and v is not None}
    if data.get("id"):
        result = get_client().table("service_defaults").update(row).eq("id", data["id"]).execute()
    else:
        result = get_client().table("service_defaults").insert(row).execute()
    return result.data[0]


def delete_service_default(service_id: str) -> None:
    get_client().table("service_defaults").delete().eq("id", service_id).execute()
