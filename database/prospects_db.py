from __future__ import annotations
"""CRUD for prospects table — people who have been quoted but haven't bought.

Promoted to clients (via promote_prospect_to_client, see clients_db.py)
when a proposal referencing them is marked won.
"""
from database.supabase_client import get_client


def create_prospect(
    name: str,
    empresa: str = "",
    phone: str = "",
    email: str = "",
    notes: str = "",
) -> dict:
    result = (
        get_client()
        .table("prospects")
        .insert({"name": name.strip(), "empresa": empresa, "phone": phone, "email": email, "notes": notes})
        .execute()
    )
    return result.data[0]


def list_all_prospects() -> list[dict]:
    result = (
        get_client()
        .table("prospects")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def get_prospect_by_id(prospect_id: str) -> dict | None:
    result = (
        get_client()
        .table("prospects")
        .select("*")
        .eq("id", prospect_id)
        .single()
        .execute()
    )
    return result.data
