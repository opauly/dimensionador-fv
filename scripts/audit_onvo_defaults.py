from __future__ import annotations
"""Phase 22 Step 0 — read-only audit of `project_payments.onvo_commission_pct`.

`onvo_commission_pct` has been `NOT NULL DEFAULT 0.024` since migration 020,
and nothing in the codebase has ever written or read it (PLAN_PHASE22 §1.10.3).
That means every row currently asserts a 2.4% ONVO card commission that no one
actually chose. This script never writes anything — it only reports:

  1. Total `project_payments` row count.
  2. How many rows match the untouched-default signature exactly
     (`onvo_commission_pct = 0.024 AND onvo_iva_pct IS NULL AND
     net_deposited IS NULL`) — these are migration 048 half (b)'s blanket
     backfill candidates, and the list a human must review to find any real
     ONVO payments hiding among them.
  3. A full, human-readable dump of every one of those candidate rows
     (project/client, payment number, amount, paid state, date, bank
     account, notes).
  4. A full dump of any row that does NOT match that signature. Per
     PLAN_PHASE22_PROJECTS_JINJA.md §1.10.3 guardrail 1: if even one such row
     exists, the "all 0.024 values are schema defaults" premise is false, and
     migration 048's blanket UPDATE must not run. This script reports that
     and exits nonzero; it does not decide anything on its own.

Usage:
    python -m scripts.audit_onvo_defaults
    (or)  python scripts/audit_onvo_defaults.py
    (or, from the venv)  .venv/bin/python scripts/audit_onvo_defaults.py
"""

import os
import sys

# Allow `python scripts/audit_onvo_defaults.py` (direct run) as well as
# `python -m scripts.audit_onvo_defaults` (module run) — both are documented
# entry points, so make the repo root importable either way.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from database.supabase_client import get_client  # noqa: E402

DEFAULT_COMMISSION_PCT = 0.024


def _is_default_signature(row: dict) -> bool:
    return (
        row.get("onvo_commission_pct") == DEFAULT_COMMISSION_PCT
        and row.get("onvo_iva_pct") is None
        and row.get("net_deposited") is None
    )


def _fmt_usd(v) -> str:
    if v is None:
        return "—"
    return f"${float(v):,.2f}"


def _print_row_table(rows: list[dict], projects_by_id: dict) -> None:
    header = (
        f"{'Proyecto / Cliente':<32} {'Pago #':>6} {'Monto USD':>12} "
        f"{'Pagado':>7} {'Fecha':>11} {'Cuenta bancaria':<20} {'Notas'}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        project = projects_by_id.get(row["project_id"], {})
        client = project.get("client_name") or f"(proyecto {row['project_id']} no encontrado)"
        paid = "sí" if row.get("paid") else "no"
        print(
            f"{client:<32.32} {row.get('payment_number', '—'):>6} "
            f"{_fmt_usd(row.get('amount_usd')):>12} {paid:>7} "
            f"{(row.get('paid_date') or '—'):>11} "
            f"{(row.get('bank_account') or '—'):<20.20} "
            f"{row.get('notes') or '—'}"
        )


def _print_deviating_row(row: dict, projects_by_id: dict) -> None:
    project = projects_by_id.get(row["project_id"], {})
    client = project.get("client_name") or f"(proyecto {row['project_id']} no encontrado)"
    print(f"  id={row['id']}")
    print(f"    project_id             = {row['project_id']} ({client})")
    print(f"    payment_number         = {row.get('payment_number')}")
    print(f"    amount_usd             = {row.get('amount_usd')}")
    print(f"    paid                   = {row.get('paid')}")
    print(f"    paid_date              = {row.get('paid_date')}")
    print(f"    bank_account           = {row.get('bank_account')}")
    print(f"    onvo_commission_pct    = {row.get('onvo_commission_pct')}")
    print(f"    onvo_iva_pct           = {row.get('onvo_iva_pct')}")
    print(f"    net_deposited          = {row.get('net_deposited')}")
    print(f"    notes                  = {row.get('notes')}")
    print()


def run_audit() -> dict:
    """Runs the audit and returns a summary dict. Does not raise on
    deviating rows — the caller decides what to do (main() below stops and
    exits nonzero, per the plan's guardrail)."""
    c = get_client()

    payments = c.table("project_payments").select("*").order("created_at").execute().data or []
    projects = c.table("projects").select("id,client_name,system_type").execute().data or []
    projects_by_id = {p["id"]: p for p in projects}

    default_rows = [r for r in payments if _is_default_signature(r)]
    deviating_rows = [r for r in payments if not _is_default_signature(r)]

    print("=" * 78)
    print("ONVO commission default audit — project_payments")
    print("=" * 78)
    print(f"Total project_payments rows:                {len(payments)}")
    print(f"Rows matching untouched-default signature:  {len(default_rows)}")
    print(f"Rows NOT matching that signature:            {len(deviating_rows)}")
    print()

    if default_rows:
        print("-" * 78)
        print(f"CANDIDATE ROWS (default signature, migration 048 half (b) targets) — "
              f"{len(default_rows)} row(s)")
        print("Review these to identify any that were genuinely paid via ONVO card.")
        print("-" * 78)
        _print_row_table(default_rows, projects_by_id)
        print()
    else:
        print("No rows match the untouched-default signature.\n")

    if deviating_rows:
        print("!" * 78)
        print(f"DEVIATING ROWS — {len(deviating_rows)} row(s) do NOT match the default "
              f"signature.")
        print("These rows already carry a real classification (a different commission")
        print("pct, a non-NULL onvo_iva_pct, or a non-NULL net_deposited). Per")
        print("PLAN_PHASE22 §1.10.3 guardrail 1, this means the \"all 0.024 values are")
        print("schema defaults\" premise is FALSE. STOP — do not write or run the")
        print("migration's blanket UPDATE. Full dump follows.")
        print("!" * 78)
        for row in deviating_rows:
            _print_deviating_row(row, projects_by_id)
    else:
        print("No deviating rows found — every row matches the untouched-default "
              "signature or none exist.")

    return {
        "total": len(payments),
        "default_count": len(default_rows),
        "deviating_count": len(deviating_rows),
        "default_rows": default_rows,
        "deviating_rows": deviating_rows,
    }


def main() -> int:
    summary = run_audit()
    if summary["deviating_count"] > 0:
        print("\nAudit result: STOP — deviating rows found. Do not proceed to migration 048.")
        return 1
    print("\nAudit result: OK — safe to proceed (all rows are either untouched "
          "defaults or there are no rows at all).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
