from __future__ import annotations
"""
Pure period arithmetic for scheduled reports (PLAN_PHASE17.md §3.2, §0.3,
§8 Step 6). No database access, no I/O, no network — the one piece of this
phase genuinely tricky enough to need to be testable without a DB, a
network, or a clock, per the plan's own naming rule for this file.

`compute_due_period()` is the whole surface: given a schedule and "now,"
return the `(period_start, period_end)` this cadence is currently pointing
at, or `None` if it isn't due yet at this exact moment. It does NOT know
about `vrm.report_runs` — whether that period was ALREADY generated is
`vrm_api/report_runs.py`'s job (the partial unique index is the real
guarantee; this function would happily return the same period every time
it's called across many days, by design — see §0.5 Decision 1: a missed
cron run self-heals because "due" is computed from the calendar, not a
timer, and idempotency lives downstream, not here).

Time zones: this function requires a real IANA name and lets
`zoneinfo.ZoneInfoNotFoundError` propagate on a bad one — deliberately not
caught here (§3.3: "a bad timezone value must not break the run," but that
means the RUN continues past one bad site, not that this pure function
pretends a garbage string means something). The caller (`routers/
reports.py:post_run_due()`) wraps each site in its own try/except, which is
what actually turns a bad timezone into one `failed` row instead of a
crashed fan-out.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# 28-day cap on report_schedule_day_of_month (migration 026's own CHECK) is
# what guarantees `_most_recent_day_of_month()` below never has to handle a
# day that doesn't exist in some month — every month has at least 28 days.
_VALID_SCHEDULES = {"daily", "weekly", "monthly"}


def _most_recent_weekday(today: date, weekday: int) -> date:
    """The most recent date `<= today` whose ISO weekday (1=Monday..7=Sunday)
    equals `weekday`. Always returns a date `<= today` — the modular
    subtraction below can never produce a future anchor."""
    delta = (today.isoweekday() - weekday) % 7
    return today - timedelta(days=delta)


def _most_recent_day_of_month(today: date, day_of_month: int) -> date:
    """The most recent date `<= today` whose day-of-month equals
    `day_of_month` (1-28). If today's day hasn't reached it yet this month,
    the anchor is in the PREVIOUS month — never a future date."""
    if today.day >= day_of_month:
        return date(today.year, today.month, day_of_month)
    if today.month == 1:
        return date(today.year - 1, 12, day_of_month)
    return date(today.year, today.month - 1, day_of_month)


def compute_due_period(
    schedule: str,
    weekday: int,
    day_of_month: int,
    hour: int,
    tz_name: str,
    now_utc: datetime,
) -> tuple[date, date] | None:
    """PLAN_PHASE17.md §3.2's table, implemented literally. `now_utc` must be
    timezone-aware (UTC) — every caller in this codebase already constructs
    `datetime.now(timezone.utc)` this way (`vrm_api/jobs.py:_now()`,
    `vrm_api/branding.py`, etc.), so this function trusts that rather than
    re-validating it.

    Returns `(period_start, period_end)` (both inclusive) if this cadence is
    due RIGHT NOW in the site's own timezone, else `None`. `schedule='off'`
    (or any value outside {'daily','weekly','monthly'}) always returns
    `None` — the caller is expected to have already filtered `report_schedule
    <> 'off'` at the query level (migration 026's own CHECK makes `'off'`
    the only possible value for a non-`vrm_api` site anyway), but this
    function doesn't assume that and simply has nothing to compute for it.
    """
    if schedule not in _VALID_SCHEDULES:
        return None

    tz = ZoneInfo(tz_name)  # raises ZoneInfoNotFoundError on a bad name — see module docstring
    local_now = now_utc.astimezone(tz)
    today = local_now.date()
    due_hour_reached = local_now.hour >= hour

    if not due_hour_reached:
        return None

    if schedule == "daily":
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday

    if schedule == "weekly":
        anchor = _most_recent_weekday(today, weekday)
        return anchor - timedelta(days=7), anchor - timedelta(days=1)

    # schedule == "monthly" — the complete calendar month immediately
    # preceding the anchor's own month (NOT "anchor minus 7/1 days" the way
    # daily/weekly are — a real calendar month, 28-31 days).
    anchor = _most_recent_day_of_month(today, day_of_month)
    anchor_month_first = date(anchor.year, anchor.month, 1)
    period_end = anchor_month_first - timedelta(days=1)
    period_start = date(period_end.year, period_end.month, 1)
    return period_start, period_end
