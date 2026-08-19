from __future__ import annotations
"""CRUD for projects and all financial sub-tables. Phase 6.

Shape mirrors ``proposals_db.py``: no ORM, direct
``.table(x).insert/select/update/delete().execute()`` calls against the
``get_client()`` singleton.

**Generated columns.** ``project_expenses.total_with_iva``,
``project_invoice_items.iva_amount``/``total_usd`` and
``project_extras.total_with_iva`` are all Postgres ``GENERATED ALWAYS AS
... STORED`` columns — including them in an insert/update payload makes
Postgres reject the *whole* statement. Every write function in this module
routes its payload through ``_clean()``, which strips them via
``_GENERATED_BY_TABLE``. Do not bypass this when adding new write paths.

**Mano de obra (§1.6 of PLAN_PHASE6.md).** ``project_labor.total_advanced``
is the *only* place worker cash is recorded — ``add_advance()`` is the sole
writer, and there is no expense-entry form for the ``mano_de_obra`` category
in the planned UI. If a future change adds a second way to write advances or
a bulk-edit path over ``project_labor.advances``, it MUST recompute
``total_advanced`` the same way (``round(sum(a["amount"] for a in advances), 2)``)
or the Presupuesto "Mano de obra — actual" figure will double count.
"""
from datetime import datetime, timezone

from database.supabase_client import get_client

# ── Generated columns, per table — never write these ───────────────────────
_GENERATED_BY_TABLE: dict[str, set[str]] = {
    "project_expenses": {"total_with_iva"},
    "project_invoice_items": {"iva_amount", "total_usd"},
    "project_extras": {"total_with_iva"},
}

# Keyword → budget category map, PLAN_PHASE6.md §1.7. Applied case-insensitively,
# accent-insensitive, substring match against the line item's `item` text.
_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("panel", "equipo"),
    ("inversor", "equipo"),
    ("bateria", "equipo"),
    ("controlador", "equipo"),
    ("monitoreo", "equipo"),
    ("cargador", "equipo"),
    ("estructura", "materiales"),
    ("material", "materiales"),
    ("cable", "materiales"),
    ("proteccion", "materiales"),
    ("tuberia", "materiales"),
    ("canaliza", "materiales"),
    ("mano de obra", "mano_de_obra"),
    ("instalacion", "mano_de_obra"),
    ("montaje", "mano_de_obra"),
    ("transporte", "viaticos"),
    ("viatico", "viaticos"),
    ("hospedaje", "viaticos"),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(table: str, payload: dict) -> dict:
    """Strip generated columns for `table` out of `payload` before a write."""
    generated = _GENERATED_BY_TABLE.get(table, set())
    return {k: v for k, v in payload.items() if k not in generated}


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def categorize_line_item(item_text: str) -> str:
    """Map a proposal line item's description to an EXPENSE_CATEGORIES value,
    per PLAN_PHASE6.md §1.7. Falls back to 'extras' when nothing matches."""
    norm = _strip_accents((item_text or "").lower())
    for keyword, category in _CATEGORY_KEYWORDS:
        if _strip_accents(keyword) in norm:
            return category
    return "extras"


def _line_item_total(item: dict) -> float:
    """Return a line item's total, falling back to qty * unit_cost when
    `total` is absent (very old proposal rows) — mirrors the wizard's
    `_row_subtotal()`, where qty=None means 1."""
    if item.get("total") is not None:
        return float(item["total"])
    qty = item.get("qty")
    qty = 1.0 if qty is None else float(qty)
    return qty * float(item.get("unit_cost") or 0)


