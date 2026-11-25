"""Recurring expenses (fase 25.4, adelantada): which months are due and the memo.

Pure module. A rule charges on `day_of_month` of every month from
`start_date` (inclusive) to `end_date` (if any). Day 29–31 falls back to the
month's last day. `due_dates()` lists every charge date up to `today` that
has no movement yet, so months missed while nobody opened the app are
caught up too.
"""
from __future__ import annotations

import calendar
from datetime import date

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def charge_date(year: int, month: int, day: int) -> date:
    return date(year, month, min(int(day), calendar.monthrange(year, month)[1]))


def period(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def memo(template: str, d: date) -> str:
    """'Google Workspace [mes]' → 'Google Workspace diciembre 2026'.
    [mes] alone adds the year (so the list reads clearly across years);
    if the template also has [año], [mes] is just the month name."""
    mes = MESES[d.month - 1]
    text = template or ""
    if "[año]" in text or "[ano]" in text:
        return text.replace("[mes]", mes).replace("[año]", str(d.year)).replace("[ano]", str(d.year))
    return text.replace("[mes]", f"{mes} {d.year}")


def due_dates(rule: dict, today, done_periods: set[str]) -> list[date]:
    if not rule.get("active", True):
        return []
    today = _d(today)
    start = _d(rule["start_date"])
    end = _d(rule["end_date"]) if rule.get("end_date") else None
    y, m = start.year, start.month
    out = []
    while (y, m) <= (today.year, today.month):
        d = charge_date(y, m, rule["day_of_month"])
        if start <= d <= today and (end is None or d <= end) and period(d) not in done_periods:
            out.append(d)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def next_date(rule: dict, today) -> date | None:
    """The next charge after today (for the list of rules)."""
    if not rule.get("active", True):
        return None
    today = _d(today)
    start = _d(rule["start_date"])
    ref = max(today, start)
    y, m = ref.year, ref.month
    for _ in range(24):
        d = charge_date(y, m, rule["day_of_month"])
        if d > today and d >= start:
            if rule.get("end_date") and d > _d(rule["end_date"]):
                return None
            return d
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return None
