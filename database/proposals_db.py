from __future__ import annotations
"""CRUD for proposals and proposal_versions. Phase 2+3."""
from datetime import datetime, timezone

from database.supabase_client import get_client

QUOTE_PREFIX = "PC"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_quote_number(year: int) -> int:
    """Return the next sequential quote number for the given year."""
    db = get_client()
    result = (
        db.table("proposals")
        .select("quote_number")
        .gte("created_at", f"{year}-01-01")
        .lt("created_at", f"{year + 1}-01-01")
        .execute()
    )
    existing = [r["quote_number"] for r in (result.data or []) if r.get("quote_number")]
    return (max(existing) + 1) if existing else 1


def format_quote_number(quote_number: int | None, created_at: str, version_number: int = 1) -> str:
    """Format: PC-2026-001 (v1) or PC-2026-001-v2 (v2+). Returns '—' if not yet assigned."""
    if not quote_number:
        return "—"
    year = int((created_at or "2026")[:4])
    base = f"{QUOTE_PREFIX}-{year}-{quote_number:03d}"
    return base if version_number <= 1 else f"{base}-v{version_number}"


def create_proposal(client_name: str, system_type: str, client_id: str | None = None) -> dict:
    """Create a proposal row + an initial unlocked version 1. Returns the version row."""
    db = get_client()

    year = datetime.now(timezone.utc).year
    quote_number = _next_quote_number(year)

    proposal_payload: dict = {
        "client_name": client_name,
        "system_type": system_type,
        "status": "draft",
        "current_version_number": 1,
        "quote_number": quote_number,
    }
    if client_id:
        proposal_payload["client_id"] = client_id

    proposal = db.table("proposals").insert(proposal_payload).execute().data[0]
    proposal_id = proposal["id"]

    version = (
        db.table("proposal_versions")
        .insert({
            "proposal_id": proposal_id,
            "version_number": 1,
            "locked": False,
            "sent_to_client": False,
            "data": {},
        })
        .execute()
        .data[0]
    )

    return {**version, "proposal_id": proposal_id}


def get_proposal(proposal_id: str) -> dict | None:
    result = (
        get_client()
        .table("proposals")
        .select("*")
        .eq("id", proposal_id)
        .single()
        .execute()
    )
    return result.data


def list_proposals(status: str | None = None) -> list[dict]:
    db = get_client()
    q = db.table("proposals").select("*, proposal_versions(version_number, total_usd, locked, created_at)")
    if status:
        q = q.eq("status", status)
    result = q.order("updated_at", desc=True).limit(200).execute()
    return result.data or []


def list_proposals_by_client(client_id: str, client_name: str = "") -> list[dict]:
    """Return proposals for a client by client_id, with client_name fallback."""
    db = get_client()
    _select = "id, quote_number, created_at, system_type, proposal_versions(id, version_number, total_usd, locked, sent_to_client)"

    rows: list[dict] = []
    seen: set[str] = set()

    if client_id:
        r = (
            db.table("proposals")
            .select(_select)
            .eq("client_id", client_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        for p in r.data or []:
            if p["id"] not in seen:
                rows.append(p)
                seen.add(p["id"])

    if client_name:
        r2 = (
            db.table("proposals")
            .select(_select)
            .ilike("client_name", client_name.strip())
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        for p in r2.data or []:
            if p["id"] not in seen:
                rows.append(p)
                seen.add(p["id"])

    return rows


def update_proposal_status(proposal_id: str, status: str) -> dict:
    result = (
        get_client()
        .table("proposals")
        .update({"status": status, "updated_at": _now()})
        .eq("id", proposal_id)
        .execute()
    )
    return result.data[0]


def create_version(proposal_id: str, data: dict, version_note: str = "") -> dict:
    """Create a new version by inheriting data from the latest locked version."""
    db = get_client()

    existing = (
        db.table("proposal_versions")
        .select("version_number")
        .eq("proposal_id", proposal_id)
        .order("version_number", desc=True)
        .limit(1)
        .execute()
    )
    next_num = (existing.data[0]["version_number"] + 1) if existing.data else 1

    version = (
        db.table("proposal_versions")
        .insert({
            "proposal_id": proposal_id,
            "version_number": next_num,
            "locked": False,
            "sent_to_client": False,
            "version_note": version_note,
            "data": data,
        })
        .execute()
        .data[0]
    )

    db.table("proposals").update({
        "current_version_number": next_num,
        "updated_at": _now(),
    }).eq("id", proposal_id).execute()

    return version


def get_version(version_id: str) -> dict | None:
    result = (
        get_client()
        .table("proposal_versions")
        .select("*")
        .eq("id", version_id)
        .single()
        .execute()
    )
    return result.data


def upsert_version(version_id: str, data: dict, total_usd: float | None = None) -> dict:
    """Update the JSONB data blob (and optionally total_usd) for a version."""
    payload: dict = {"data": data}
    if total_usd is not None:
        payload["total_usd"] = total_usd

    db = get_client()
    result = (
        db.table("proposal_versions")
        .update(payload)
        .eq("id", version_id)
        .execute()
    )
    version = result.data[0]

    # Also bump proposal.updated_at
    db.table("proposals").update({"updated_at": _now()}).eq(
        "id", version["proposal_id"]
    ).execute()

    return version


def lock_version(version_id: str, version_note: str | None = None) -> dict:
    payload: dict = {"locked": True, "locked_at": _now()}
    if version_note:
        payload["version_note"] = version_note
    result = (
        get_client()
        .table("proposal_versions")
        .update(payload)
        .eq("id", version_id)
        .execute()
    )
    return result.data[0]


def list_versions(proposal_id: str) -> list[dict]:
    result = (
        get_client()
        .table("proposal_versions")
        .select("id, version_number, created_at, locked_at, locked, sent_to_client, version_note, total_usd, pdf_path")
        .eq("proposal_id", proposal_id)
        .order("version_number")
        .execute()
    )
    return result.data or []


def mark_version_sent(version_id: str) -> dict:
    result = (
        get_client()
        .table("proposal_versions")
        .update({"sent_to_client": True})
        .eq("id", version_id)
        .execute()
    )
    return result.data[0]


def save_pdf_path(version_id: str, pdf_path: str) -> None:
    get_client().table("proposal_versions").update(
        {"pdf_path": pdf_path}
    ).eq("id", version_id).execute()
