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
        .select("id, name, empresa, phone, email")
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


def upsert_client(
    name: str,
    empresa: str = "",
    phone: str = "",
    email: str = "",
    notes: str = "",
) -> dict:
    """Create or update client by name (case-insensitive match on name)."""
    db = get_client()
    existing = (
        db.table("clients")
        .select("id, name, empresa, phone, email")
        .ilike("name", name.strip())
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        updates: dict = {}
        if empresa and not row.get("empresa"):
            updates["empresa"] = empresa
        if phone and not row.get("phone"):
            updates["phone"] = phone
        if email and not row.get("email"):
            updates["email"] = email
        if updates:
            db.table("clients").update(updates).eq("id", row["id"]).execute()
        return {**row, **updates}

    result = (
        db.table("clients")
        .insert({"name": name.strip(), "empresa": empresa, "phone": phone, "email": email, "notes": notes})
        .execute()
    )
    return result.data[0]


def list_all_clients() -> list[dict]:
    result = (
        get_client()
        .table("clients")
        .select("*")
        .order("name")
        .execute()
    )
    return result.data or []


def update_client(
    client_id: str,
    name: str,
    empresa: str = "",
    phone: str = "",
    email: str = "",
    notes: str = "",
) -> dict:
    """Full field update — used by the Admin Clientes editor (unlike
    upsert_client, this overwrites rather than only filling blanks)."""
    result = (
        get_client()
        .table("clients")
        .update({"name": name.strip(), "empresa": empresa, "phone": phone, "email": email, "notes": notes})
        .eq("id", client_id)
        .execute()
    )
    return result.data[0]


def promote_prospect(prospect_id: str) -> str:
    """Moves a prospect into clients (see promote_prospect_to_client in
    migration 008) and repoints any proposals that referenced them.
    Returns the new client_id."""
    result = get_client().rpc("promote_prospect_to_client", {"p_prospect_id": prospect_id}).execute()
    return result.data
