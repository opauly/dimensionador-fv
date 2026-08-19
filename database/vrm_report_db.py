from __future__ import annotations
"""
Schema-agnostic reader for the Victron weekly report.

Ports Apps Script's `fetchSiteRow_` / `fetchEnergyDailyRows_` /
`fetchDailyHealthRows_` / `fetchLongestOutageMinutes_`
(`victron-monitor/apps-script/Victron_Events_App_Script_v1p7.js` ~lines
1634-1750) into Python, with one addition: every function takes a `schema`.

`monitoring` holds Pauly & Co's own Cerbo GX sites, written by Node-RED.
`vrm` holds external customers' sites, written from VRM CSV exports. The two
have the same table and column shape by design, so the report reads either
through this one module. That's the whole bet: one reader, one set of KPI
definitions, instead of a Python copy that drifts from the Apps Script
original — which is exactly what went wrong in the Sheets-to-Supabase
migration (see CONTEXT.md).

Everything here is read-only. Ingestion writes live in `victron/`.
"""
from datetime import date, timedelta

from database.supabase_client import get_client

MONITORING = "monitoring"
VRM = "vrm"

# Which `dump_type` values are real data in each schema.
#
# Node-RED writes AUTO for scheduled dumps and MANUAL/TEST while someone is
# debugging on a live site. Filtering these server-side is not cosmetic: the
# Sheets-era report summed TEST rows into weekly totals and silently inflated
# every PV and load figure for weeks.
REAL_DUMP_TYPES = {
    MONITORING: ("AUTO",),
    VRM: ("csv_upload", "vrm_api"),
}


def _dump_types(schema: str, dump_types: tuple[str, ...] | None) -> tuple[str, ...]:
    if dump_types is not None:
        return dump_types
    try:
        return REAL_DUMP_TYPES[schema]
    except KeyError:
        raise ValueError(
            f"Unknown schema {schema!r} — expected {MONITORING!r} or {VRM!r}. "
            "Pass dump_types explicitly to read from somewhere else."
        ) from None


def _table(schema: str, name: str):
    return get_client().schema(schema).table(name)


# ──────────────────────────────────────────────────────────────────
# Sites
# ──────────────────────────────────────────────────────────────────
def list_sites(schema: str, active_only: bool = True) -> list[dict]:
    """All sites in a schema, ordered by display name."""
    q = _table(schema, "sites").select("*")
    if active_only:
        q = q.eq("active", True)
    return q.order("display_name").execute().data or []


def get_site(site_id: str, schema: str) -> dict | None:
    """One site row, or None. Equivalent of `fetchSiteRow_`."""
    rows = _table(schema, "sites").select("*").eq("site_id", site_id).limit(1).execute().data
    return rows[0] if rows else None


# ──────────────────────────────────────────────────────────────────
# Energy
# ──────────────────────────────────────────────────────────────────
def get_energy_daily(site_id: str, start: str | date, end: str | date, schema: str,
                     dump_types: tuple[str, ...] | None = None) -> list[dict]:
    """`energy_daily` rows for an inclusive date range.

    Both bounds are inclusive, matching the Apps Script original's
    `date=gte.<start>&date=lte.<end>`.
    """
    return (_table(schema, "energy_daily").select("*")
            .eq("site_id", site_id)
            .in_("dump_type", list(_dump_types(schema, dump_types)))
            .gte("date", str(start)).lte("date", str(end))
            .order("date").execute().data or [])


def get_daily_health(site_id: str, start: str | date, end: str | date, schema: str,
                     dump_types: tuple[str, ...] | None = None) -> list[dict]:
    """`daily_health` rows for an inclusive date range."""
    return (_table(schema, "daily_health")
            .select("date,health_score,health_status,alarms_count,min_soc,"
                    "outage_count,outage_minutes,grid_dependency_pct,battery_cycles,notes")
            .eq("site_id", site_id)
            .in_("dump_type", list(_dump_types(schema, dump_types)))
            .gte("date", str(start)).lte("date", str(end))
            .order("date").execute().data or [])


