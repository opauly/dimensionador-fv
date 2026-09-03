from __future__ import annotations
"""
Fleet Dashboard Phase 3b — "unexpected silence" anomaly detection
(2026-09-03, PLAN_PHASE19_FLEET_P3.md §3).

Sibling of `vrm_live.py`'s `check_live_alarms()`: called from the SAME
~15-minute snapshot-refresh sweep (`vrm_api/routers/vrm_fleet.py:
post_refresh_snapshots()`), right after each site's `vrm.site_snapshots`
row is upserted, reusing data that sweep already fetched — zero extra VRM
API cost, same reasoning `bf9a142`'s live alarm-detection work already
established. Writes/clears `vrm.site_anomalies` (migration 038,
anomaly_type='unexpected_silence') — a deliberately separate signal from
`vrm.daily_health`/`vrm.compute_daily_health()` (PLAN_PHASE19_FLEET_P3.md
§1); nothing here touches that table or its trigger.

── What counts as "silent" ─────────────────────────────────────────────────
Only a real `0.0` on `pv_power_w` counts. `pv_power_w IS NULL` (a site that
simply doesn't publish PVP, or — per `vrm_live.py`'s own docstring — a
multi-charger site whose per-instance readings are all summed into a real
number these days, but could still legitimately be `None` if a site
publishes no `PVP` diagnostics record at all) is excluded entirely: `None`
is "can't tell," never treated as a silence signal, and immediately clears
any anomaly already open (see `_is_real_zero()`/the top of
`check_unexpected_silence()` below).

── Debounce ─────────────────────────────────────────────────────────────────
Flags only once TWO consecutive ~15-minute checks both read a real zero
during the site's own productive window (~30 min sustained,
PLAN_PHASE19_FLEET_P3.md §3's own number — a starting point, not locked,
see §7 item 1). This module has no long-lived process state of its own
(the sweep is a stateless, ~15-minutely `POST`) — the "previous check"'s
own reading is instead read straight from `vrm.site_snapshots` BEFORE the
caller overwrites it with the new one (the row already holds exactly one
prior reading, `captured_at` included, for free). A previous reading only
counts as "the immediately preceding check" if it is no more than
`_DEBOUNCE_MAX_GAP_MINUTES` old — wide enough to tolerate the sweep running
a few minutes late, narrow enough that a zero from hours or days ago is
never mistaken for "consecutive."

── "Should be producing" window — an explicit judgment call, flag for
   Oscar ───────────────────────────────────────────────────────────────────
The plan doc's own §3 asks for this window to be "derive[d] per-site from
its own `energy_daily` history (has this site historically had non-trivial
generation at this local hour on recent days?)." That is not literally
computable from what `vrm.energy_daily` actually stores: it is a DAILY-grain
table (`pv_kwh` per calendar day — confirmed via migration 012's own
column list; there is no intraday/hourly history stored ANYWHERE in this
schema, and no sunrise/sunset-calculation library is used anywhere in this
codebase either). A single daily total cannot, by itself, say whether a
site produces at 7am vs. 1pm.

What IS genuinely derivable from `vrm.energy_daily`, and is what this module
actually does: whether this site has a real, RECENT history of non-trivial
daily production at all (`_site_productive_window()` below — at least
`_MIN_VALID_HISTORY_DAYS` valid days in the last `_LOOKBACK_DAYS`, with at
least `_PRODUCTIVE_DAY_FRACTION_MIN` of them clearing `_PRODUCTION_FLOOR_KWH`
kWh). That gate is real, per-site, and history-derived, and it is what keeps
this check from ever flagging a site that is chronically idle (under
long-term maintenance, decommissioned, etc.) — for a site like that, a zero
is its normal state, not "unexpected."

The literal HOUR-of-day component, which `energy_daily` genuinely cannot
supply, falls back to a fixed, deliberately narrow "core midday" local-clock
band (`_WINDOW_LOCAL_START_HOUR`-`_WINDOW_LOCAL_END_HOUR`, converted through
each site's own `timezone` column, which is a real per-site value even
though every current site happens to share `America/Costa_Rica`). Chosen
narrow ON PURPOSE, per §7 item 1's own "start conservative" guidance: a
window this far from sunrise/sunset survives a shaded or unusually-oriented
array's real, narrower productive hours (the exact failure mode the plan
doc explicitly worried a generic clear-sky window would hit) at the cost of
not catching a silence that happens only at the very edges of the day.
Building a genuine per-site, per-hour empirical window would need this
pipeline to start accumulating intraday history somewhere — real, valuable
follow-up work, but a new capability, not something achievable by reading a
daily total differently. Flagged for Oscar rather than silently resolved;
see this build's own report.

Once an anomaly is OPEN, this window is not re-checked on every following
read — a site that started a genuine silence at 10am and is still silent at
4pm should stay flagged, even though 4pm falls outside the conservative
detection window above (see `check_unexpected_silence()`'s own "already
open" branch). The window only gates whether a NEW anomaly gets opened.
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from victron.vrm_series import DEFAULT_TZ_NAME

logger = logging.getLogger("victron.anomaly_silence")

ANOMALY_TYPE = "unexpected_silence"

# See "Debounce" above.
_DEBOUNCE_MAX_GAP_MINUTES = 25

# See "Should be producing window" above — a conservative, narrower-than-
# sunrise-to-sunset core midday band, local time, per the site's own
# `timezone` column.
_WINDOW_LOCAL_START_HOUR = 8
_WINDOW_LOCAL_END_HOUR = 16

# How much `vrm.energy_daily` history to look at, and how much of it must be
# valid/productive for this site to be considered a genuine, currently-
# active producer worth checking at all. Fails closed (no window, no flag)
# on insufficient history — same posture PLAN_PHASE19_FLEET_P3.md §6 states
# for 3a/3c ("<30 valid days produces no flag, not a guessed one"); 3b uses
# a lower bar (`_MIN_VALID_HISTORY_DAYS`, not 30) since its own window
# derivation needs far less signal than 3a/3c's trend math does, but the
# same "no data over fabricated data" rule applies.
_LOOKBACK_DAYS = 30
_MIN_VALID_HISTORY_DAYS = 5
_PRODUCTION_FLOOR_KWH = 0.3
_PRODUCTIVE_DAY_FRACTION_MIN = 0.5


def _is_real_zero(pv_power_w: float | None) -> bool:
    """`0.0` and nothing else — see the module docstring's "What counts as
    'silent'" section. `None` (NULL) is deliberately NOT a zero."""
    return pv_power_w is not None and float(pv_power_w) == 0.0