def derive_contract_terms(version: dict) -> dict:
    """Pure derivation of contract_usd / contract_iva_rate / contract_iva_usd
    from a proposal version. Used both by `promote_to_project` (write path)
    and as a read-only preview for the promotion form.

    Revised 2026-08-17 (superseding the original PLAN_PHASE6.md §1.5): IVA in
    this app is per line item (equipment commonly 0%/exempt, labor/materials/
    services commonly 13% — see `costs["line_items"][].iva_pct`), not a
    single rate on the whole contract. A "blended rate" derivation
    (iva_usd / subtotal_usd) was tried first and technically reconciled, but
    it invents a number ("8.10% IVA") that means nothing on a real invoice —
    the per-item rates are what actually matter for invoicing, and that's
    exactly what Facturación (project_invoice_items, Step 7) exists to
    carry. At the contract-summary level there's nothing to decompose:
    `contract_usd` is simply the real quoted total (already correctly
    summing every item plus whatever tax applies to it), and
    `contract_iva_rate` stays 0 — there's no additional tax to layer on top
    of a total that already includes it.

    `contract_iva_usd` (migration 022, PLAN_PHASE6.md §1.2/§1.5) is the real
    dollar amount of IVA already embedded in `contract_usd` — needed so
    `calculations/project_finance.py`'s utilidad_bruta can strip it back out
    and compare like with like against `project_expenses.amount_usd` (ex-IVA).
    Unlike the blended rate, this is a genuinely meaningful figure (it's the
    IVA total on the quote's own cost breakdown), not an invented percentage."""
    data = version.get("data") or {}
    costs = data.get("costs") or {}
    contract_usd = float(costs.get("total_usd") or version.get("total_usd") or 0)
    contract_iva_usd = float(costs.get("iva_usd") or 0)
    return {
        "contract_usd": contract_usd,
        "contract_iva_rate": 0.0,
        "contract_iva_usd": contract_iva_usd,
    }


def derive_budget_rows(version: dict) -> list[dict]:
    """Pure derivation of the seeded project_expenses budget rows from a
    proposal version's cost line items, per PLAN_PHASE6.md §1.7."""
    data = version.get("data") or {}
    costs = data.get("costs") or {}
    line_items = costs.get("line_items") or []
    rows = []
    for li in line_items:
        item_text = li.get("item") or li.get("item_en") or ""
        rows.append({
            "description": item_text,
            "category": categorize_line_item(item_text),
            "budgeted_usd": round(_line_item_total(li), 2),
        })
    return rows


_SCHEDULE_PRESETS: dict[str, list[float]] = {
    "70/30": [0.7, 0.3],
    "50/40/10": [0.5, 0.4, 0.1],
}


def payment_schedule_for_preset(total_with_iva: float, preset: str = "70/30") -> list[dict]:
    """Split `total_with_iva` per the named preset (PLAN_PHASE6.md §5 open
    question 3: 70/30 default, 50/40/10 also offered). The last installment
    absorbs rounding so the sum always matches `total_with_iva` exactly."""
    fractions = _SCHEDULE_PRESETS.get(preset, _SCHEDULE_PRESETS["70/30"])
    amounts = [round(total_with_iva * f, 2) for f in fractions[:-1]]
    amounts.append(round(total_with_iva - sum(amounts), 2))
    return [{"payment_number": i + 1, "amount_usd": amt} for i, amt in enumerate(amounts)]


def default_payment_schedule(total_with_iva: float) -> list[dict]:
    """70/30 split of the contract total (IVA-inclusive) — the default used
    when `promote_to_project()` is called without an explicit schedule."""
    return payment_schedule_for_preset(total_with_iva, "70/30")