def get_available_dates(site_id: str, schema: str,
                        dump_types: tuple[str, ...] | None = None) -> list[str]:
    """Every date with data, ascending — drives the report's week picker.

    Node-RED writes yesterday's row daily, so `monitoring` is dense. A CSV
    export covers whatever window the customer chose, so `vrm` can have gaps
    and the UI must offer real dates rather than a free date input.
    """
    rows = (_table(schema, "energy_daily").select("date")
            .eq("site_id", site_id)
            .in_("dump_type", list(_dump_types(schema, dump_types)))
            .order("date").execute().data or [])
    return [r["date"] for r in rows]


def get_longest_outage_minutes(site_id: str, start: str | date, end: str | date,
                               schema: str) -> float:
    """Longest single outage in the window.

    `monitoring` has `grid_events`, one row per outage with its own duration —
    the Apps Script original reads that. `vrm` has no such table: the CSV
    mapper resolves outages into per-day `outage_count`/`outage_minutes`
    aggregates and does not persist individual events.

    So for `vrm` this returns the largest single *day's* total, which is an
    upper bound on the longest single outage and equals it whenever a day had
    at most one outage. Flagged rather than silently reported as exact — if
    the report starts leaning on this figure, `vrm` needs a `grid_events`
    table and the mapper needs to write the events it already computes.
    """
    if schema == MONITORING:
        rows = (_table(schema, "grid_events").select("duration_minutes")
                .eq("site_id", site_id)
                .gte("timestamp", f"{start}T00:00:00")
                .lte("timestamp", f"{end}T23:59:59")
                .execute().data or [])
        return max((float(r.get("duration_minutes") or 0) for r in rows), default=0.0)

    rows = get_energy_daily(site_id, start, end, schema)
    return max((float(r.get("outage_minutes") or 0) for r in rows), default=0.0)


def get_low_battery_shutdown_count(site_id: str, start: str | date, end: str | date,
                                   schema: str) -> int:
    """Count of Low Battery Alarm *starts* (the inverter shutting down on a
    low-battery condition) within the window — an off-grid-specific metric
    (report bug fix, 2026-08-18).

    `alarm_events` has the same shape in both `monitoring` (Node-RED) and
    `vrm` (CSV/API) schemas, and both write the identical label
    `'Low Battery Alarm'` with `WARNING`/`CLEARED` severities per episode
    (confirmed live against `vista-atenas-lp-m3` in `monitoring` and every
    `vrm` site's `ALARM_CATEGORIES`/`vrm_daily.alarm_episode_events()`), so
    one query serves both — no schema branching needed here, unlike
    `get_longest_outage_minutes` above.

    Counts only `severity = 'WARNING'` rows — the shutdown-start edge of each
    episode. Counting both `WARNING` and `CLEARED` would double the real
    number of shutdown events, since every episode writes one of each.
    """
    rows = (_table(schema, "alarm_events").select("id")
            .eq("site_id", site_id)
            .eq("alarm", "Low Battery Alarm")
            .eq("severity", "WARNING")
            .gte("timestamp", f"{start}T00:00:00")
            .lte("timestamp", f"{end}T23:59:59")
            .execute().data or [])
    return len(rows)


