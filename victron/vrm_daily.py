from __future__ import annotations
"""
Format-independent daily-summary core, shared by every Victron ingestion path.

Extracted from `victron/vrm_csv.py` (PLAN_PHASE15.md §4.1/§4.2) without any
behaviour change: everything here operates on the *tidied* frame's canonical
columns (`pv_w`, `load_w`, `grid_import_w`, `grid_v_l1`, `soc_pct`, `batt_v`,
`batt_temp_c`, ...) or on an already-extracted boolean/series input, never on
a CSV column name. `vrm_csv.py` — the export-file mapper — is this module's
first caller, and keeps its own public signatures unchanged, delegating into
the functions below. A future cloud-API mapper (`vrm_series.py`, not built by
this step) is the second caller; it will build the same canonical columns
from Victron VRM cloud time series instead of a CSV export, then reuse this
module's outage detector, integrator, and daily-row builder as-is.

Three traps this module exists to keep fixed in one place rather than
re-learned per ingestion path (see `vrm_csv.py`'s own docstring for the full
story of how each was found):

1. **Outages are AC-input voltage absence, not inverter state and not
   `Grid alarm`.** See `_grid_outages()`.
2. **An all-NaN sample must let the previous state persist, not reset it.**
   See `_grid_outages()`.
3. **A day's fine-grained sample spacing is real, not assumed** — `integrate()`
   and `_grid_outages()` both derive elapsed time from the index itself, and
   both refuse to integrate/count across a gap wider than `max_gap_s`.

`max_gap_s` is deliberately never given a module-level default here (contrast
`vrm_csv.MAX_GAP_S = 300`, which is that path's own choice). Every function
below that needs it takes it as an explicit, required argument. This is not
stylistic: `integrate()`'s existing 300s default was tuned for the CSV path's
~1-minute sampling. Reusing that default unexamined against a `15mins`-interval
API series (900s between samples) would treat *every single gap* as "too
large to integrate" and silently return ~0 kWh for every day — see
PLAN_PHASE15.md §4.3. Requiring the caller to pass `max_gap_s` explicitly is
what forces that decision to be made deliberately, per ingestion path.
"""
import numpy as np
import pandas as pd
from datetime import date

# AC-input voltage above this means the grid (or a running genset) is present.
# Well below any nominal supply, well above the 0.00 V a disconnected input
# reads. A brownout deep enough for the inverter to drop the input still counts
# as an outage — that is what the customer experiences.
_GRID_PRESENT_V = 30.0
# A site whose AC input is essentially never energised is off-grid, or
# genset-only: absence is its normal state, not an outage.
_GRID_SITE_MIN_V = 50.0
_GRID_SITE_MIN_SHARE = 0.05
# Sub-2-minute dropouts are recloser operations, not outages worth reporting.
_MIN_OUTAGE_MIN = 2.0

# Battery temperatures outside this band are treated as sensor dropouts rather
# than measurements. The reference export reports a 3 °C minimum at a site in
# Atenas, Costa Rica, which is not a real battery temperature.
_PLAUSIBLE_BATT_TEMP_C = (5.0, 70.0)


def integrate(series: pd.Series, index: pd.DatetimeIndex, max_gap_s: int) -> float:
    """Integrate power [W] to energy [kWh] using real sample spacing.

    `max_gap_s` is required, not defaulted — see the module docstring.
    """
    s = series.reindex(index)
    dt = pd.Series(index.to_series().diff().dt.total_seconds().values, index=index)
    dt = dt.where(dt <= max_gap_s, np.nan)
    return float(np.nansum(s.values * dt.values) / 3_600_000.0)


def _min_max_nonzero(series: pd.Series) -> tuple[float | None, float | None]:
    """Day min/max, excluding zeros.

    Grid voltage and frequency read exactly 0.00 while the grid is
    disconnected. Including those samples makes `min_grid_v_l1` 0 on any day
    the grid dropped even briefly — which is a reading no one would publish,
    and which Node-RED does not produce.
    """
    s = pd.to_numeric(series, errors="coerce").dropna()
    s = s[s > 0]
    if s.empty:
        return None, None
    return float(s.min()), float(s.max())


