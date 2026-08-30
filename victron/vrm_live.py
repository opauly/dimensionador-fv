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

── The `PVP` multi-charger trap (found live, 2026-08-30 — NOT the same
   number `vrm_series.py`'s own per-charger yield gap describes, but the
   same underlying cause) ────────────────────────────────────────────────
`get_diagnostics()` can list `PVP` at MORE THAN ONE instance (two separate
physical solar-charger devices, confirmed on 844478). Victron's `stats`
endpoint has no documented way to request a specific instance for an
ambiguous code like this — `vrm_series.py`'s own module docstring already
established this exact limitation for `YT` ("Yield today") and chose NULL
over a guessed sum. A live probe here (5 real days of data) found `PVP`
returning real, plausible-looking non-zero values even with two `PVP`
instances present — but with no independent number to cross-check it
against, there is no way to confirm from this endpoint alone whether that
is the true site total or just one charger's share wearing the total's
name. Rather than ship a number that might silently understate real PV
production, `pv_power_w` is populated ONLY when exactly one `PVP` instance
exists; a site with more than one is left `None`, same discipline as
`pv_yield_kwh_sc0`/`sc1`/`mppt` on the daily-report path.

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
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from victron.vrm_series import DEFAULT_TZ_NAME, _available_codes, _series_to_pandas

logger = logging.getLogger("victron.vrm_live")

PV_POWER_CODE = "PVP"
LOAD_CODES = ("a1", "a2")
BATTERY_POWER_CODE = "bp"
SOC_CODE = "SOC"
GRID_POWER_CODES = ("g1", "g2", "g3")
INVERTER_STATE_CODE = "S"
ACTIVE_INPUT_CODE = "AI"

# How far back to look for "the most recent sample" — wide enough to
# tolerate a site that hasn't reported in a little while (still worth
# showing its last known reading, with `captured_at` telling the reader how
# stale it is) without pulling a large, mostly-irrelevant window.
_LOOKBACK_HOURS = 3


class VrmLiveError(ValueError):
    """The API returned nothing usable for a live snapshot."""


def _pv_power_instance_count(diagnostics: dict) -> int:
    records = diagnostics.get("records", diagnostics) if isinstance(diagnostics, dict) else diagnostics
    if not isinstance(records, list):
        return 0
    instances = {r.get("instance") for r in records
                if isinstance(r, dict) and r.get("code") == PV_POWER_CODE}
    return len(instances)


def _latest(series: pd.Series) -> float | None:
    clean = series.dropna()
    return float(clean.iloc[-1]) if not clean.empty else None


def _latest_ts(series: pd.Series):
    clean = series.dropna()
    return clean.index[-1] if not clean.empty else None


def fetch_live_snapshot(client, id_site, site_id: str, *, tz: str = DEFAULT_TZ_NAME) -> dict | None:
    """One site's most recent reading, or `None` if this installation has
    published nothing usable at all (never raises for that case — a single
    unresponsive site must not stop a fleet-wide refresh; the caller logs
    and moves on, same posture `vrm_sync.py:post_run_due()`'s per-site
    isolation already takes).

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

    try:
        diagnostics = client.get_diagnostics(id_site)
    except Exception:  # noqa: BLE001 — one site's failure must not raise
        # past this function; the caller's per-site loop is what isolates it.
        logger.warning("vrm_live: get_diagnostics failed for installation %s (site %s)", id_site, site_id)
        return None
    available = _available_codes(diagnostics)
    if not available:
        return None

    pv_instances = _pv_power_instance_count(diagnostics)
    requested = set()
    if pv_instances == 1:
        requested.add(PV_POWER_CODE)
    for code in LOAD_CODES:
        if code in available:
            requested.add(code)
    if BATTERY_POWER_CODE in available:
        requested.add(BATTERY_POWER_CODE)
    if SOC_CODE in available:
        requested.add(SOC_CODE)
    for code in GRID_POWER_CODES:
        if code in available:
            requested.add(code)
    if INVERTER_STATE_CODE in available:
        requested.add(INVERTER_STATE_CODE)
    if ACTIVE_INPUT_CODE in available:
        requested.add(ACTIVE_INPUT_CODE)

    if not requested:
        return None

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

    series_by_code: dict[str, pd.Series] = {}
    for code in requested:
        series_by_code[code] = _series_to_pandas(
            records.get(code, False) if isinstance(records, dict) else False, zone
        )

    load_parts = [series_by_code[c] for c in LOAD_CODES if c in series_by_code and not series_by_code[c].empty]
    load_power_w = None
    if load_parts:
        combined = pd.concat(load_parts, axis=1).sum(axis=1, min_count=1)
        load_power_w = _latest(combined)

    grid_parts = [series_by_code[c] for c in GRID_POWER_CODES if c in series_by_code and not series_by_code[c].empty]
    grid_power_w = None
    if grid_parts:
        combined = pd.concat(grid_parts, axis=1).sum(axis=1, min_count=1)
        grid_power_w = _latest(combined)

    pv_power_w = (_latest(series_by_code[PV_POWER_CODE])
                 if PV_POWER_CODE in series_by_code else None)

    # `captured_at` — the most recent timestamp among whatever series
    # actually had data, so a site with a slow SOC feed but fresh power
    # data (or vice versa) still gets an honest "as of" time rather than
    # `None` because one particular series happened to be sparse.
    latest_timestamps = [ts for s in series_by_code.values() if (ts := _latest_ts(s)) is not None]
    if not latest_timestamps:
        return None
    # `_series_to_pandas()` always returns tz-NAIVE local timestamps (its
    # own docstring) — localize before converting to UTC for storage.
    captured_at = max(latest_timestamps).tz_localize(zone)

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
        "raw": {code: (round(v, 3) if (v := _latest(s)) is not None else None)
               for code, s in series_by_code.items()},
    }
