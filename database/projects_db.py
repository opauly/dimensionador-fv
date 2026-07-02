from __future__ import annotations
"""CRUD for projects and all financial sub-tables. Phase 6."""
from database.supabase_client import get_client


def promote_to_project(proposal_id: str, version_id: str, contract_usd: float) -> dict:
    raise NotImplementedError("Phase 6")


def get_project(project_id: str) -> dict | None:
    raise NotImplementedError("Phase 6")


def list_projects(status: str | None = None) -> list[dict]:
    raise NotImplementedError("Phase 6")


def update_project_status(project_id: str, status: str) -> dict:
    raise NotImplementedError("Phase 6")


# Payments
def add_payment(project_id: str, payment_number: int, amount_usd: float) -> dict:
    raise NotImplementedError("Phase 6")


def mark_payment_paid(payment_id: str, paid_date: str, bank_account: str) -> dict:
    raise NotImplementedError("Phase 6")


def list_payments(project_id: str) -> list[dict]:
    raise NotImplementedError("Phase 6")


# Expenses
def add_expense(project_id: str, category: str, description: str, amount_usd: float, **kwargs) -> dict:
    raise NotImplementedError("Phase 6")


def list_expenses(project_id: str, category: str | None = None) -> list[dict]:
    raise NotImplementedError("Phase 6")


# Labor
def add_labor(project_id: str, worker_name: str, quoted_amount: float, role: str = "") -> dict:
    raise NotImplementedError("Phase 6")


def add_advance(labor_id: str, amount: float, date: str) -> dict:
    raise NotImplementedError("Phase 6")


def list_labor(project_id: str) -> list[dict]:
    raise NotImplementedError("Phase 6")


# Invoice items
def add_invoice_item(project_id: str, description: str, category: str, amount_usd: float, iva_rate: float) -> dict:
    raise NotImplementedError("Phase 6")


def list_invoice_items(project_id: str) -> list[dict]:
    raise NotImplementedError("Phase 6")
