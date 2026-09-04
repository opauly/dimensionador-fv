from __future__ import annotations
"""
Fleet Dashboard Phase 3d — "incomplete charging" anomaly detection
(2026-09-03, extending PLAN_PHASE19_FLEET_P3.md's own three-check set with
a fourth Oscar asked for directly, once the first three were live).

Sibling of `victron/anomaly_drift.py`'s two checks and `anomaly_silence.py`'s
one — same `vrm.site_anomalies` table, same "one open row per (site_id,
anomaly_type)" shape, same deterministic/no-ML posture. Unlike the other
three, this one needs no PVGIS/irradiance data at all: it only reads
`vrm.energy_daily.battery_reached_float`, a signal `vrm.compute_daily_
health()` already reads for its own single-day "Battery did not fully
charge today" note (migration 012). This check is the SUSTAINED version of
that exact same signal, catching a pattern the single-day note can't — one
bad day is normal; five bad days out of the last seven is a battery that
may be degrading, or a system undersized for its load, either way worth a
customer/admin actually looking at rather than replacing.

── Why this applies to off_grid AND hybrid, unlike a grid-dependency
   check ────────────────────────────────────────────────────────────────
Considered "rising grid dependency" as this fourth check first — rejected
specifically because off_grid sites have no grid to depend on at all, so
it would be silently inapplicable to a real chunk of the fleet. Whether a
battery reaches full charge is a real question for every battery-equipped
system regardless of whether it also has a grid connection, which is why
this one was built instead. `grid_zero` (no battery) is the one system
type genuinely out of scope — `battery_reached_float` is meaningless
there, same reasoning `vrm.compute_daily_health()`'s own `v_has_battery`
gate (migration 012/039) already applies to the identical signal.

── Exclusion rules ─────────────────────────────────────────────────────────
Drops a day with `complete_day = false` (a partial day shouldn't count as
evidence either way) and a day with `battery_reached_float IS NULL` (can't
tell, not "didn't reach float" — "no data over fabricated data", the same
posture everywhere else in this pipeline).

── The rule ─────────────────────────────────────────────────────────────────
Looks at the last `_WINDOW_DAYS` calendar days. Needs at least
`_MIN_VALID_DAYS` real (non-excluded) days in that window to say anything
at all — fewer than that and the check does nothing (fail closed), same
posture `anomaly_drift.py`'s own checks use for insufficient history, just
scaled to a much shorter window since this signal doesn't need PVGIS's
multi-year climatology to mean something. Flags when at least
`_INCOMPLETE_DAYS_REQUIRED` of those valid days did NOT reach float —
sustained, not a single off day (a night of unusually high late-evening
load, one cloudy afternoon).
"""
import logging
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger("victron.anomaly_battery")

INCOMPLETE_CHARGING_TYPE = "incomplete_charging"

_WINDOW_DAYS = 7
_MIN_VALID_DAYS = 5
_INCOMPLETE_DAYS_REQUIRED = 5


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _valid_daily_rows(energy_daily_rows: list[dict]) -> list[dict]:
    """Same shape as `anomaly_drift.py`'s own `_valid_daily_rows()`, not
    imported from it — that one filters on `pv_kwh`, this one on
    `battery_reached_float`; different signal, same exclusion posture,
    kept as its own small copy rather than a shared helper parameterized
    over which column to check."""
    out = []
    for r in energy_daily_rows:
        if r.get("battery_reached_float") is None or r.get("complete_day") is False:
            continue
        if _parse_date(r.get("date")) is None:
            continue
        out.append(r)
    return out


def _clear_open(anomalies_table, open_row: dict | None, now_utc: datetime, *, log_msg: str, site_id: str) -> None:
    if open_row is None:
        return
    anomalies_table.update({"cleared_at": now_utc.isoformat()}).eq("id", open_row["id"]).execute()
    logger.info(log_msg, site_id)


def _open_or_update(anomalies_table, open_row: dict | None, *, site_id: str, anomaly_type: str,
                    detected_at_iso: str, detail: dict, log_msg: str) -> None:
    if open_row is not None:
        anomalies_table.update({"detail": detail}).eq("id", open_row["id"]).execute()
        return
    anomalies_table.insert({
        "site_id": site_id, "anomaly_type": anomaly_type,
        "detected_at": detected_at_iso, "detail": detail,
    }).execute()
    logger.warning(log_msg, site_id)


def check_incomplete_charging(
    anomalies_table,
    *,
    site_id: str,
    system_type: str,
    energy_daily_rows: list[dict],
    now_utc: datetime | None = None,
) -> None:
    """One site's incomplete-charging check (3d), meant to run once daily
    alongside `anomaly_drift.py`'s two checks — see the module docstring.
    `anomalies_table` is a Supabase `postgrest-py` table handle already
    scoped to `vrm.site_anomalies`, same calling convention as
    `anomaly_silence.check_unexpected_silence()`/`anomaly_drift.py`'s own
    two checks. `energy_daily_rows` is this site's own recent
    `vrm.energy_daily` rows (`{"date", "battery_reached_float",
    "complete_day"}` shape, extra keys ignored).

    `grid_zero` (no battery) is out of scope entirely — fail closed, no
    state change, same reasoning `vrm.compute_daily_health()`'s own
    `v_has_battery` gate uses for the identical signal."""
    now_utc = now_utc or datetime.now(timezone.utc)
    open_rows = (
        anomalies_table.select("id,detail")
        .eq("site_id", site_id).eq("anomaly_type", INCOMPLETE_CHARGING_TYPE)
        .is_("cleared_at", "null").limit(1).execute().data
    )
    open_row = open_rows[0] if open_rows else None

    if system_type not in ("off_grid", "hybrid"):
        return  # no battery -- out of scope, fail closed, no state change

    today = now_utc.date()
    window_cutoff = today - timedelta(days=_WINDOW_DAYS)
    valid = [
        r for r in _valid_daily_rows(energy_daily_rows)
        if window_cutoff <= _parse_date(r["date"]) < today
    ]
    if len(valid) < _MIN_VALID_DAYS:
        return  # fail closed -- not enough real coverage in this short window

    incomplete_days = [r for r in valid if r["battery_reached_float"] is False]

    if len(incomplete_days) < _INCOMPLETE_DAYS_REQUIRED:
        # A real, freshly-computed "no" -- clears an open anomaly (unlike
        # the fail-closed branches above, which never touch state), same
        # distinction anomaly_drift.py's own module docstring draws.
        _clear_open(anomalies_table, open_row, now_utc, site_id=site_id,
                   log_msg="anomaly_battery: cleared incomplete_charging for site %s")
        return

    detail = {
        "incomplete_days": len(incomplete_days),
        "valid_days_checked": len(valid),
        "window_days": _WINDOW_DAYS,
        "incomplete_days_required": _INCOMPLETE_DAYS_REQUIRED,
        "last_checked_at": now_utc.isoformat(),
    }
    _open_or_update(anomalies_table, open_row, site_id=site_id, anomaly_type=INCOMPLETE_CHARGING_TYPE,
                    detected_at_iso=now_utc.isoformat(), detail=detail,
                    log_msg="anomaly_battery: OPENED incomplete_charging for site %s")
