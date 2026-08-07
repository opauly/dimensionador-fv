from __future__ import annotations
"""CRUD for equipment catalog tables. Phase 7 for admin UI; Phase 2 reads are earlier."""
from database.supabase_client import get_client


def list_panels() -> list[dict]:
    result = (
        get_client()
        .table("panels")
        .select("id, brand, model, wp, voc, vmp, isc, imp, temp_coeff_pmax, width_m, height_m, warranty_product_yr, warranty_power_yr, cost_usd, cost_iva_rate, notes")
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
        .select("id, brand, model, kw, type, vmax, vmin_mppt, vmax_mppt, imax_mppt, mppt_channels, phase, output_v, ac_output_current_a, ac_input_current_max_a, warranty_yr, cost_usd, cost_iva_rate, notes")
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
    result = (
        get_client()
        .table("batteries")
        .select("id, brand, model, chemistry, capacity_kwh, capacity_ah, voltage_v, dod_pct, cycles, warranty_yr, cost_usd, cost_iva_rate, notes")
        .order("brand")
        .execute()
    )
    return result.data or []


def get_battery(battery_id: str) -> dict | None:
    result = (
        get_client()
        .table("batteries")
        .select("*")
        .eq("id", battery_id)
        .single()
        .execute()
    )
    return result.data


def upsert_battery(data: dict) -> dict:
    """Insert or update a battery. Include 'id' to update an existing row."""
    row = {k: v for k, v in data.items() if v is not None and k != "id"}
    if data.get("id"):
        result = get_client().table("batteries").update(row).eq("id", data["id"]).execute()
    else:
        result = get_client().table("batteries").insert(row).execute()
    return result.data[0]


def delete_battery(battery_id: str) -> None:
    get_client().table("batteries").delete().eq("id", battery_id).execute()


def list_charge_controllers() -> list[dict]:
    result = (
        get_client()
        .table("charge_controllers")
        .select("id, brand, model, type, vin_max, vout, imax_in, imax_out, cost_usd, cost_iva_rate, notes")
        .order("brand")
        .execute()
    )
    return result.data or []


def get_charge_controller(charge_controller_id: str) -> dict | None:
    result = (
        get_client()
        .table("charge_controllers")
        .select("*")
        .eq("id", charge_controller_id)
        .single()
        .execute()
    )
    return result.data


def upsert_charge_controller(data: dict) -> dict:
    """Insert or update a charge controller. Include 'id' to update an existing row."""
    row = {k: v for k, v in data.items() if v is not None and k != "id"}
    if data.get("id"):
        result = get_client().table("charge_controllers").update(row).eq("id", data["id"]).execute()
    else:
        result = get_client().table("charge_controllers").insert(row).execute()
    return result.data[0]


def delete_charge_controller(charge_controller_id: str) -> None:
    get_client().table("charge_controllers").delete().eq("id", charge_controller_id).execute()


def list_monitoring_devices() -> list[dict]:
    result = (
        get_client()
        .table("monitoring_devices")
        .select("id, brand, model, compatible_with, cost_usd, cost_iva_rate, notes")
        .order("brand")
        .execute()
    )
    return result.data or []


def get_monitoring_device(monitoring_id: str) -> dict | None:
    result = (
        get_client()
        .table("monitoring_devices")
        .select("*")
        .eq("id", monitoring_id)
        .single()
        .execute()
    )
    return result.data


def upsert_monitoring_device(data: dict) -> dict:
    """Insert or update a monitoring device. Include 'id' to update an existing row."""
    row = {k: v for k, v in data.items() if v is not None and k != "id"}
    if data.get("id"):
        result = get_client().table("monitoring_devices").update(row).eq("id", data["id"]).execute()
    else:
        result = get_client().table("monitoring_devices").insert(row).execute()
    return result.data[0]


def delete_monitoring_device(monitoring_id: str) -> None:
    get_client().table("monitoring_devices").delete().eq("id", monitoring_id).execute()


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
