from __future__ import annotations
"""
Live/instantaneous site snapshots — Fleet Dashboard Phase 2 (2026-08-30).

Sibling of `vrm_series.py` (the daily-report mapper): same client, same
`get_diagnostics()`-first discovery discipline, same "no data is better
than fabricated data" rule — but this module answers "what is this site
doing right now," not "what happened this reporting period." Nothing here
writes to `energy_daily`/`daily_health`; the caller
(`vrm_api/routers/vrm_fleet.py:post_refresh_snapshots()`) upserts this
module's output straight into `vrm.site_snapshots` (migration 031).

── Codes, confirmed against a real installation (Vista Atenas LP M3, id
   844478), 2026-08-30, not guessed ───────────────────────────────────────
`PVP` ("PV power"), `a1`/`a2` ("AC Consumption L1"/"L2" — the same
descriptions `vrm_csv.py:SIGNALS`'s `pv_w`/`load_l1_w`/`load_l2_w` already
trust from the CSV path), `bp` ("Battery Power"), `SOC` (already known from
`vrm_series.STATE_CODES`). `g1`/`g2`/`g3` ("Grid L1/L2/L3") exist on SOME
real installations (confirmed on El Encino Casona during Phase 18) but not
this one — best-effort only, `None` when absent, same as every other
optional signal in this pipeline.

── The `PVP` multi-charger trap, and how the LIVE path (this module) gets
   around it (found live, 2026-08-30, fixed 2026-09-01) ───────────────────
`get_diagnostics()` can list `PVP` at MORE THAN ONE instance (two separate
physical solar-charger devices, confirmed on 844478 and, live-checked
2026-09-01, also on 855465/793865/844477). Victron's `stats` endpoint has
no documented way to request a specific instance for an ambiguous code
like this — `vrm_series.py`'s own module docstring already established
this exact limitation for `YT` ("Yield today") and chose NULL over a
guessed sum; `get_stats(attribute_codes=["PVP"])` on a multi-instance site
was confirmed live to return one single, unlabeled series whose values
don't line up with either instance's own reading, so summing or trusting
that series is not possible — that limitation is real and still applies
to `vrm_shape.py`'s hourly history, which has no other source.
`fetch_live_snapshot()` doesn't need history, though — only "right now" —
and `get_diagnostics()`'s own per-instance records already carry a real,
trustworthy `rawValue` (each solar charger's own current output) AND a
`timestamp`, both confirmed live against real production data. Summing
`rawValue` across every `PVP` instance directly from diagnostics, instead
of going through the ambiguous `stats` series at all, gives an honest live
total for a multi-charger site with no guessing involved — this is the one
place in this pipeline where beating `stats`'s own limitation is possible,
because a snapshot only ever needs one instant, not a series.

── `inverter_state_raw`/`active_ac_source_raw` (codes `S`, `AI`) ──────────
Both returned real, live, current values in the same probe (`AI` = a bare
integer, no confirmed enum mapping to "grid"/"generator"/"inverter"
found in Victron's own diagnostics response — `formatWithUnit` says
`'%s'` but the value is numeric). Stored RAW and undecoded — inventing a
label mapping nothing here can verify would be exactly the kind of
fabricated-meaning this pipeline's own conventions exist to avoid (see
`vrm_series.py`'s own tank fluid_type/status precedent, PLAN_PHASE18.md
§7). Decoding these into a human label is real follow-up work, once
Victron's actual enum values are confirmed against known site states.

── Live alarm/critical-alert detection (added 2026-09-01) ─────────────────
`vrm_series.py`'s own historical path only ever sees data through
yesterday (by design — `vrm_api/routers/vrm_sync.py:_do_sync()`'s date
range never includes today), so a transient alarm that starts and clears
within the same day would NEVER show as "active" on the dashboard at any
point — by the time it's synced, it's already resolved history. Found live
2026-09-01 while auditing whether "Active Alarms: 0" fleet-wide could be
trusted. `check_live_alarms()` closes that gap using the exact same
interpretation `vrm_series.py` already uses for its own historical episode
detection (`ALARM_CATEGORIES`/`CRITICAL_ALARM_CATEGORIES`, "any code's raw
value != 0 means this category is active," codes OR'd within a category)
— confirmed live that diagnostics' own `rawValue` is `0` exactly when
`formattedValue` reads "Ok"/"No alarm", the same convention. Reuses the
SAME `get_diagnostics()` call `fetch_live_snapshot()` already makes (pass
it in via that function's own `diagnostics` parameter) rather than costing
a second VRM API call per site per ~15-minute sweep. This function only
READS and reports current state — inserting the resulting WARNING/CLEARED
episode-boundary rows into `vrm.alarm_events`/`vrm.critical_alerts` is the
caller's job (`vrm_api/routers/vrm_fleet.py:post_refresh_snapshots()`),
which also owns comparing against the last known state so a still-ongoing
alarm doesn't get a fresh WARNING row inserted every single sweep.
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from victron.vrm_series import (
    ALARM_CATEGORIES,
    CRITICAL_ALARM_CATEGORIES,
    DEFAULT_TZ_NAME,
    _available_codes,
    _series_to_pandas,
)

logger = logging.getLogger("victron.vrm_live")

PV_POWER_CODE = "PVP"
LOAD_CODES = ("a1", "a2")
BATTERY_POWER_CODE = "bp"
SOC_CODE = "SOC"
# `g1`/`g2`/`g3` — a DEDICATED grid meter (e.g. an ET340), "Grid L1/L2/L3."
# Confirmed present on only some real installations (El Encino Casona,
# Emtec CR, Proyecto gV, live-checked 2026-09-01). `IP1`/`IP2`/`IP3` — the
# inverter/charger's OWN "Input power 1/2/3" measurement at its own AC
# input terminals, present on every real installation checked (single
# instance each, no multi-charger-style ambiguity). These are NOT
# interchangeable: cross-checked live on Emtec CR (the one site with both)
# and they read meaningfully different values at the same instant (-92W vs
# -22W) — they measure at different points in the electrical system, not
# the same thing with a different name. `grid_power_w` prefers the
# dedicated meter when one exists and only falls back to the inverter's own
# reading when it doesn't; `raw["grid_source"]` records which was used so
# the UI can be honest about it instead of implying a meter that isn't
# there.
GRID_POWER_CODES = ("g1", "g2", "g3")
INVERTER_INPUT_CODES = ("IP1", "IP2", "IP3")
INVERTER_STATE_CODE = "S"
ACTIVE_INPUT_CODE = "AI"

# How far back to look for "the most recent sample" — wide enough to
# tolerate a site that hasn't reported in a little while (still worth
# showing its last known reading, with `captured_at` telling the reader how
# stale it is) without pulling a large, mostly-irrelevant window.
_LOOKBACK_HOURS = 3


class VrmLiveError(ValueError):
    """The API returned nothing usable for a live snapshot."""


def _pv_power_from_diagnostics(
    diagnostics: dict,
) -> tuple[float | None, datetime | None, list[dict] | None]:
    """Sum every `PVP` instance's own `rawValue` straight from diagnostics —
    see the module docstring for why this, not `get_stats`, is the one
    place in this pipeline that can safely total a multi-charger site.
    `None`/`None`/`None` when the installation publishes no `PVP` at all (an
    off-grid-battery-only or grid-only site), same "no data" convention as
    every other missing signal here.

    The third element is the per-instance breakdown (each charger's own
    `instance` id and current watts) — stored in `vrm.site_snapshots.raw`
    under `pv_chargers` (that column's own migration comment already
    anticipated "PVP per solar-charger instance"), so a multi-charger site
    can show what each device is contributing, not just the total."""
    records = diagnostics.get("records", diagnostics) if isinstance(diagnostics, dict) else diagnostics
    if not isinstance(records, list):
        return None, None, None
    pv_records = [r for r in records if isinstance(r, dict) and r.get("code") == PV_POWER_CODE
                 and isinstance(r.get("rawValue"), (int, float))]
    if not pv_records:
        return None, None, None
    total = sum(r["rawValue"] for r in pv_records)
    timestamps = [r["timestamp"] for r in pv_records if isinstance(r.get("timestamp"), (int, float))]
    latest = (datetime.fromtimestamp(max(timestamps), tz=timezone.utc)
             if timestamps else None)
    by_instance = sorted(
        ({"instance": r.get("instance"), "power_w": round(float(r["rawValue"]), 1)}
         for r in pv_records),
        key=lambda d: (d["instance"] is None, d["instance"]),
    )
    return float(total), latest, by_instance


def check_live_alarms(diagnostics: dict) -> dict[str, dict]:
    """Current instantaneous state of every scored alarm/critical-alert
    category, straight from diagnostics' own `rawValue` — see the module
    docstring's "Live alarm/critical-alert detection" section for why this
    exists and the interpretation it reuses from `vrm_series.py`.

    Returns `{category_key: {"label": str, "table": "alarm_events" |
    "critical_alerts", "active": bool}}` — only for categories this
    installation actually publishes at least one relevant code for; a
    category with no codes present on this hardware is simply absent from
    the result, never a fabricated `False` (same "no data over fabricated
    data" rule as everywhere else in this module)."""
    records = diagnostics.get("records", diagnostics) if isinstance(diagnostics, dict) else diagnostics
    if not isinstance(records, list):
        return {}
    raw_by_code = {r["code"]: r.get("rawValue") for r in records
                  if isinstance(r, dict) and r.get("code")}

    result: dict[str, dict] = {}
    for source, (label, codes) in ALARM_CATEGORIES.items():
        present = [c for c in codes if c in raw_by_code]
        if not present:
            continue
        active = any((raw_by_code[c] or 0) != 0 for c in present)
        result[source] = {"label": label, "table": "alarm_events", "active": active}
    for category, (label, codes) in CRITICAL_ALARM_CATEGORIES.items():
        present = [c for c in codes if c in raw_by_code]
        if not present:
            continue
        active = any((raw_by_code[c] or 0) != 0 for c in present)
        result[category] = {"label": label, "table": "critical_alerts", "active": active}
    return result


def fetch_pv_power_series(client, id_site, *, interval: str, start: int, end: int,
                          zone: ZoneInfo) -> pd.Series:
    """A site's total PV power over `[start, end)`, correctly summed across
    every solar-charger instance — the historical counterpart to
    `_pv_power_from_diagnostics()`'s live total. Diagnostics only gives an
    instant reading, so it can't power an hour-by-hour chart; this instead
    uses `get_stats(show_instance=True)` (confirmed live 2026-09-01 against
    Victron's own OpenAPI spec — see `VrmRemoteClient.get_stats()`'s own
    docstring) to get each instance's own real series, timestamp-aligned,
    then sums them the same way `LOAD_CODES`/`GRID_POWER_CODES` already are
    elsewhere in this pipeline. Works identically for a single-instance
    site (one series, "summed" with nothing to add) — callers don't need to
    branch on instance count any more than they do for load/grid.

    Returns an empty `pd.Series` (never raises) on any failure or when the
    installation publishes no `PVP` at all — same "no data over fabricated
    data" posture as every other optional signal here."""
    try:
        body = client.get_stats(id_site, type="custom", interval=interval,
                                start=start, end=end,
                                attribute_codes=[PV_POWER_CODE], show_instance=True)
    except Exception:  # noqa: BLE001 — one site's failure must not raise
        # past this function; callers already isolate per-site failures.
        logger.warning("vrm_live: get_stats(show_instance) failed for installation %s", id_site)
        return pd.Series(dtype=float)

    records = body.get("records") if isinstance(body, dict) else None
    if isinstance(records, dict):
        records = list(records.values())
    if not isinstance(records, list):
        return pd.Series(dtype=float)

    parts = []
    for entry in records:
        if not isinstance(entry, dict):
            continue
        stats = entry.get("stats", entry)
        raw = stats.get(PV_POWER_CODE, False) if isinstance(stats, dict) else False
        series = _series_to_pandas(raw, zone)
        if not series.empty:
            parts.append(series)

    if not parts:
        return pd.Series(dtype=float)
    return pd.concat(parts, axis=1).sum(axis=1, min_count=1)


def _latest(series: pd.Series) -> float | None:
    clean = series.dropna()
    return float(clean.iloc[-1]) if not clean.empty else None


def _latest_ts(series: pd.Series):
    clean = series.dropna()
    return clean.index[-1] if not clean.empty else None


def fetch_live_snapshot(client, id_site, site_id: str, *, tz: str = DEFAULT_TZ_NAME,
                        diagnostics: dict | None = None) -> dict | None:
    """One site's most recent reading, or `None` if this installation has
    published nothing usable at all (never raises for that case — a single
    unresponsive site must not stop a fleet-wide refresh; the caller logs
    and moves on, same posture `vrm_sync.py:post_run_due()`'s per-site
    isolation already takes).

    `diagnostics` — pass an already-fetched `get_diagnostics()` response to
    reuse it (e.g. also feeding `check_live_alarms()` from the same call)
    instead of this function fetching its own; `None` (the default) fetches
    it here exactly as before, so every existing caller/test keeps working
    unchanged.

    Returns a dict shaped exactly like a `vrm.site_snapshots` row (minus
    `site_id`, which the caller already has) — `captured_at` is the actual
    timestamp of the most recent sample found, not "now," so a stale
    reading is honestly stale rather than looking fresh because the job
    happened to run.
    """
    try:
        zone = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(DEFAULT_TZ_NAME)

    if diagnostics is None:
        try:
            diagnostics = client.get_diagnostics(id_site)
        except Exception:  # noqa: BLE001 — one site's failure must not raise
            # past this function; the caller's per-site loop is what isolates it.
            logger.warning("vrm_live: get_diagnostics failed for installation %s (site %s)", id_site, site_id)
            return None
    available = _available_codes(diagnostics)
    if not available:
        return None

    # PV is deliberately NOT requested via get_stats below — see the module
    # docstring for why diagnostics' own per-instance rawValue is the
    # trustworthy source for a live snapshot, unlike the ambiguous single
    # series `stats` returns for a multi-charger site.
    pv_power_w, pv_captured_at, pv_chargers = _pv_power_from_diagnostics(diagnostics)

    # Live alarm/critical-alert state — see check_live_alarms()'s own
    # docstring and this module's "Live alarm/critical-alert detection"
    # section. Deliberately just a snapshot of RIGHT NOW, not an
    # episode/history record — this pipeline's historical sync already
    # owns that (through yesterday, for report/health-score purposes); the
    # live dashboard's own "Active Alarms" is meant to answer nothing more
    # than "is this present in the latest live fetch," full stop.
    live_alarm_states = check_live_alarms(diagnostics)
    live_alarms = {k: v["active"] for k, v in live_alarm_states.items() if v["table"] == "alarm_events"} or None
    live_critical_alerts = {k: v["active"] for k, v in live_alarm_states.items()
                           if v["table"] == "critical_alerts"} or None

    # Prefer a dedicated grid meter; fall back to the inverter's own AC
    # input measurement only when no meter exists — see the module-level
    # constants' own comment for why these aren't just synonyms.
    if any(c in available for c in GRID_POWER_CODES):
        grid_codes, grid_source = GRID_POWER_CODES, "meter"
    elif any(c in available for c in INVERTER_INPUT_CODES):
        grid_codes, grid_source = INVERTER_INPUT_CODES, "inverter"
    else:
        grid_codes, grid_source = (), None

    requested = set()
    for code in LOAD_CODES:
        if code in available:
            requested.add(code)
    if BATTERY_POWER_CODE in available:
        requested.add(BATTERY_POWER_CODE)
    if SOC_CODE in available:
        requested.add(SOC_CODE)
    for code in grid_codes:
        if code in available:
            requested.add(code)
    if INVERTER_STATE_CODE in available:
        requested.add(INVERTER_STATE_CODE)
    if ACTIVE_INPUT_CODE in available:
        requested.add(ACTIVE_INPUT_CODE)

    if not requested and pv_power_w is None:
        return None

    series_by_code: dict[str, pd.Series] = {}
    if requested:
        now = datetime.now(timezone.utc)
        end_s = int(now.timestamp())
        start_s = end_s - _LOOKBACK_HOURS * 3600
        try:
            body = client.get_stats(id_site, type="custom", interval="15mins",
                                    start=start_s, end=end_s, attribute_codes=sorted(requested))
        except Exception:  # noqa: BLE001 — see the get_diagnostics() try/except above
            logger.warning("vrm_live: get_stats failed for installation %s (site %s)", id_site, site_id)
            return None
        records = body.get("records", body) if isinstance(body, dict) else {}
        for code in requested:
            series_by_code[code] = _series_to_pandas(
                records.get(code, False) if isinstance(records, dict) else False, zone
            )

    load_parts = [series_by_code[c] for c in LOAD_CODES if c in series_by_code and not series_by_code[c].empty]
    load_power_w = None
    if load_parts:
        combined = pd.concat(load_parts, axis=1).sum(axis=1, min_count=1)
        load_power_w = _latest(combined)

    # Per-phase breakdown, same idea as pv_chargers above — kept alongside
    # the summed load_power_w rather than replacing it.
    _PHASE_LABELS = {"a1": "L1", "a2": "L2"}
    load_phases = [
        {"phase": _PHASE_LABELS.get(c, c), "power_w": round(v, 1)}
        for c in LOAD_CODES
        if c in series_by_code and (v := _latest(series_by_code[c])) is not None
    ] or None

    grid_parts = [series_by_code[c] for c in grid_codes if c in series_by_code and not series_by_code[c].empty]
    grid_power_w = None
    if grid_parts:
        combined = pd.concat(grid_parts, axis=1).sum(axis=1, min_count=1)
        grid_power_w = _latest(combined)

    # `captured_at` — the most recent timestamp among whatever source
    # actually had data (the get_stats series above, or PV's own
    # diagnostics-sourced timestamp), so a site with a slow SOC feed but
    # fresh power data (or vice versa) still gets an honest "as of" time
    # rather than `None` because one particular series happened to be
    # sparse. `_series_to_pandas()` always returns tz-NAIVE local
    # timestamps (its own docstring) — localize before comparing/storing.
    latest_timestamps = [ts.tz_localize(zone).astimezone(timezone.utc)
                         for s in series_by_code.values() if (ts := _latest_ts(s)) is not None]
    if pv_captured_at is not None:
        latest_timestamps.append(pv_captured_at)
    if not latest_timestamps:
        return None
    captured_at = max(latest_timestamps)

    def _raw_str(code: str) -> str | None:
        v = _latest(series_by_code[code]) if code in series_by_code else None
        return None if v is None else str(v)

    return {
        "captured_at": captured_at.astimezone(timezone.utc).isoformat(),
        "pv_power_w": round(pv_power_w, 1) if pv_power_w is not None else None,
        "load_power_w": round(load_power_w, 1) if load_power_w is not None else None,
        "battery_power_w": (round(_latest(series_by_code[BATTERY_POWER_CODE]), 1)
                            if BATTERY_POWER_CODE in series_by_code and _latest(series_by_code[BATTERY_POWER_CODE]) is not None
                            else None),
        "grid_power_w": round(grid_power_w, 1) if grid_power_w is not None else None,
        "soc_pct": (round(_latest(series_by_code[SOC_CODE]), 1)
                   if SOC_CODE in series_by_code and _latest(series_by_code[SOC_CODE]) is not None
                   else None),
        "inverter_state_raw": _raw_str(INVERTER_STATE_CODE),
        "active_ac_source_raw": _raw_str(ACTIVE_INPUT_CODE),
        "raw": {
            **{code: (round(v, 3) if (v := _latest(s)) is not None else None)
              for code, s in series_by_code.items()},
            PV_POWER_CODE: round(pv_power_w, 3) if pv_power_w is not None else None,
            # Per-charger breakdown (only meaningful/present on a
            # multi-instance site) — see _pv_power_from_diagnostics()'s own
            # docstring. `None` when the site has no PVP at all, same as
            # every other missing signal here.
            "pv_chargers": pv_chargers,
            # Per-phase load breakdown — same idea as pv_chargers, always
            # present when load_power_w is (both come from the same a1/a2
            # series), `None` only when this site publishes no AC
            # consumption signal at all.
            "load_phases": load_phases,
            # Live alarm/critical-alert state, RIGHT NOW — {category_key:
            # bool}, `None` when this installation publishes no relevant
            # codes at all. Not an episode/history record; see this
            # function's own comment above for why.
            "alarms": live_alarms,
            "critical_alerts": live_critical_alerts,
            # Which signal grid_power_w came from — "meter" (a dedicated
            # grid meter), "inverter" (the inverter/charger's own AC input
            # measurement, used only when no meter exists), or `None` (no
            # grid signal published at all). See the module-level constants'
            # own comment for why these two sources are not interchangeable.
            "grid_source": grid_source,
        },
    }