def _grid_outages(tidied: pd.DataFrame, max_gap_s: int) -> pd.DataFrame:
    """Grid outages from AC-input voltage absence.

    `Grid alarm` is NOT usable for this, despite being the signal Node-RED
    reads. It is flat (`Grid ok`) across every export checked — 9 sites x ~161
    days — including stretches where the AC input sits at 0.00 V for hours
    while the battery carries the load. Read literally it reports zero outages
    forever, which is what the weekly report was showing for sites that in fact
    lose grid 4-12 times a month.

    Voltage absence is the reliable signal, and it cross-validates: sibling
    sites on one feeder (the three Vista Atenas meters; the Rebeca Ruiz
    cluster) show identical outage timestamps to the second, while an event
    local to a single site appears only there.

    Two traps this function exists to avoid, both of which produce
    plausible-looking wrong numbers rather than errors:

    1. **VRM emits an all-NaN row at each exact hour boundary.** Treating "no
       reading" as "grid present" ends the run there, chopping one outage into
       59.9-minute pieces — one 33-hour event became 33 hourly ones. NaN rows
       therefore inherit the previous known state rather than clearing it.
    2. **Duration is summed from real sample spacing, clipped at `max_gap_s`**,
       not taken as end-minus-start. A logging hole inside an outage would
       otherwise be counted as outage time, inflating it without evidence. The
       gap leading into the first absent sample is included, so an outage is
       measured from the last moment the grid was known good.

    Takes the tidied frame (not `raw`): voltage is normalised to numeric there,
    and phase 2 is absent on single-phase sites. `max_gap_s` is required, not
    defaulted — see the module docstring.
    """
    empty = pd.DataFrame(columns=["start", "end", "minutes"])
    if tidied.empty or not {"grid_v_l1", "grid_v_l2"} <= set(tidied.columns):
        return empty

    vmax = tidied[["grid_v_l1", "grid_v_l2"]].max(axis=1)
    logged = vmax.notna()
    if not logged.any():
        return empty

    present = vmax > _GRID_PRESENT_V
    # Off-grid and genset-only sites. Reporting their whole history as one
    # continuous outage would be worse than reporting none.
    if (float(vmax.max()) < _GRID_SITE_MIN_V
            or float(present[logged].mean()) < _GRID_SITE_MIN_SHARE):
        return empty

    # Trap 1: NaN inherits the previous state. bfill covers an export whose
    # first row is one of those hour-boundary NaNs. Carried as float, not
    # bool-with-NaN: masking a bool series yields object dtype, whose ffill
    # pandas deprecates (and which silently downcasts).
    state = (present.astype(float).where(logged)
             .ffill().bfill().fillna(1.0) > 0.5)

    # Trap 2: real elapsed time between samples, not wall-clock span.
    dt = pd.Series(tidied.index, index=tidied.index).diff()
    dt = dt.dt.total_seconds().fillna(0.0).clip(upper=max_gap_s)

    rows = []
    for _, block in tidied.groupby((state != state.shift()).cumsum()):
        if bool(state.loc[block.index[0]]):
            continue  # grid present through this block
        minutes = float(dt.loc[block.index].sum()) / 60.0
        if minutes >= _MIN_OUTAGE_MIN:
            rows.append({"start": block.index[0], "end": block.index[-1],
                         "minutes": round(minutes, 1)})
    return pd.DataFrame(rows, columns=["start", "end", "minutes"])