def get_alarm_episode_counts_by_category(site_id: str, start: str | date, end: str | date,
                                         schema: str) -> dict[str, int]:
    """Episode-start count per `alarm` category within the window — one
    query, grouped in Python (report bug fix, 2026-08-19), for the Events
    section's "which alarm fired how many times" breakdown.

    Counts only `severity = 'WARNING'` rows, same reasoning as
    `get_low_battery_shutdown_count()` above: each episode writes one
    `WARNING` (start) and one `CLEARED` (end) row, so counting both would
    double the real number of episodes.

    Only the categories `ALARM_CATEGORIES` (`victron/vrm_csv.py`) actually
    scores — `'Low Battery Alarm'`, `'Overload Alarm'` — show up here in
    practice; unscored signals (DC ripple, temperature, Battery Monitor
    faults — `UNSCORED_ALARM_SIGNALS`) are a different, lower-confidence
    tier this function does not touch, deliberately, matching how they've
    never been scored or counted anywhere else in this product.

    `sum(this function's values)` is `alarmEpisodesTotal` (`weekly_report.py`
    — the Events section's "Total" AND what the AI narrative cites), NOT
    `sum(daily_health.alarms_count)`, deliberately: `vrm.count_alarm_
    episodes()` (migration 012) tracks a single in/out state PER SITE PER
    DAY across every category combined, so a second category's `WARNING`
    arriving while the first is still active does not open a new counted
    episode there. This function, querying `alarm_events` directly per
    category, does not have that limitation. **Not a rare edge case** — a
    first draft of this feature assumed it was and shipped `alarmEpisodesTotal`
    still wired to `alarms_count`; caught immediately from a real site
    (`vista-atenas-2-floor-pool`, 2026-07-21..28): 68 Low battery + 29
    Overload = 97 from this function, vs. 83 from `alarms_count` — an 18%
    gap on ordinary, real data. `daily_health.alarms_count` / the persisted
    `health_score` are untouched by this (a separate, Postgres-trigger-
    computed value this module never recalculates) — only what a customer
    reads as "how many alarm episodes happened" changed, to the more
    complete number.
    """
    rows = (_table(schema, "alarm_events").select("alarm")
            .eq("site_id", site_id)
            .eq("severity", "WARNING")
            .gte("timestamp", f"{start}T00:00:00")
            .lte("timestamp", f"{end}T23:59:59")
            .execute().data or [])
    counts: dict[str, int] = {}
    for row in rows:
        alarm = row.get("alarm")
        if alarm:
            counts[alarm] = counts.get(alarm, 0) + 1
    return counts


# ──────────────────────────────────────────────────────────────────
# Report window assembly
# ──────────────────────────────────────────────────────────────────
MAX_CUSTOM_RANGE_DAYS = 31
# Phase A cap (plan doc §21) — the Detallado/daily-report boundary. Past this,
# `fetch_report_window` sets `is_overview` instead of raising (plan doc §22):
# the cap became a mode boundary, not a hard stop, once the Overview report
# existed to render the longer side of it. Still enforced here, not just in
# the UI that calls this — a caller that skips the UI must not be able to
# skip the boundary either. Chosen for the daily bar/SOC charts' legibility,
# not for any data or performance reason.
MAX_OVERVIEW_RANGE_DAYS = 183
# Phase B's real ceiling (plan doc §22, locked with the user 2026-08-15;
# ~6 months). Overview mode has no upper bound of its own otherwise — this is
# where a pick actually gets rejected now, in the same place the old
# MAX_CUSTOM_RANGE_DAYS check used to raise.


