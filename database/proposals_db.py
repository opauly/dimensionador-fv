from __future__ import annotations
"""CRUD for proposals and proposal_versions. Phase 2."""
from database.supabase_client import get_client


def create_proposal(client_name: str, system_type: str, client_id: str | None = None) -> dict:
    raise NotImplementedError("Phase 2")


def get_proposal(proposal_id: str) -> dict | None:
    raise NotImplementedError("Phase 2")


def list_proposals(status: str | None = None) -> list[dict]:
    raise NotImplementedError("Phase 2")


def update_proposal_status(proposal_id: str, status: str) -> dict:
    raise NotImplementedError("Phase 2")


def create_version(proposal_id: str, data: dict, version_note: str = "") -> dict:
    raise NotImplementedError("Phase 2")


def get_version(version_id: str) -> dict | None:
    raise NotImplementedError("Phase 2")


def upsert_version(version_id: str, data: dict, total_usd: float | None = None) -> dict:
    raise NotImplementedError("Phase 2")


def lock_version(version_id: str) -> dict:
    raise NotImplementedError("Phase 3")


def list_versions(proposal_id: str) -> list[dict]:
    raise NotImplementedError("Phase 2")


def mark_version_sent(version_id: str) -> dict:
    raise NotImplementedError("Phase 3")


def save_pdf_path(version_id: str, pdf_path: str) -> None:
    raise NotImplementedError("Phase 2")