def alarm_episode_events(active: pd.Series, *, site_id: str, alarm: str,
                         source: str) -> list[dict]:
    """WARNING/CLEARED episode-boundary events from a boolean series.

    This is the format-independent half of what `vrm_csv.py`'s `alarm_events`
    used to do in one function: given a boolean series indexed by timestamp
    (`True` = this alarm category is active at that sample), find where it
    transitions and emit one event per transition. Finding *which columns*
    feed that boolean series is CSV-shaped and stays in `vrm_csv.py`
    (`_category_active`); this state machine is not — it only ever sees a
    boolean series, however it was derived.

    A period that opens already active counts as an episode starting at the
    first sample — otherwise an export/window beginning mid-event silently
    loses it. Callers are expected to sort/merge events from multiple
    categories themselves (as `vrm_csv.alarm_events` does).
    """
    events: list[dict] = []
    if active is None or active.empty:
        return events
    edges = active.astype(int).diff()
    edges.iloc[0] = 1 if bool(active.iloc[0]) else 0
    for ts in active.index[edges == 1]:
        events.append({"site_id": site_id, "alarm": alarm, "severity": "WARNING",
                       "source": source, "timestamp": ts.isoformat()})
    for ts in active.index[edges == -1]:
        events.append({"site_id": site_id, "alarm": alarm, "severity": "CLEARED",
                       "source": source, "timestamp": ts.isoformat()})
    return events


def format_independent_warnings(raw_index: pd.DatetimeIndex, tidied: pd.DataFrame,
                                max_gap_s: int) -> list[str]:
    """The subset of `vrm_csv.validate_export()`'s warnings that only look at
    the tidied frame's canonical columns / the sample index — not at CSV
    column names or `SIGNALS`. `max_gap_s` is required, not defaulted — see
    the module docstring.
    """
    warnings: list[str] = []
    step = raw_index.to_series().diff().dt.total_seconds()
    big_gaps = int((step > max_gap_s).sum())
    if big_gaps:
        warnings.append(
            f"{big_gaps} gap(s) longer than {max_gap_s}s — energy across those "
            "gaps is not integrated, so affected days read low."
        )
    if tidied["grid_w"].notna().sum() == 0:
        warnings.append("No grid power data — grid import will be reported as zero.")
    # Outages are detected from AC-input voltage (see _grid_outages). A site
    # that clearly uses the grid but never reports input voltage would report
    # zero outages with no other sign that detection was impossible — the exact
    # silent failure the voltage rewrite exists to remove.
    if (tidied["grid_w"].notna().sum()
            and int(tidied[["grid_v_l1", "grid_v_l2"]].notna().sum().sum()) == 0):
        warnings.append(
            "No AC input voltage in this export — outages cannot be detected "
            "and will read as zero. Include 'Input voltage phase 1' (VE.Bus "
            "System) in the VRM export to get outage reporting."
        )
    return warnings


