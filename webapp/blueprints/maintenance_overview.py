from __future__ import annotations
"""Resumen tab — port of pages/07_maintenance.py:_overview_section() /
_kpi_strip() / _render_overview_row() (Phase 21 Step 1).

Reads only from maintenance_common.property_rows() and sorted_rows() per
§1.3 — this module adds display-only fields (badge colors, the due-date
label string) on top of that shared computation; it does not recompute any
status/date/visited-flag itself.
"""
from flask import render_template

from webapp.blueprints.maintenance_common import STATUS_BADGE, property_rows, sorted_rows


def _due_label(r: dict) -> str:
    """Port of _render_overview_row()'s due_label logic verbatim: days-overdue
    text when overdue, otherwise the date, plus the " (movida)" suffix when
    next_due_override is set."""
    if r["status"] == "overdue" and r.get("days_overdue") is not None:
        return f"{r['days_overdue']} días de atraso"
    if r.get("next_due_date"):
        label = str(r["next_due_date"])
        if r.get("next_due_override"):
            label += " (movida)"
        return label
    return "—"


def _row_ctx(r: dict) -> dict:
    badge_label, badge_bg, badge_fg = STATUS_BADGE.get(r["status"], STATUS_BADGE["unknown"])
    return {
        "id": r["id"],
        "name": r["name"],
        "location": r.get("location") or "",
        "badge_label": badge_label,
        "badge_bg": badge_bg,
        "badge_fg": badge_fg,
        "due_label": _due_label(r),
        "site_count": r["site_count"],
        "visited_this_year": r["visited_this_year"],
    }


def render_overview_panel() -> str:
    try:
        rows = sorted_rows(property_rows())
        error = None
    except Exception as exc:
        rows, error = [], str(exc)

    if error is not None:
        return render_template("admin/_error.html", message=error)

    counts = {"overdue": 0, "due_soon": 0, "up_to_date": 0, "unknown": 0}
    for r in rows:
        counts[r["status"]] += 1

    kpis = [
        ("Total", len(rows), "#1E2D54"),
        ("Atrasadas", counts["overdue"], "#dc2626"),
        ("Próximas", counts["due_soon"], "#a16207"),
        ("Al día", counts["up_to_date"], "#16a34a"),
    ]

    return render_template(
        "maintenance/_overview.html",
        rows=[_row_ctx(r) for r in rows],
        kpis=kpis,
    )
