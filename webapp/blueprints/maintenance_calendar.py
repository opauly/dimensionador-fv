from __future__ import annotations
"""Calendario anual tab — port of pages/07_maintenance.py:_calendar_section()
onto Flask/Jinja2/htmx (Phase 21 Step 3).

Reads exclusively from maintenance_common.property_rows() per §1.3 — no
status/next-due-date/visited-flag is recomputed here. The historical mode
(any past year) is built from the "visits" list property_rows() already
carries (§1.5), costing zero extra queries instead of the N Streamlit's own
_calendar_section() spends re-fetching list_visits() per property.

⚠ The current-year grid's `next_due_date.year <= year` filter (item 8) is the
single easiest thing in this phase to get wrong — see _current_year_ctx()'s
docstring, which is Streamlit's own _month_card() docstring carried over
verbatim. Do not "simplify" this away.
"""
from datetime import date

from flask import redirect, render_template, request, url_for

from webapp.blueprints.maintenance_common import MONTH_NAMES, STATUS_EMOJI, _parse_date, property_rows


def _month_grid_current_year(this_year_or_overdue: list[dict], current_year: int) -> list[dict]:
    """Port of _month_card() (item 9). `this_year_or_overdue` must already be
    filtered to `next_due_date.year <= <displayed year>` by the caller — a
    future-year date (already visited this cycle, not due again until next
    year) would otherwise look identical to a due-this-year date, which is
    exactly the ambiguity that prompted this filter (Oscar, 2026-09-08)."""
    by_month: dict[int, list[dict]] = {m: [] for m in range(1, 13)}
    for p in this_year_or_overdue:
        by_month[p["next_due_date"].month].append(p)

    months = []
    for m in range(1, 13):
        items = sorted(by_month[m], key=lambda p: p["next_due_date"].day)
        months.append({
            "name": MONTH_NAMES[m - 1],
            "entries": [
                {
                    "emoji": STATUS_EMOJI[p["status"]],
                    "day": p["next_due_date"].day,
                    "year_suffix": p["next_due_date"].year if p["next_due_date"].year != current_year else None,
                    "name": p["name"],
                    "visited": p["visited_this_year"],
                }
                for p in items
            ],
        })
    return months


def _month_grid_historical(by_month: dict[int, list[dict]]) -> list[dict]:
    """Port of _historical_month_card() (item 10) — real logged visits, no
    status color (there's no "overdue" concept for a year already over)."""
    months = []
    for m in range(1, 13):
        items = sorted(by_month[m], key=lambda v: v["visit_date_obj"].day)
        months.append({
            "name": MONTH_NAMES[m - 1],
            "entries": [
                {"day": v["visit_date_obj"].day, "name": v["property_name"], "amount": v.get("amount_usd")}
                for v in items
            ],
        })
    return months


def _historical_ctx(rows: list[dict], year: int) -> dict:
    by_month: dict[int, list[dict]] = {m: [] for m in range(1, 13)}
    any_visit = False
    for p in rows:
        for v in p["visits"]:
            vdate = _parse_date(v["visit_date"])
            if vdate and vdate.year == year:
                any_visit = True
                by_month[vdate.month].append({**v, "property_name": p["name"], "visit_date_obj": vdate})

    return {"any_visit": any_visit, "months": _month_grid_historical(by_month)}


def _current_year_ctx(rows: list[dict], year: int) -> dict:
    not_visited = [r for r in rows if not r["visited_this_year"]]

    scheduled = [p for p in rows if p["next_due_date"]]
    unscheduled = [p for p in rows if not p["next_due_date"]]

    # A next_due_date in a FUTURE year means this property was already visited
    # and its next cycle isn't due until then — showing it in this year's grid
    # (bucketed only by month, ignoring year) is exactly what looked like
    # "already fine this year" when it's really "already done, see you next
    # year." Kept out of the grid entirely instead (item 8).
    this_year_or_overdue = [p for p in scheduled if p["next_due_date"].year <= year]
    future_cycle = sorted((p for p in scheduled if p["next_due_date"].year > year), key=lambda p: p["next_due_date"])

    scheduled_for_picker = sorted(scheduled, key=lambda p: p["name"])

    return {
        "not_visited": not_visited,
        "months": _month_grid_current_year(this_year_or_overdue, year),
        "future_cycle": [
            {"name": p["name"], "next_due_date_iso": p["next_due_date"].isoformat()} for p in future_cycle
        ],
        "unscheduled": unscheduled,
        "scheduled": [
            {
                "id": p["id"], "name": p["name"],
                "next_due_date_iso": p["next_due_date"].isoformat(),
                "next_due_override": bool(p.get("next_due_override")),
            }
            for p in scheduled_for_picker
        ],
    }


def render_calendar_panel(year: int | None, error: str | None = None) -> str:
    current_year = date.today().year
    year = year or current_year
    year_options = list(range(current_year, current_year - 6, -1))

    try:
        rows = property_rows()
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))

    ctx = {
        "year": year, "year_options": year_options, "current_year": current_year,
        "error": error, "is_historical": year != current_year,
    }

    if not rows:
        return render_template("maintenance/_calendar.html", rows_empty=True, **ctx)

    if year != current_year:
        ctx.update(_historical_ctx(rows, year))
    else:
        ctx.update(_current_year_ctx(rows, year))

    return render_template("maintenance/_calendar.html", rows_empty=False, **ctx)


def register(bp):
    @bp.route("/calendario/override", methods=["POST"])
    def calendario_override():
        from database.site_properties_db import set_due_override

        form = request.form
        property_id = form.get("property_id")
        action = form.get("action") or "aplicar"
        new_date = form.get("new_date")
        try:
            year = int(form.get("anio") or date.today().year)
        except ValueError:
            year = date.today().year

        error = None
        try:
            if action == "restablecer":
                set_due_override(property_id, None)
            elif new_date:
                set_due_override(property_id, new_date)
            else:
                error = "Selecciona una fecha."
        except Exception as exc:
            error = f"Error: {exc}"

        return redirect(url_for("maintenance.calendario", anio=year, error=error), code=303)
