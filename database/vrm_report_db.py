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


# ──────────────────────────────────────────────────────────────────
# Report window assembly
# ──────────────────────────────────────────────────────────────────
MAX_CUSTOM_RANGE_DAYS = 31
# Phase A cap (plan doc §21). Enforced here, not just in the UI that currently
# calls this — a caller that skips the UI must not be able to skip the limit
# either. Chosen for the daily bar/SOC charts' legibility, not for any data or
# performance reason; a future "Overview" mode for longer windows renders
# differently rather than raising this number (see plan doc §21, Phase B).


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
    if num_days > MAX_CUSTOM_RANGE_DAYS:
        raise ValueError(
            f"Report window is {num_days} days; the cap is "
            f"{MAX_CUSTOM_RANGE_DAYS} (plan doc §21, Phase A). Longer windows "
            "need the not-yet-built Overview mode, not a bigger version of "
            "this report."
        )

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

    trend = []
    for i in range(3, -1, -1):
        b_end = end - timedelta(days=7 * i)
        b_start = b_end - timedelta(days=6)
        bucket = slice_days(b_start, b_end)
        trend.append({
            "label": b_start.isoformat()[5:],
            "start": b_start.isoformat(),
            "end": b_end.isoformat(),
            "days": len(bucket),
            "pv": round(sum(float(r.get("pv_kwh") or 0) for r in bucket), 1),
            "load": round(sum(float(r.get("load_kwh") or 0) for r in bucket), 1),
        })

    return {
        "schema": schema,
        "site": site,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "days": current,
        "previous_days": previous,
        "trend": trend,
        "health": get_daily_health(site_id, start, end, schema),
        "longest_outage_minutes": get_longest_outage_minutes(site_id, start, end, schema),
        # A window can be short because the CSV didn't cover it or because
        # Node-RED missed days. The report must be able to say so rather than
        # present 3 days of data as a full window.
        "expected_days": num_days,
        "missing_days": num_days - len(current),
    }
