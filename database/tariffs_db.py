"""CRUD for tariff tables. Phase 2 reads; Phase 7 admin writes."""
from database.supabase_client import get_client


def list_distributors() -> list[dict]:
    raise NotImplementedError("Phase 2")


def get_tariff_type(distributor_id: str, code: str) -> dict | None:
    raise NotImplementedError("Phase 2")


def list_tariff_types(distributor_id: str) -> list[dict]:
    raise NotImplementedError("Phase 2")


def get_tariff_tiers(tariff_type_id: str) -> list[dict]:
    raise NotImplementedError("Phase 2")


def upsert_tariff_type(data: dict) -> dict:
    raise NotImplementedError("Phase 7")


def replace_tariff_tiers(tariff_type_id: str, tiers: list[dict]) -> None:
    raise NotImplementedError("Phase 7")


def touch_tariff_updated(tariff_type_id: str) -> None:
    raise NotImplementedError("Phase 7")
