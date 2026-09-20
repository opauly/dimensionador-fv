from __future__ import annotations
"""Shared computation for the Mantenimiento section (Phase 21 — port of
pages/07_maintenance.py onto Flask/Jinja2/htmx).

`property_rows()` is this module's one load-bearing function, and the rule
carried over from `pages/07_maintenance.py:_compute_property_rows()`'s own
docstring is absolute: the Resumen table, the KPI strip, both calendar grids
(current-year and historical), the not-visited banner, the future-cycle
banner and the move-a-property picker all read from `property_rows()` and
nothing else. No route recomputes a status, a next-due date or a
visited-this-year flag from its own locals — a partial handler that mutates
something re-calls `property_rows()` and renders its fragment from that.
See PLAN_PHASE21_MAINTENANCE_JINJA.md §1.3.
"""
from datetime import date

from calculations.maintenance import compute_status, visited_this_calendar_year

MONTH_NAMES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

# Verbatim from pages/07_maintenance.py — labels/colors must match Streamlit
# character for character.
STATUS_BADGE = {
    "overdue":    ("Atrasado",     "#fee2e2", "#dc2626"),
    "due_soon":   ("Próximo",      "#fef9c3", "#a16207"),
    "up_to_date": ("Al día",       "#dcfce7", "#16a34a"),
    "unknown":    ("Sin datos",    "#f1f5f9", "#6b7280"),
}
STATUS_EMOJI = {"overdue": "🔴", "due_soon": "🟡", "up_to_date": "🟢", "unknown": "⚪"}

# Sort order Streamlit's _overview_section() uses: overdue -> due_soon ->
# unknown -> up_to_date, then by name. `unknown` sorts ABOVE up_to_date — a
# property nobody can compute a date for needs attention.
STATUS_ORDER = {"overdue": 0, "due_soon": 1, "unknown": 2, "up_to_date": 3}


def _parse_date(value) -> date | None:
    """Port of pages/07_maintenance.py:_parse_date() verbatim — list_visits()
    and list_properties() return ISO strings from PostgREST, and
    compute_status() needs date objects."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def property_rows() -> list[dict]:
    """Every property's computed status, in one pass. Port of
    pages/07_maintenance.py:_compute_property_rows() — see this module's
    docstring for the "every consumer reads from here" rule.

    Row shape (superset of Streamlit's `{**p, **result, "visited_this_year": ...}`):
      - every `site_properties_db.list_properties()` field: id, name,
        maintenance_interval_days, next_due_override, created_at, client_id,
        location, site_count
      - from `calculations.maintenance.compute_status()`: next_due_date
        (date | None), status ("overdue" | "due_soon" | "up_to_date" |
        "unknown"), days_overdue (int | None — negative when not overdue,
        only render when overdue)
      - visited_this_year (bool, from visited_this_calendar_year()) —
        deliberately distinct from `status`, see that function's docstring
      - visits (this property's list_visits() rows, newest first — kept here,
        NEW vs. Streamlit, so the calendar's historical mode costs zero extra
        queries instead of N; see PLAN §1.5)
    """
    from database.site_properties_db import (
        list_all_sites_for_maintenance, list_properties, list_visits_for_properties,
    )

    properties = list_properties()
    all_sites = list_all_sites_for_maintenance()

    sites_by_property: dict[str, list[dict]] = {}
    for s in all_sites:
        pid = s.get("property_id")
        if pid:
            sites_by_property.setdefault(pid, []).append(s)

    visits_by_property = list_visits_for_properties([p["id"] for p in properties])

    rows = []
    for p in properties:
        visits = visits_by_property.get(p["id"], [])
        last_visit = _parse_date(visits[0]["visit_date"]) if visits else None
        linked_sites = sites_by_property.get(p["id"], [])
        commissioned_dates = [
            _parse_date(s.get("commissioned_at")) for s in linked_sites if s.get("commissioned_at")
        ]
        fallback = min(commissioned_dates) if commissioned_dates else None

        override = _parse_date(p.get("next_due_override"))
        result = compute_status(last_visit, fallback, p["maintenance_interval_days"], override_date=override)
        rows.append({
            **p,
            **result,
            "visited_this_year": visited_this_calendar_year(visits),
            "visits": visits,
        })
    return rows


def sorted_rows(rows: list[dict]) -> list[dict]:
    """The one sort order every property_rows() consumer that lists properties
    uses: overdue -> due_soon -> unknown -> up_to_date, then by name."""
    return sorted(rows, key=lambda r: (STATUS_ORDER.get(r["status"], 9), r["name"]))
