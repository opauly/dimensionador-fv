"""Checks for calculations/recurring.py (Phase 25.4). No database needed.

    .venv/bin/python scripts/validate_phase25_recurring.py
"""
from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculations.recurring import due_dates, memo, next_date  # noqa: E402

gw = {"day_of_month": 1, "start_date": "2026-11-24", "active": True}
assert due_dates(gw, "2026-11-30", set()) == []                       # Nov 1 is before the start
assert due_dates(gw, "2026-12-01", set()) == [date(2026, 12, 1)]
assert due_dates(gw, "2026-12-01", {"2026-12"}) == []                 # already created
# months missed while the app was closed are caught up
assert due_dates(gw, "2027-02-15", {"2026-12"}) == [date(2027, 1, 1), date(2027, 2, 1)]
assert next_date(gw, "2026-11-24") == date(2026, 12, 1)
assert next_date(gw, "2026-12-01") == date(2027, 1, 1)

# day 31 in February → last day; end date stops it; paused does nothing
r31 = {"day_of_month": 31, "start_date": "2027-01-01", "end_date": "2027-02-28", "active": True}
assert due_dates(r31, "2027-04-30", set()) == [date(2027, 1, 31), date(2027, 2, 28)]
assert next_date(r31, "2027-02-28") is None
assert due_dates({**gw, "active": False}, "2027-02-15", set()) == []

# a start date in the past backfills from there
assert due_dates({"day_of_month": 15, "start_date": "2026-09-01", "active": True}, "2026-11-24", set()) \
    == [date(2026, 9, 15), date(2026, 10, 15), date(2026, 11, 15)]

assert memo("Google Workspace [mes]", date(2026, 12, 1)) == "Google Workspace diciembre 2026"
assert memo("Alquiler [mes] de [año]", date(2027, 1, 1)) == "Alquiler enero de 2027"
assert memo("Contador", date(2027, 1, 1)) == "Contador"

print("Phase 25.4 recurring checks: all passed")