def promote_to_project(
    proposal_id: str,
    version_id: str,
    contract_usd: float,
    contract_iva_rate: float | None = None,
    contract_iva_usd: float | None = None,
    budget_rows: list[dict] | None = None,
    payment_schedule: list[dict] | None = None,
    dry_run: bool = False,
) -> dict:
    """Promote a won proposal to a project.

    `contract_usd` is required (the plan's exact signature) — pass the
    value derived via `derive_contract_terms()` (edited or not) to keep the
    bare 3-arg call working. `contract_usd` is the FULL quoted total
    (already includes each item's own IVA where it applies — §1.5,
    2026-08-17 revision) — it is what the payment schedule is split from
    directly, with no `* (1 + rate)` multiplication. `contract_iva_rate`
    stays at 0 (vestigial — kept for schema/manual-project compatibility,
    never used in this function's own math). `contract_iva_usd` defaults to
    the derived value when omitted — the real dollar amount of IVA already
    embedded in `contract_usd`, used downstream by
    `calculations/project_finance.py` to compute ex-IVA profit correctly
    (migration 022, PLAN_PHASE6.md §1.2).

    `dry_run=True` computes and returns everything (project fields, budget
    rows, payment schedule) WITHOUT writing anything — used by the
    promotion form to preview values before the engineer confirms. This is
    the single place the §1.5/§1.7 derivation logic lives; the UI must not
    duplicate it.
    """
    from database.proposals_db import get_proposal, get_version

    proposal = get_proposal(proposal_id)
    if not proposal:
        raise ValueError(f"Propuesta {proposal_id} no encontrada.")
    version = get_version(version_id)
    if not version:
        raise ValueError(f"Versión {version_id} no encontrada.")

    derived = derive_contract_terms(version)
    resolved_iva_rate = (
        derived["contract_iva_rate"] if contract_iva_rate is None else float(contract_iva_rate)
    )
    resolved_iva_usd = (
        derived["contract_iva_usd"] if contract_iva_usd is None else float(contract_iva_usd)
    )
    resolved_contract_usd = float(contract_usd)

    if budget_rows is None:
        budget_rows = derive_budget_rows(version)

    if payment_schedule is None:
        payment_schedule = default_payment_schedule(round(resolved_contract_usd, 2))

    if dry_run:
        return {
            "client_name": proposal.get("client_name"),
            "system_type": proposal.get("system_type"),
            "contract_usd": resolved_contract_usd,
            "contract_iva_rate": resolved_iva_rate,
            "contract_iva_usd": resolved_iva_usd,
            "budget_rows": budget_rows,
            "payment_schedule": payment_schedule,
        }

    db = get_client()

    existing = (
        db.table("projects")
        .select("id")
        .eq("proposal_id", proposal_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        raise ValueError(
            "Esta propuesta ya fue movida a un proyecto. Solo se puede promover una vez."
        )

    project_payload = _clean("projects", {
        "proposal_id": proposal_id,
        "version_id": version_id,
        "client_name": proposal.get("client_name"),
        "system_type": proposal.get("system_type"),
        "status": "active",
        "contract_usd": round(resolved_contract_usd, 2),
        "contract_iva_rate": resolved_iva_rate,
        "contract_iva_usd": round(resolved_iva_usd, 2),
    })
    project = db.table("projects").insert(project_payload).execute().data[0]
    project_id = project["id"]

    if budget_rows:
        expense_payloads = [
            _clean("project_expenses", {
                "project_id": project_id,
                "category": row["category"],
                "description": row["description"],
                "amount_usd": 0,
                "iva_rate": 0,
                "paid": False,
                "budgeted_usd": row.get("budgeted_usd"),
            })
            for row in budget_rows
        ]
        db.table("project_expenses").insert(expense_payloads).execute()

    if payment_schedule:
        payment_payloads = [
            _clean("project_payments", {
                "project_id": project_id,
                "payment_number": row["payment_number"],
                "amount_usd": row["amount_usd"],
                "paid": False,
            })
            for row in payment_schedule
        ]
        db.table("project_payments").insert(payment_payloads).execute()

    return project


def create_project_manual(
    client_name: str,
    system_type: str,
    contract_usd: float,
    contract_iva_rate: float = 0.0,
    contract_iva_usd: float = 0.0,
    client_id: str | None = None,
    notes: str | None = None,
) -> dict:
    """Create a bare project with no proposal behind it (PLAN_PHASE6.md §6).

    No seeded expense/payment rows — there is no proposal cost blob to
    derive them from. `client_id` is accepted for symmetry with the UI's
    typeahead but is not stored on `projects` (no FK there by design —
    see §3 non-goals; `client_name` is the denormalized display value).

    `contract_usd` is the full contract total (same convention as
    `promote_to_project` — §1.5); `contract_iva_usd` is the dollar amount of
    IVA already included in it, if any (defaults to 0, the common case for
    an untaxed or single-item manual project). `contract_iva_rate` stays
    vestigial, kept only for schema compatibility — never used in the
    profit math (see `calculations/project_finance.py`, §1.2)."""
    payload = _clean("projects", {
        "proposal_id": None,
        "version_id": None,
        "client_name": client_name,
        "system_type": system_type,
        "status": "active",
        "contract_usd": round(float(contract_usd), 2),
        "contract_iva_rate": float(contract_iva_rate),
        "contract_iva_usd": round(float(contract_iva_usd), 2),
        "notes": notes,
    })
    result = get_client().table("projects").insert(payload).execute()
    return result.data[0]


def get_project(project_id: str) -> dict | None:
    result = (
        get_client()
        .table("projects")
        .select("*")
        .eq("id", project_id)
        .single()
        .execute()
    )
    return result.data


def get_project_by_proposal(proposal_id: str) -> dict | None:
    """Return the project promoted from `proposal_id`, or None."""
    result = (
        get_client()
        .table("projects")
        .select("*")
        .eq("proposal_id", proposal_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def list_projects(status: str | None = None) -> list[dict]:
    db = get_client()
    q = db.table("projects").select("*")
    if status:
        q = q.eq("status", status)
    result = q.order("created_at", desc=True).execute()
    return result.data or []


def update_project_status(project_id: str, status: str) -> dict:
    result = (
        get_client()
        .table("projects")
        .update({"status": status})
        .eq("id", project_id)
        .execute()
    )
    return result.data[0]


def update_project(project_id: str, **fields) -> dict:
    payload = _clean("projects", fields)
    result = (
        get_client()
        .table("projects")
        .update(payload)
        .eq("id", project_id)
        .execute()
    )
    return result.data[0]


def get_project_bundle(project_id: str) -> dict:
    """One call per detail-page render — fetches the project plus every
    ledger table in one shot."""
    return {
        "project": get_project(project_id),
        "payments": list_payments(project_id),
        "expenses": list_expenses(project_id),
        "labor": list_labor(project_id),
        "invoice_items": list_invoice_items(project_id),
        "extras": list_extras(project_id),
    }


# ── Payments ─────────────────────────────────────────────────────────────

def add_payment(project_id: str, payment_number: int, amount_usd: float, **kwargs) -> dict:
    payload = _clean("project_payments", {
        "project_id": project_id,
        "payment_number": payment_number,
        "amount_usd": amount_usd,
        "paid": False,
        **kwargs,
    })
    result = get_client().table("project_payments").insert(payload).execute()
    return result.data[0]


def mark_payment_paid(payment_id: str, paid_date: str, bank_account: str) -> dict:
    payload = _clean("project_payments", {
        "paid": True,
        "paid_date": paid_date,
        "bank_account": bank_account,
    })
    result = (
        get_client()
        .table("project_payments")
        .update(payload)
        .eq("id", payment_id)
        .execute()
    )
    return result.data[0]


def update_payment(payment_id: str, **fields) -> dict:
    payload = _clean("project_payments", fields)
    result = (
        get_client()
        .table("project_payments")
        .update(payload)
        .eq("id", payment_id)
        .execute()
    )
    return result.data[0]


def delete_payment(payment_id: str) -> None:
    get_client().table("project_payments").delete().eq("id", payment_id).execute()


def list_payments(project_id: str) -> list[dict]:
    result = (
        get_client()
        .table("project_payments")
        .select("*")
        .eq("project_id", project_id)
        .order("payment_number")
        .execute()
    )
    return result.data or []


# ── Expenses ─────────────────────────────────────────────────────────────

def add_expense(project_id: str, category: str, description: str, amount_usd: float, **kwargs) -> dict:
    payload = _clean("project_expenses", {
        "project_id": project_id,
        "category": category,
        "description": description,
        "amount_usd": amount_usd,
        "iva_rate": kwargs.pop("iva_rate", 0),
        "paid": kwargs.pop("paid", False),
        **kwargs,
    })
    result = get_client().table("project_expenses").insert(payload).execute()
    return result.data[0]


def update_expense(expense_id: str, **fields) -> dict:
    payload = _clean("project_expenses", fields)
    result = (
        get_client()
        .table("project_expenses")
        .update(payload)
        .eq("id", expense_id)
        .execute()
    )
    return result.data[0]


def delete_expense(expense_id: str) -> None:
    get_client().table("project_expenses").delete().eq("id", expense_id).execute()


def list_expenses(project_id: str, category: str | None = None) -> list[dict]:
    db = get_client()
    q = db.table("project_expenses").select("*").eq("project_id", project_id)
    if category:
        q = q.eq("category", category)
    result = q.order("created_at").execute()
    return result.data or []


# ── Labor ────────────────────────────────────────────────────────────────

def add_labor(project_id: str, worker_name: str, quoted_amount: float, role: str = "") -> dict:
    payload = _clean("project_labor", {
        "project_id": project_id,
        "worker_name": worker_name,
        "quoted_amount": quoted_amount,
        "role": role,
        "advances": [],
        "total_advanced": 0,
    })
    result = get_client().table("project_labor").insert(payload).execute()
    return result.data[0]


def add_advance(labor_id: str, amount: float, date: str) -> dict:
    """Append {number, amount, date} to the row's `advances` jsonb array and
    recompute `total_advanced` — the ONLY writer of total_advanced (see the
    module docstring / PLAN_PHASE6.md §1.3)."""
    db = get_client()
    row = db.table("project_labor").select("*").eq("id", labor_id).single().execute().data
    advances = list(row.get("advances") or [])
    advances.append({"number": len(advances) + 1, "amount": round(float(amount), 2), "date": date})
    total_advanced = round(sum(a["amount"] for a in advances), 2)

    payload = _clean("project_labor", {"advances": advances, "total_advanced": total_advanced})
    result = db.table("project_labor").update(payload).eq("id", labor_id).execute()
    return result.data[0]


def delete_advance(labor_id: str, advance_number: int) -> dict:
    """Remove one advance from the row's `advances` jsonb array by its
    `number` and recompute `total_advanced` — same single-writer pattern as
    `add_advance()` (module docstring / PLAN_PHASE6.md §1.3): read the row,
    mutate the array in Python, write `advances` and `total_advanced`
    together in one `.update()` so the two never go out of sync, even
    transiently.

    PLAN_PHASE6.md Step 5 lists advance deletion as optional ("if delete is
    implemented"); this is the implementation, built to the exact pattern
    the plan requires for it.

    Renumbering choice: the remaining advances are renumbered sequentially
    (1..N) rather than left with a gap after the deleted `number` — this
    keeps `number` matching display order, and stays consistent with
    `add_advance()`'s own `len(advances) + 1` numbering for the next
    addition (documented here since the plan left the choice open)."""
    db = get_client()
    row = db.table("project_labor").select("*").eq("id", labor_id).single().execute().data
    advances = [a for a in (row.get("advances") or []) if a.get("number") != advance_number]
    for i, a in enumerate(advances):
        a["number"] = i + 1
    total_advanced = round(sum(float(a["amount"]) for a in advances), 2)

    payload = _clean("project_labor", {"advances": advances, "total_advanced": total_advanced})
    result = db.table("project_labor").update(payload).eq("id", labor_id).execute()
    return result.data[0]


def update_labor(labor_id: str, **fields) -> dict:
    payload = _clean("project_labor", fields)
    result = (
        get_client()
        .table("project_labor")
        .update(payload)
        .eq("id", labor_id)
        .execute()
    )
    return result.data[0]


def delete_labor(labor_id: str) -> None:
    get_client().table("project_labor").delete().eq("id", labor_id).execute()


def list_labor(project_id: str) -> list[dict]:
    result = (
        get_client()
        .table("project_labor")
        .select("*")
        .eq("project_id", project_id)
        .order("created_at")
        .execute()
    )
    return result.data or []


# ── Invoice items (facturación) ─────────────────────────────────────────

def add_invoice_item(project_id: str, description: str, category: str, amount_usd: float, iva_rate: float) -> dict:
    payload = _clean("project_invoice_items", {
        "project_id": project_id,
        "description": description,
        "category": category,
        "amount_usd": amount_usd,
        "iva_rate": iva_rate,
    })
    result = get_client().table("project_invoice_items").insert(payload).execute()
    return result.data[0]


def update_invoice_item(item_id: str, **fields) -> dict:
    payload = _clean("project_invoice_items", fields)
    result = (
        get_client()
        .table("project_invoice_items")
        .update(payload)
        .eq("id", item_id)
        .execute()
    )
    return result.data[0]


def delete_invoice_item(item_id: str) -> None:
    get_client().table("project_invoice_items").delete().eq("id", item_id).execute()


def list_invoice_items(project_id: str) -> list[dict]:
    result = (
        get_client()
        .table("project_invoice_items")
        .select("*")
        .eq("project_id", project_id)
        .order("created_at")
        .execute()
    )
    return result.data or []


# ── Extras (INGRESOS — additional work orders, §1.1) ────────────────────

def add_extra(project_id: str, description: str, amount_usd: float, iva_rate: float = 0.0, **kwargs) -> dict:
    payload = _clean("project_extras", {
        "project_id": project_id,
        "description": description,
        "amount_usd": amount_usd,
        "iva_rate": iva_rate,
        "approved": kwargs.pop("approved", True),
        **kwargs,
    })
    result = get_client().table("project_extras").insert(payload).execute()
    return result.data[0]


def update_extra(extra_id: str, **fields) -> dict:
    payload = _clean("project_extras", fields)
    result = (
        get_client()
        .table("project_extras")
        .update(payload)
        .eq("id", extra_id)
        .execute()
    )
    return result.data[0]


def delete_extra(extra_id: str) -> None:
    get_client().table("project_extras").delete().eq("id", extra_id).execute()


def list_extras(project_id: str) -> list[dict]:
    result = (
        get_client()
        .table("project_extras")
        .select("*")
        .eq("project_id", project_id)
        .order("created_at")
        .execute()
    )
    return result.data or []
