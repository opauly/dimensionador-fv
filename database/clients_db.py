from __future__ import annotations
"""CRUD for clients table. Phase 2."""
from database.supabase_client import get_client


def search_clients(query: str, limit: int = 8) -> list[dict]:
    """Case-insensitive substring search by name."""
    if not query or len(query) < 2:
        return []
    result = (
        get_client()
        .table("clients")
        .select("id, name, phone, email")
        .ilike("name", f"%{query}%")
        .limit(limit)
        .execute()
    )
    return result.data or []


def get_client_by_id(client_id: str) -> dict | None:
    result = (
        get_client()
        .table("clients")
        .select("*")
        .eq("id", client_id)
        .single()
        .execute()
    )
    return result.data


def upsert_client(name: str, phone: str = "", email: str = "", notes: str = "") -> dict:
    """Create or update client by name (case-insensitive match on name)."""
    db = get_client()
    existing = (
        db.table("clients")
        .select("id, name, phone, email")
        .ilike("name", name.strip())
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        updates: dict = {}
        if phone and not row.get("phone"):
            updates["phone"] = phone
        if email and not row.get("email"):
            updates["email"] = email
        if updates:
            db.table("clients").update(updates).eq("id", row["id"]).execute()
        return {**row, **updates}

    result = (
        db.table("clients")
        .insert({"name": name.strip(), "phone": phone, "email": email, "notes": notes})
        .execute()
    )
    return result.data[0]
