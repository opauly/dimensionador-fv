from __future__ import annotations
"""Preventive maintenance status math (Phase 10).

Pure module — no `database`/`streamlit` imports, matching
`calculations/project_finance.py`'s own convention — so the overdue LIST view
(potentially many properties) can compute every property's status in one pass over
already-fetched rows instead of one Postgres round trip each. The single-property
detail page instead calls `public.get_property_maintenance_status()` (migration 045)
directly — same logic, expressed once each in SQL and Python because they serve two
different call shapes, not because they're allowed to drift; `days_overdue` here is
the one thing the SQL function doesn't also return.
"""
from datetime import date, timedelta

DUE_SOON_WINDOW_DAYS = 30


def compute_status(
    last_visit_date: date | None,
    fallback_commissioned_at: date | None,
    interval_days: int,
    today: date | None = None,
    override_date: date | None = None,
) -> dict:
    """Returns {next_due_date, status, days_overdue} for one property.

    `status` is 'overdue' / 'due_soon' / 'up_to_date' / 'unknown' — 'unknown' only
    when there is neither a visit nor any commissioned_at to anchor a first cycle to
    (a property with no linked sites yet and no visit logged), matching
    `get_property_maintenance_status()`'s empty-result case rather than fabricating
    a status from nothing.

    `override_date` (migration 046) — a one-time manual nudge to this cycle's due
    date, e.g. a customer asked to move their visit to a different month. When set,
    it's used as `next_due_date` directly, skipping the last-visit/commissioned_at
    computation entirely — same short-circuit `get_property_maintenance_status()`
    applies in SQL. It's the caller's job to clear it once a real visit is logged
    (`site_properties_db.py:add_visit()`/`add_bundled_visit()` do this); this function
    just honors whatever it's given.
    """
    today = today or date.today()

    if override_date is not None:
        next_due_date = override_date
    else:
        base = last_visit_date or fallback_commissioned_at
        if base is None:
            return {"next_due_date": None, "status": "unknown", "days_overdue": None}
        next_due_date = base + timedelta(days=interval_days)

    days_overdue = (today - next_due_date).days

    if next_due_date < today:
        status = "overdue"
    elif next_due_date < today + timedelta(days=DUE_SOON_WINDOW_DAYS):
        status = "due_soon"
    else:
        status = "up_to_date"

    return {"next_due_date": next_due_date, "status": status, "days_overdue": days_overdue}


def visited_this_calendar_year(visits: list[dict], year: int | None = None) -> bool:
    """Any visit whose `visit_date` falls in `year` (defaults to the current year).

    Distinct from `status` — a property can be `up_to_date` (last visit within its
    interval) without having been visited in the current calendar year yet, if its
    cycle started late in the prior year. `visits` is `list_visits()`'s own shape
    (each a dict with a `visit_date` string or date)."""
    year = year or date.today().year
    for v in visits:
        visit_date = v["visit_date"]
        visit_year = visit_date.year if isinstance(visit_date, date) else int(str(visit_date)[:4])
        if visit_year == year:
            return True
    return False