def bucket_days(rows: list[dict], start: date, end: date,
                bucket_len_days: int) -> list[dict]:
    """Groups `rows` (already-fetched `energy_daily` rows) into consecutive
    `bucket_len_days`-day buckets spanning `[start, end]` inclusive, walking
    forward from `start`. The final bucket is clipped to `end`, so it's
    shorter than `bucket_len_days` whenever the span isn't an exact multiple
    — expected for the Overview report's monthly buckets over an arbitrary
    range (plan doc §22).

    The fixed 4-week trend (`fetch_report_window` below) calls this with a
    28-day span and `bucket_len_days=7`, which divides evenly into 4 buckets
    identical to what used to be a separate anchored-from-`end` loop —
    forward-from-`start` and anchored-from-`end` coincide exactly whenever
    the span is a whole multiple of the bucket size, so this one function
    serves both without the trend needing special-cased logic.

    Each bucket: `{label, start, end, days, pv, load, grid, discharge,
    min_soc, max_soc}`. `days` counts how many of the bucket's calendar days
    actually have a row — a bucket can be short because the site's data
    doesn't cover it, the same "don't silently show a partial period as a
    full one" rule the rest of this module follows. `min_soc`/`max_soc` are
    named to match `energy_daily`'s own columns on purpose (the min of the
    bucket's daily `min_soc` values, the max of its daily `max_soc` values)
    — the SOC chart can swap its per-day source for a per-bucket one without
    also renaming the fields it reads. `grid`/`discharge` (summed
    `grid_kwh`/`battery_discharge_kwh`) exist so the grid-independence and
    battery-cycling trend can derive per-bucket figures with the exact same
    formula `weekly_report.py` already uses for the period totals, rather
    than a second definition (plan doc §22).
    """
    by_date = {r["date"]: r for r in rows}
    buckets = []
    b_start = start
    while b_start <= end:
        b_end = min(b_start + timedelta(days=bucket_len_days - 1), end)
        day, bucket_rows = b_start, []
        while day <= b_end:
            row = by_date.get(day.isoformat())
            if row is not None:
                bucket_rows.append(row)
            day += timedelta(days=1)
        min_socs = [float(r["min_soc"]) for r in bucket_rows if r.get("min_soc") is not None]
        max_socs = [float(r["max_soc"]) for r in bucket_rows if r.get("max_soc") is not None]
        buckets.append({
            "label": b_start.isoformat()[5:],
            "start": b_start.isoformat(),
            "end": b_end.isoformat(),
            "days": len(bucket_rows),
            "pv": round(sum(float(r.get("pv_kwh") or 0) for r in bucket_rows), 1),
            "load": round(sum(float(r.get("load_kwh") or 0) for r in bucket_rows), 1),
            "grid": round(sum(float(r.get("grid_kwh") or 0) for r in bucket_rows), 1),
            "discharge": round(sum(float(r.get("battery_discharge_kwh") or 0)
                                   for r in bucket_rows), 1),
            "min_soc": min(min_socs) if min_socs else None,
            "max_soc": max(max_socs) if max_socs else None,
        })
        b_start = b_end + timedelta(days=1)
    return buckets


def bucket_health_days(rows: list[dict], start: date, end: date,
                       bucket_len_days: int) -> list[dict]:
    """Same boundary-walking as `bucket_days()`, over `daily_health` rows
    instead of `energy_daily` ones — a separate function because the two
    tables have no shared row shape and `daily_health` needs its own
    dedup-by-date rule before aggregating (plan doc §22).

    A site can have more than one `daily_health` row per date (different
    `dump_type`s), so each bucket first keeps only the highest-scoring row
    per date — identical to the whole-period average's own dedup in
    `weekly_report.py` — then averages `health_score` across the kept rows.

    Each bucket: `{label, start, end, days, health_score}`. `health_score`
    is `None` for a bucket with no health rows at all, rather than 0 — a
    missing score must not read as a scored zero.
    """
    by_date: dict[str, dict] = {}
    for r in rows:
        d0 = r["date"]
        if d0 not in by_date or (float(r.get("health_score") or 0)
                                 > float(by_date[d0].get("health_score") or 0)):
            by_date[d0] = r

    buckets = []
    b_start = start
    while b_start <= end:
        b_end = min(b_start + timedelta(days=bucket_len_days - 1), end)
        day, scores = b_start, []
        while day <= b_end:
            row = by_date.get(day.isoformat())
            if row is not None and row.get("health_score") is not None:
                scores.append(float(row["health_score"]))
            day += timedelta(days=1)
        buckets.append({
            "label": b_start.isoformat()[5:],
            "start": b_start.isoformat(),
            "end": b_end.isoformat(),
            "days": len(scores),
            "health_score": round(sum(scores) / len(scores)) if scores else None,
        })
        b_start = b_end + timedelta(days=1)
    return buckets


def week_bounds(week_ending: str | date) -> tuple[date, date]:
    """The 7-day window ending on `week_ending`, inclusive both ends.

    Still exactly what `monitoring`'s automatic weekly report uses — that
    report's cadence is unchanged by the `vrm` custom-range work below callers
    compute bounds themselves and pass them to `fetch_report_window`, and this
    is how the fixed-week caller does it.

    Apps Script uses `start = today - 7` with both bounds inclusive, i.e. an
    8-day span. That is a real off-by-one in the original — a "weekly" report
    that double-counts one day at the boundary between consecutive weeks. Fixed
    here to a true 7 days; noted because it means this report's totals will not
    match an archived Apps Script PDF exactly, and that difference is the fix,
    not a regression.
    """
    end = date.fromisoformat(str(week_ending))
    return end - timedelta(days=6), end


