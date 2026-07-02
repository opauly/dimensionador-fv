"""CRUD for equipment catalog tables. Phase 7 for admin UI; Phase 2 reads are earlier."""
from database.supabase_client import get_client


def list_panels() -> list[dict]:
    raise NotImplementedError("Phase 2")


def get_panel(panel_id: str) -> dict | None:
    raise NotImplementedError("Phase 2")


def upsert_panel(data: dict) -> dict:
    raise NotImplementedError("Phase 7")


def delete_panel(panel_id: str) -> None:
    raise NotImplementedError("Phase 7")


def list_inverters() -> list[dict]:
    raise NotImplementedError("Phase 2")


def get_inverter(inverter_id: str) -> dict | None:
    raise NotImplementedError("Phase 2")


def upsert_inverter(data: dict) -> dict:
    raise NotImplementedError("Phase 7")


def list_batteries() -> list[dict]:
    raise NotImplementedError("Phase 5")


def upsert_battery(data: dict) -> dict:
    raise NotImplementedError("Phase 7")


def list_charge_controllers() -> list[dict]:
    raise NotImplementedError("Phase 5")


def upsert_charge_controller(data: dict) -> dict:
    raise NotImplementedError("Phase 7")


def list_monitoring_devices() -> list[dict]:
    raise NotImplementedError("Phase 2")
