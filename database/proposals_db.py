from __future__ import annotations
"""CRUD for proposals and proposal_versions. Phase 2."""
from datetime import datetime, timezone

from database.supabase_client import get_client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_proposal(client_name: str, system_type: str, client_id: str | None = None) -> dict:
    """Create a proposal row + an initial unlocked version 1. Returns the version row."""
    db = get_client()

    proposal_payload: dict = {
        "client_name": client_name,
        "system_type": system_type,
        "status": "draft",
        "current_version_number": 1,
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


def lock_version(version_id: str) -> dict:
    result = (
        get_client()
        .table("proposal_versions")
        .update({"locked": True, "locked_at": _now()})
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
