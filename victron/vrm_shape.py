from __future__ import annotations
"""
On-demand hour-of-day power shape — Fleet Dashboard Phase 2.5 (2026-08-30).

Answers "what does a day look like" for PV/load/battery/grid power, at
three granularities (today's actual hours so far, a 7-day hour-of-day
average, a 30-day hour-of-day average) — entirely on demand from VRM's own
retained history. Confirmed live against real installations: gapless 15-min
data holds for at least 180 days on an established site (a brand-new site
is simply bounded by its own install date, not by the API). No new
ingestion, no new table: unlike `vrm_live.py`'s snapshot (which its caller
upserts into `vrm.site_snapshots` on a cron), this is computed fresh on
every call and never stored.

Reuses `vrm_live.py`'s codes/discovery discipline (same "no data is better
than fabricated data" rule) rather than restating them — this module
answers "what shape," that one answers "what right now," over the same
underlying signals. PV specifically uses `vrm_live.py:fetch_pv_power_series()`
(added 2026-09-01) rather than requesting `PVP` through this module's own
`get_stats` call below — see that function's own docstring for why a
multi-charger site needs `show_instance=True` and per-instance summing to
get an honest total, the same fix already shipped for the live snapshot.
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from victron.vrm_live import (
    BATTERY_POWER_CODE,
    GRID_POWER_CODES,
    INVERTER_INPUT_CODES,
    LOAD_CODES,
    PV_POWER_CODE,
    fetch_pv_power_series,
)
from victron.vrm_series import DEFAULT_TZ_NAME, _available_codes, _series_to_pandas

logger = logging.getLogger("victron.vrm_shape")

RANGE_DAYS = {"today": 1, "week": 7, "month": 30}

_EMPTY_SHAPE = {"solar": [None] * 24, "load": [None] * 24, "battery": [None] * 24, "grid": [None] * 24}


def _hourly_average(series: pd.Series) -> list[float | None]:
    """24 floats (`None` where no sample ever fell in that hour-of-day),
    averaged across however many days the window actually covered — a
    "today" call has at most one day per bucket, "week"/"month" have
    several, both handled by the same groupby().mean()."""
    if series.empty:
        return [None] * 24
    grouped = series.groupby(series.index.hour).mean()
    return [round(float(grouped[h]), 1) if h in grouped.index else None for h in range(24)]


def fetch_site_shape(client, id_site, *, range_key: str, tz: str = DEFAULT_TZ_NAME) -> dict:
    """One site's hour-of-day PV/load/battery/grid shape for `range_key`
    ("today"/"week"/"month"). Never raises for a site with nothing usable —
    returns an all-`None` shape instead, same posture as `vrm_live.py`'s
    `fetch_live_snapshot()`, since one site's failure must not break a
    fleet-wide aggregate that sums many sites' calls to this function."""
    if range_key not in RANGE_DAYS:
        raise ValueError(f"unknown range_key: {range_key!r}")

    try:
        zone = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(DEFAULT_TZ_NAME)

    try:
        diagnostics = client.get_diagnostics(id_site)
    except Exception:  # noqa: BLE001 — one site must not break a fleet aggregate
        logger.warning("vrm_shape: get_diagnostics failed for installation %s", id_site)
        return dict(_EMPTY_SHAPE)
    available = _available_codes(diagnostics)
    if not available:
        return dict(_EMPTY_SHAPE)

    has_pv = PV_POWER_CODE in available
    # Same meter-first, inverter-fallback preference as vrm_live.py's live
    # snapshot — see that module's GRID_POWER_CODES/INVERTER_INPUT_CODES
    # comment for why the two aren't interchangeable.
    if any(c in available for c in GRID_POWER_CODES):
        grid_codes: tuple[str, ...] = GRID_POWER_CODES
    elif any(c in available for c in INVERTER_INPUT_CODES):
        grid_codes = INVERTER_INPUT_CODES
    else:
        grid_codes = ()

    requested: set[str] = set()
    for code in LOAD_CODES:
        if code in available:
            requested.add(code)
    if BATTERY_POWER_CODE in available:
        requested.add(BATTERY_POWER_CODE)
    for code in grid_codes:
        if code in available:
            requested.add(code)

    if not requested and not has_pv:
        return dict(_EMPTY_SHAPE)

    now = datetime.now(timezone.utc)
    if range_key == "today":
        # Midnight in the SITE's own local timezone, not UTC midnight — a
        # site west of UTC would otherwise lose its evening hours off the
        # front of "today."
        local_now = now.astimezone(zone)
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_s = int(start_local.astimezone(timezone.utc).timestamp())
    else:
        start_s = int((now - timedelta(days=RANGE_DAYS[range_key])).timestamp())
    end_s = int(now.timestamp())

    series_by_code: dict[str, pd.Series] = {}
    if requested:
        try:
            body = client.get_stats(id_site, type="custom", interval="15mins",
                                    start=start_s, end=end_s, attribute_codes=sorted(requested))
        except Exception:  # noqa: BLE001 — see the get_diagnostics() try/except above
            logger.warning("vrm_shape: get_stats failed for installation %s", id_site)
            return dict(_EMPTY_SHAPE)
        records = body.get("records", body) if isinstance(body, dict) else {}
        series_by_code = {
            code: _series_to_pandas(records.get(code, False) if isinstance(records, dict) else False, zone)
            for code in requested
        }

    load_parts = [series_by_code[c] for c in LOAD_CODES if c in series_by_code and not series_by_code[c].empty]
    load_series = pd.concat(load_parts, axis=1).sum(axis=1, min_count=1) if load_parts else pd.Series(dtype=float)

    grid_parts = [series_by_code[c] for c in grid_codes if c in series_by_code and not series_by_code[c].empty]
    grid_series = pd.concat(grid_parts, axis=1).sum(axis=1, min_count=1) if grid_parts else pd.Series(dtype=float)

    # Correctly summed across every solar-charger instance — see
    # fetch_pv_power_series()'s own docstring; a plain `attributeCodes[]`
    # request for PVP (the path every other code above still uses) returns
    # one ambiguous, unsummable series on a multi-charger site.
    solar_series = (fetch_pv_power_series(client, id_site, interval="15mins",
                                          start=start_s, end=end_s, zone=zone)
                    if has_pv else pd.Series(dtype=float))
    battery_series = series_by_code.get(BATTERY_POWER_CODE, pd.Series(dtype=float))

    return {
        "solar": _hourly_average(solar_series),
        "load": _hourly_average(load_series),
        "battery": _hourly_average(battery_series),
        # `None` for every hour (not just empty) when this site has no grid
        # meter at all — the caller/frontend already treats an all-`None`
        # series as "unavailable," same convention `grid_power_w: None`
        # already uses on the live-snapshot path.
        "grid": _hourly_average(grid_series) if grid_parts else [None] * 24,
    }