def to_energy_daily_rows(tidied: pd.DataFrame, site_id: str, *, max_gap_s: int,
                         dump_type: str = "csv_upload",
                         pv_kwp: float | None = None,
                         battery_usable_kwh: float | None = None,
                         yields: list[pd.Series] | None = None,
                         charge_states: list[pd.Series] | None = None) -> list[dict]:
    """Per-day `energy_daily` rows.

    Every day present in `tidied` is emitted, including partial ones — the
    caller decides what to do with them. `hours_covered` and `complete_day`
    travel alongside so a partial first/last day can be excluded from a report
    without having to re-derive that from the row itself.

    Unlike `vrm_csv.py`'s original version of this function, this one does not
    read a raw CSV frame itself: `yields` and `charge_states` (per-charger
    "Yield today" / "Charge state" series, one per physical device) are passed
    in already extracted, so this function stays format-independent — a future
    API mapper that has no equivalent per-charger series can simply pass
    nothing and get `None`s in those columns, same as an export missing those
    columns does today. `max_gap_s` is required, not defaulted — see the
    module docstring.
    """
    yields = yields or []
    charge_states = charge_states or []

    outages = _grid_outages(tidied, max_gap_s)
    if not outages.empty:
        outages["day"] = outages["start"].dt.date

    rows: list[dict] = []
    for day, g in tidied.groupby(tidied.index.date):
        idx = g.index
        hours = (idx[-1] - idx[0]).total_seconds() / 3600 if len(idx) > 1 else 0.0

        soc = g["soc_pct"].dropna()
        batt_v = g["batt_v"].dropna()
        temp = pd.to_numeric(g["batt_temp_c"], errors="coerce").dropna()
        temp = temp[(temp >= _PLAUSIBLE_BATT_TEMP_C[0]) & (temp <= _PLAUSIBLE_BATT_TEMP_C[1])]

        min_v_l1, max_v_l1 = _min_max_nonzero(g["grid_v_l1"])
        min_v_l2, max_v_l2 = _min_max_nonzero(g["grid_v_l2"])
        min_hz, max_hz = _min_max_nonzero(g["grid_freq"])

        # Per-charger daily yield: each charger's own "Yield today" counter,
        # taken at its maximum for the day (it resets at midnight).
        per_charger: list[float | None] = []
        for y in yields:
            day_y = pd.to_numeric(y.loc[idx], errors="coerce").dropna()
            per_charger.append(round(float(day_y.max()), 3) if not day_y.empty else None)

        max_soc = float(soc.max()) if not soc.empty else None
        reached_float = any(
            (cs.loc[idx].astype(str).str.strip().str.lower() == "float").any()
            for cs in charge_states
        )
        # Matches Node-RED's `Daily Summary`: either the charger actually
        # entered Float, or the pack hit 100%.
        reached_float = bool(reached_float or (max_soc is not None and max_soc >= 100))

        day_outages = (outages[outages["day"] == day]
                       if not outages.empty else pd.DataFrame())

        rows.append({
            "site_id": site_id,
            "date": day.isoformat() if isinstance(day, date) else str(day),
            "dump_type": dump_type,

            "pv_kwh": round(integrate(g["pv_w"], idx, max_gap_s), 2),
            "load_kwh": round(integrate(g["load_w"], idx, max_gap_s), 2),
            "grid_kwh": round(integrate(g["grid_import_w"], idx, max_gap_s), 2),
            "grid_export_kwh": round(integrate(g["grid_export_w"], idx, max_gap_s), 3),
            "battery_charge_kwh": round(integrate(g["batt_charge_w"], idx, max_gap_s), 2),
            "battery_discharge_kwh": round(integrate(g["batt_discharge_w"], idx, max_gap_s), 2),

            "min_soc": round(float(soc.min()), 1) if not soc.empty else None,
            "max_soc": round(max_soc, 1) if max_soc is not None else None,
            "avg_soc": round(float(soc.mean()), 1) if not soc.empty else None,

            "outage_count": int(len(day_outages)),
            "outage_minutes": round(float(day_outages["minutes"].sum()), 1) if len(day_outages) else 0.0,

            "min_voltage": round(float(batt_v.min()), 2) if not batt_v.empty else None,
            "max_voltage": round(float(batt_v.max()), 2) if not batt_v.empty else None,
            "min_temperature": round(float(temp.min()), 1) if not temp.empty else None,
            "max_temperature": round(float(temp.max()), 1) if not temp.empty else None,
            "avg_temperature": round(float(temp.mean()), 1) if not temp.empty else None,

            "min_grid_freq": round(min_hz, 2) if min_hz is not None else None,
            "max_grid_freq": round(max_hz, 2) if max_hz is not None else None,
            "min_grid_v_l1": round(min_v_l1, 1) if min_v_l1 is not None else None,
            "max_grid_v_l1": round(max_v_l1, 1) if max_v_l1 is not None else None,
            "min_grid_v_l2": round(min_v_l2, 1) if min_v_l2 is not None else None,
            "max_grid_v_l2": round(max_v_l2, 1) if max_v_l2 is not None else None,
            # Node-RED's rule: the grid was physically present, which is not
            # the same as the site having imported anything from it.
            "grid_data_available": bool(max_v_l1 is not None and max_v_l1 > 0),

            "pv_yield_kwh_sc0": per_charger[0] if len(per_charger) > 0 else None,
            "pv_yield_kwh_sc1": per_charger[1] if len(per_charger) > 1 else None,
            "pv_yield_kwh_mppt": (round(sum(y for y in per_charger if y), 3)
                                  if any(per_charger) else None),
            "battery_reached_float": reached_float,

            "pv_kwp_snapshot": pv_kwp,
            "battery_kwh_snapshot": battery_usable_kwh,

            # Not columns on energy_daily — carried for the caller's UI/filtering.
            "hours_covered": round(hours, 1),
            "complete_day": hours >= 23.0,
        })
    return rows