def fetch_report_window(site_id: str, start: str | date, end: str | date,
                        schema: str) -> dict:
    """Everything the report needs for an inclusive [start, end] window, in
    one call.

    Both `monitoring`'s fixed weekly report and `vrm`'s operator-chosen custom
    range go through this — the window itself has no opinion about who's
    calling or how long it is. `monitoring`'s caller computes `(start, end)`
    via `week_bounds()`; `vrm`'s caller passes whatever the operator picked.

    Fetches the full required span once and slices locally, rather than the
    Apps Script original's seven round trips (one per trend bucket, plus
    current and previous week).
    """
    site = get_site(site_id, schema)
    if site is None:
        raise ValueError(f"No site {site_id!r} in schema {schema!r}")

    start = date.fromisoformat(str(start))
    end = date.fromisoformat(str(end))
    if start > end:
        raise ValueError(f"start ({start}) is after end ({end})")
    num_days = (end - start).days + 1
    if num_days > MAX_OVERVIEW_RANGE_DAYS:
        raise ValueError(
            f"Report window is {num_days} days; the cap is "
            f"{MAX_OVERVIEW_RANGE_DAYS} (plan doc §22, Phase B)."
        )
    # Past MAX_CUSTOM_RANGE_DAYS this is an Overview report, not a bigger
    # Detallado one (plan doc §22) — auto, no operator toggle. `monitoring`'s
    # caller always passes a 7-day window via week_bounds(), so this is never
    # True for that schema in practice.
    is_overview = num_days > MAX_CUSTOM_RANGE_DAYS

    # The 4-week trend is always a fixed 4x7 days ending on `end`, regardless
    # of how long [start, end] itself is — deliberate (plan doc §21): it stays
    # useful context no matter what range the operator picked for the report.
    trend_span_start = end - timedelta(days=27)
    # "vs previous" compares against the same-length window immediately
    # before `start` — generalized from the old hardcoded 7-day lookback, so
    # a 20-day report compares against the 20 days before it, not last week.
    previous_start = start - timedelta(days=num_days)
    span_start = min(trend_span_start, previous_start)

    rows = get_energy_daily(site_id, span_start, end, schema)
    by_date = {r["date"]: r for r in rows}

    def slice_days(a: date, b: date) -> list[dict]:
        out, day = [], a
        while day <= b:
            if day.isoformat() in by_date:
                out.append(by_date[day.isoformat()])
            day += timedelta(days=1)
        return out

    current = slice_days(start, end)
    previous = slice_days(previous_start, start - timedelta(days=1))

    # Always a fixed 4x7 days ending on `end`, regardless of how long
    # [start, end] itself is (plan doc §21) — trend_span_start is 27 days
    # before `end`, so this always divides evenly into 4 weekly buckets.
    trend = bucket_days(rows, trend_span_start, end, 7)

    return {
        "schema": schema,
        "site": site,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "is_overview": is_overview,
        "days": current,
        "previous_days": previous,
        "trend": trend,
        "health": get_daily_health(site_id, start, end, schema),
        "longest_outage_minutes": get_longest_outage_minutes(site_id, start, end, schema),
        # Off-grid-only KPI (report bug fix, 2026-08-18) — skipped for every
        # other system_type so a grid-tied report doesn't pay for a query it
        # never renders.
        "low_battery_shutdown_count": (
            get_low_battery_shutdown_count(site_id, start, end, schema)
            if site.get("system_type") == "off_grid" else None
        ),
        # Every system_type, unlike the off-grid-only KPI above — the Events
        # section's per-category breakdown is useful for hybrid/grid_zero
        # sites too (report bug fix, 2026-08-19).
        "alarm_episode_counts_by_category": get_alarm_episode_counts_by_category(
            site_id, start, end, schema),
        # A window can be short because the CSV didn't cover it or because
        # Node-RED missed days. The report must be able to say so rather than
        # present 3 days of data as a full window.
        "expected_days": num_days,
        "missing_days": num_days - len(current),
    }