def _parse_dt(value) -> datetime | None:
    """Best-effort parse of a timestamp that may already be a `datetime`
    (tz-aware or naive -- naive is assumed UTC, matching every other
    timestamp this pipeline stores) or a string (as PostgREST/Supabase
    returns it). `None` for anything unusable -- never raises, the same
    "one bad field must not break the whole check" posture the rest of this
    pipeline's live-data code takes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _to_iso(value) -> str | None:
    dt = _parse_dt(value)
    return dt.isoformat() if dt else None


def _site_productive_window(energy_daily_rows: list[dict]) -> dict | None:
    """The real-history half of the "should be producing" gate -- see the
    module docstring. `energy_daily_rows` is this one site's own
    `vrm.energy_daily` rows over the last `_LOOKBACK_DAYS` (any shape with
    `pv_kwh`/`complete_day` keys; extra keys ignored). Returns `None` (fail
    closed, no window, this site is never eligible to be flagged right now)
    when there isn't enough valid history or this site isn't a genuine
    recent producer at all -- both real, deliberate "no data over fabricated
    data" outcomes, not bugs."""
    valid = [r for r in energy_daily_rows
             if r.get("pv_kwh") is not None and r.get("complete_day") is not False]
    if len(valid) < _MIN_VALID_HISTORY_DAYS:
        return None
    productive_days = [r for r in valid if float(r["pv_kwh"] or 0) > _PRODUCTION_FLOOR_KWH]
    if len(productive_days) / len(valid) < _PRODUCTIVE_DAY_FRACTION_MIN:
        return None
    return {
        "start_hour": _WINDOW_LOCAL_START_HOUR,
        "end_hour": _WINDOW_LOCAL_END_HOUR,
        "valid_days": len(valid),
        "productive_days": len(productive_days),
    }


def _is_within_window(now_local: datetime, window: dict) -> bool:
    return window["start_hour"] <= now_local.hour < window["end_hour"]


def _build_detail(silent_since_iso: str | None, now_utc: datetime, checks_confirmed: int,
                  window: dict | None = None) -> dict:
    """Whatever's useful for the dashboard to show (PLAN_PHASE19_FLEET_P3.md
    §3's own phrasing) -- how long it's been silent, what the expected
    window is, and (only on the detection that actually opened the row) how
    much real history that determination was based on."""
    silent_since = _parse_dt(silent_since_iso)
    minutes_silent = round((now_utc - silent_since).total_seconds() / 60, 1) if silent_since else None
    detail: dict = {
        "silent_since": silent_since_iso,
        "last_checked_at": now_utc.isoformat(),
        "minutes_silent": minutes_silent,
        "checks_confirmed": checks_confirmed,
        "expected_window_local": f"{_WINDOW_LOCAL_START_HOUR:02d}:00-{_WINDOW_LOCAL_END_HOUR:02d}:00",
    }
    if window is not None:
        detail["window_basis_valid_days"] = window["valid_days"]
        detail["window_basis_productive_days"] = window["productive_days"]
    return detail


