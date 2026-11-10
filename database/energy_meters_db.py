"""Energy meters (Victron VM-3P75CT) — rows of monitoring_devices with device_kind = 'meter'.

Kept apart from equipment_db.list_monitoring_devices() so the monitoring selector keeps showing only the
GX gateways, and the Equipos step can offer the meters in their own selector."""
from database.supabase_client import get_client


def list_energy_meters() -> list[dict]:
    result = (
        get_client()
        .table("monitoring_devices")
        .select("id, brand, model, compatible_with, device_kind, rated_current_a, datasheet_path, cost_usd, notes")
        .eq("device_kind", "meter")
        .order("brand")
        .execute()
    )
    return result.data or []