def check_unexpected_silence(
    anomalies_table,
    *,
    site_id: str,
    tz_name: str | None,
    new_pv_power_w: float | None,
    new_captured_at,
    previous_pv_power_w: float | None,
    previous_captured_at,
    energy_daily_rows: list[dict],
    now_utc: datetime | None = None,
) -> None:
    """One site's unexpected-silence check, for one ~15-minute sweep.

    `anomalies_table` — a Supabase `postgrest-py` table handle already
    scoped to `vrm.site_anomalies` (i.e. `client.schema("vrm").table(
    "site_anomalies")`) -- passed in rather than a bare client so this
    function stays easy to point at a disposable/fake table in a test
    without needing a real Supabase connection.

    `new_pv_power_w`/`new_captured_at` -- THIS check's own reading, from the
    snapshot the caller just fetched (same values about to be upserted into
    `vrm.site_snapshots`).

    `previous_pv_power_w`/`previous_captured_at` -- the PREVIOUS reading, in
    other words whatever `vrm.site_snapshots` held for this site BEFORE this
    sweep's upsert overwrites it. The caller must read this itself, before
    upserting -- see the module docstring's "Debounce" section for why this
    is where the "was the last check also a zero" state actually lives.

    `energy_daily_rows` -- this site's own `vrm.energy_daily` rows over the
    last `_LOOKBACK_DAYS`, `{"pv_kwh": ..., "complete_day": ...}` shape
    (extra keys ignored) -- feeds `_site_productive_window()`.

    Writes at most one row (INSERT to open a new anomaly, or UPDATE to
    either extend an open one's `detail` or set its `cleared_at`) -- never
    raises for a "no anomaly, nothing to do" outcome, and any Supabase
    error propagates to the caller exactly like every other per-site step in
    `post_refresh_snapshots()`'s own loop (that loop's existing
    per-site try/except already isolates one site's failure from the rest of
    the sweep; this function does not need its own).
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    try:
        zone = ZoneInfo(tz_name) if tz_name else ZoneInfo(DEFAULT_TZ_NAME)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(DEFAULT_TZ_NAME)

    open_rows = (
        anomalies_table.select("id,detected_at,detail")
        .eq("site_id", site_id).eq("anomaly_type", ANOMALY_TYPE)
        .is_("cleared_at", "null").limit(1).execute().data
    )
    open_row = open_rows[0] if open_rows else None

    # NULL or a real non-zero reading -- resolved, or "can't tell" (NULL is
    # never a silence signal, see the module docstring). Either way, clear
    # whatever's open; nothing to do if nothing was open.
    if not _is_real_zero(new_pv_power_w):
        if open_row is not None:
            anomalies_table.update({"cleared_at": now_utc.isoformat()}).eq("id", open_row["id"]).execute()
            logger.info("anomaly_silence: cleared unexpected_silence for site %s (pv_power_w=%s)",
                       site_id, new_pv_power_w)
        return

    # A real zero from here on.
    if open_row is not None:
        # Already flagged -- stays open regardless of the window (see the
        # module docstring's last paragraph); just extend detail.
        detail = dict(open_row.get("detail") or {})
        silent_since = detail.get("silent_since") or _to_iso(previous_captured_at) or _to_iso(new_captured_at)
        detail.update(_build_detail(silent_since, now_utc, int(detail.get("checks_confirmed") or 1) + 1))
        anomalies_table.update({"detail": detail}).eq("id", open_row["id"]).execute()
        return

    # No open anomaly -- decide whether THIS reading is the confirming
    # (2nd consecutive) zero. See the module docstring's "Debounce" section.
    if not _is_real_zero(previous_pv_power_w):
        return  # first zero seen this round -- wait for the next check
    prev_dt = _parse_dt(previous_captured_at)
    if prev_dt is None or (now_utc - prev_dt) > timedelta(minutes=_DEBOUNCE_MAX_GAP_MINUTES):
        return  # too stale to count as "the immediately preceding check"

    window = _site_productive_window(energy_daily_rows)
    if window is None:
        return  # insufficient/non-productive history -- fail closed
    now_local = now_utc.astimezone(zone)
    if not _is_within_window(now_local, window):
        return  # outside this site's own established productive hours

    detected_at_iso = prev_dt.isoformat()
    detail = _build_detail(detected_at_iso, now_utc, 2, window=window)
    anomalies_table.insert({
        "site_id": site_id, "anomaly_type": ANOMALY_TYPE,
        "detected_at": detected_at_iso, "detail": detail,
    }).execute()
    logger.warning("anomaly_silence: OPENED unexpected_silence for site %s (silent since %s)",
                   site_id, detected_at_iso)
