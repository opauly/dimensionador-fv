from __future__ import annotations
"""
Victron VRM CSV export → `energy_daily` / `alarm_events` rows.

Second ingestion path for the weekly monitoring report. The first path is
Node-RED on a Cerbo GX writing `monitoring.energy_daily` directly; this one
takes a customer's VRM CSV export and produces the same row shape, so the
report reader doesn't care which produced it.

CSV reading (`load_vrm_csv`, `tidy`, `integrate`) is adapted from the
`reporte-solar-vrm` skill's `vrm_parse.py`, which is field-proven against real
exports. What's new here is `to_energy_daily_rows()` — the mapping onto
`energy_daily`'s columns, and the per-day fields the skill's own report never
needed (grid quality, battery voltage/temperature extremes, per-charger yield).

Every mapping rule below was verified against a real 80-day export
(`vista-atenas-lp-m3`, 2026-05-10..07-28) compared row-by-row against the same
site's Node-RED-written rows, and against the flow's own logic in
`victron-monitor/node-red/victron_monitor_v1p8.json`. Full findings and the
agreement table: `victron-monitor/docs/vrm-report-v1-implementation-plan.md` §7.

Three traps that this module exists to avoid, all of which produce
plausible-looking wrong numbers rather than errors:

1. **Outages are `Grid alarm` transitions, not inverter state.** The skill's
   `find_outages()` flags "system is inverting" as an island event. At an ESS
   site that is normal self-consumption — on the reference export it flagged
   95% of the period (49 events, 111,258 minutes) where Node-RED correctly
   reported zero. See `_grid_outages()`.
2. **`Grid alarm` is text in the CSV** (`Grid ok` / `Grid lost`), while
   Node-RED reads the numeric D-Bus value. `pd.to_numeric()` on it yields an
   all-NaN series, i.e. silently "no outages ever".
3. **Duplicate column names are real data, not noise.** A site with two solar
   chargers repeats all 48 `Solar Charger::` names. Selecting by name returns
   only the first, so per-charger yield silently halves. See `_pick_all()`.
"""
import io
import re
from datetime import date

import numpy as np
import pandas as pd

# Gaps longer than this are not integrated — a logging outage must not be
# treated as the last-known power level persisting across the whole hole.
MAX_GAP_S = 300

# Canonical signal → (aggregation, [candidate ("Device", "Description") pairs]).
#
# Candidates are tried in order; the first one present wins. A VRM export only
# contains the columns the user ticked in the portal, and column availability
# varies by hardware, so each signal needs alternatives rather than one exact
# name. Verified against two real exports with different column sets (264 vs
# 164 columns).
#
# The aggregation matters as much as the candidate list. A site can have several
# of the same device — two solar chargers is common, and both export under the
# identical column name. For *power* that must be summed, or a two-charger site
# silently reports half its generation. For a *state* reading (SOC, voltage,
# temperature) summing would be nonsense, so the first device is used.
#   "sum"   — additive across devices
#   "first" — one representative device
SUM, FIRST = "sum", "first"

SIGNALS = {
    "pv_w":        (SUM,   [("System overview", "PV - DC-coupled"),
                            ("System overview", "PV - AC-coupled"),
                            ("Solar Charger", "PV power")]),
    "load_l1_w":   (SUM,   [("System overview", "AC Consumption L1"),
                            ("VE.Bus System", "Output power 1")]),
    "load_l2_w":   (SUM,   [("System overview", "AC Consumption L2"),
                            ("VE.Bus System", "Output power 2")]),
    "load_l3_w":   (SUM,   [("System overview", "AC Consumption L3"),
                            ("VE.Bus System", "Output power 3")]),
    "grid_l1_w":   (SUM,   [("System overview", "Grid L1"),
                            ("Grid meter", "Grid L1 - Power")]),
    "grid_l2_w":   (SUM,   [("System overview", "Grid L2"),
                            ("Grid meter", "Grid L2 - Power")]),
    "grid_l3_w":   (SUM,   [("System overview", "Grid L3"),
                            ("Grid meter", "Grid L3 - Power")]),
    "batt_w":      (SUM,   [("System overview", "Battery Power"),
                            ("Battery Monitor", "Power")]),
    "soc_pct":     (FIRST, [("System overview", "Battery SOC"),
                            ("Battery Monitor", "State of charge")]),
    "batt_v":      (FIRST, [("Battery Monitor", "Voltage"),
                            ("System overview", "Battery Voltage")]),
    "batt_temp_c": (FIRST, [("Battery Monitor", "Battery temperature")]),
    "grid_alarm":  (FIRST, [("System overview", "Grid alarm")]),
    "grid_v_l1":   (FIRST, [("VE.Bus System", "Input voltage phase 1")]),
    "grid_v_l2":   (FIRST, [("VE.Bus System", "Input voltage phase 2")]),
    "grid_freq":   (FIRST, [("VE.Bus System", "Input frequency 1")]),
}

# Without these the file cannot produce a meaningful report, so ingestion is
# refused rather than producing one with zeros in it. `load` is included
# deliberately: a report whose consumption is 0 would still render, and every
# derived figure (grid independence, energy mix, performance) would be wrong.
REQUIRED_SIGNALS = ["pv_w", "batt_w", "soc_pct", "load_w"]

# Per-solar-charger daily yield counters. Duplicated once per charger.
YIELD_TODAY = ("Solar Charger", "Yield today")
CHARGE_STATE = ("Solar Charger", "Charge state")

# Scored alarm categories — deliberately mirroring Node-RED's taxonomy, which
# emits exactly two (`low_battery`, `overload`) with WARNING/CLEARED severity.
#
# The CSV exposes far more alarm columns (DC ripple, temperature, and the whole
# Battery Monitor set — see UNSCORED_ALARM_SIGNALS). Scoring those here would
# make a CSV-ingested site score systematically worse than an identically
# behaving Cerbo site, because `count_alarm_episodes()` counts every event row
# for the day through one shared in-episode flag. Since the point of the
# schema-agnostic reader is that the two paths are comparable, the extra
# signals are surfaced as ingestion warnings instead of scored events.
#
# Widening this is a deliberate, cross-path change: Node-RED would have to emit
# the same categories, or health scores stop meaning the same thing.
ALARM_CATEGORIES = {
    "low_battery": ("Low Battery Alarm", [("VE.Bus System", "Low battery")]),
    "overload": ("Overload Alarm", [("VE.Bus System", "Overload L1"),
                                    ("VE.Bus System", "Overload L2")]),
}

# Detected and reported, never scored. See above.
UNSCORED_ALARM_SIGNALS = [
    ("VE.Bus System", "High DC Ripple"),
    ("VE.Bus System", "Temperature L1"), ("VE.Bus System", "Temperature L2"),
    ("Battery Monitor", "Low voltage alarm"),
    ("Battery Monitor", "High battery temperature alarm"),
    ("Battery Monitor", "Cell Imbalance alarm"),
    ("Battery Monitor", "High charge current alarm"),
    ("Battery Monitor", "High discharge current alarm"),
    ("Battery Monitor", "Internal Failure"),
    ("Battery Monitor", "High cell voltage"),
]

# Values across VRM alarm columns that mean "nothing wrong".
_OK_VALUES = {"ok", "no alarm", "0", "0.0", "nan", "no", "inactive",
              "off", "none", "normal", "grid ok"}

# Battery temperatures outside this band are treated as sensor dropouts rather
# than measurements. The reference export reports a 3 °C minimum at a site in
# Atenas, Costa Rica, which is not a real battery temperature.
_PLAUSIBLE_BATT_TEMP_C = (5.0, 70.0)


class VrmCsvError(ValueError):
    """The uploaded file is not a usable VRM export."""


def installation_id(filename: str) -> str | None:
    """VRM names exports `<id>_<n>_<site>_log_<from>_to_<to>.csv`."""
    m = re.match(r"(\d{4,})_", str(filename).rsplit("/", 1)[-1])
    return m.group(1) if m else None


def load_vrm_csv(source) -> tuple[pd.DataFrame, str]:
    """Read a VRM export into a time-indexed DataFrame.

    The export has a 3-row header: devices, descriptions, units. Column names
    repeat across devices (`Voltage` appears on several), so columns are keyed
    "Device::Description" — still not unique when a site has two of the same
    device, which is deliberate: `_pick_all()` relies on the duplicates.

    `source` may be a path or a file-like object (a Streamlit upload).
    """
    buf = source
    if hasattr(source, "read"):
        raw_bytes = source.read()
        buf = io.BytesIO(raw_bytes)

    head = pd.read_csv(buf, nrows=2, header=None)
    if hasattr(buf, "seek"):
        buf.seek(0)

    devices = [str(x).split(" [")[0].strip() for x in head.iloc[0].tolist()]
    descs = [str(x).strip() for x in head.iloc[1].tolist()]
    names = ["timestamp"] + [f"{devices[i]}::{descs[i]}" for i in range(1, len(descs))]

    df = pd.read_csv(buf, skiprows=[1, 2], low_memory=False)
    if len(df.columns) != len(names):
        raise VrmCsvError(
            f"Header describes {len(names)} columns but the data has "
            f"{len(df.columns)}. This does not look like a VRM export."
        )
    df.columns = names
    try:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    except (ValueError, TypeError) as exc:
        raise VrmCsvError(f"First column is not a parseable timestamp: {exc}") from exc

    df = df.set_index("timestamp").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    timezone_label = str(head.iloc[1, 0])
    return df, timezone_label


def _pick_all(df: pd.DataFrame, device: str, desc: str) -> list[pd.Series]:
    """Every column matching Device::Description, one per physical device.

    Selecting a duplicated name returns a DataFrame; each of its columns is a
    separate device. Returning them all is the whole point — a two-charger site
    otherwise reports half its yield.
    """
    key = f"{device}::{desc}"
    if key not in df.columns:
        return []
    col = df[key]
    if isinstance(col, pd.DataFrame):
        return [col.iloc[:, i] for i in range(col.shape[1])]
    return [col]


def _pick(df: pd.DataFrame, specs: list[tuple[str, str]],
          how: str = FIRST) -> pd.Series | None:
    """First matching candidate, aggregated across devices per `how`.

    `how=SUM` is what makes a multi-device site correct: two solar chargers
    both publish `Solar Charger::PV power`, and taking only the first would
    silently halve generation.
    """
    for device, desc in specs:
        cols = _pick_all(df, device, desc)
        if not cols:
            continue
        if len(cols) == 1 or how == FIRST:
            return cols[0]
        numeric = [pd.to_numeric(c, errors="coerce") for c in cols]
        return pd.concat(numeric, axis=1).sum(axis=1, min_count=1)
    return None


def tidy(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Extract the canonical signals into a clean frame, plus what's missing."""
    out = pd.DataFrame(index=raw.index)
    missing: list[str] = []
    for name, (how, specs) in SIGNALS.items():
        col = _pick(raw, specs, how)
        if col is None:
            missing.append(name)
            out[name] = np.nan
        else:
            out[name] = col

    numeric = ["pv_w", "load_l1_w", "load_l2_w", "load_l3_w",
               "grid_l1_w", "grid_l2_w", "grid_l3_w", "batt_w", "soc_pct",
               "batt_v", "batt_temp_c", "grid_v_l1", "grid_v_l2", "grid_freq"]
    for c in numeric:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    out["load_w"] = out[["load_l1_w", "load_l2_w", "load_l3_w"]].sum(axis=1, min_count=1)
    out["grid_w"] = out[["grid_l1_w", "grid_l2_w", "grid_l3_w"]].sum(axis=1, min_count=1)
    # VRM convention: grid > 0 imports, grid < 0 exports.
    out["grid_import_w"] = out["grid_w"].clip(lower=0)
    out["grid_export_w"] = (-out["grid_w"]).clip(lower=0)
    # VRM convention: battery > 0 charges, battery < 0 discharges.
    out["batt_charge_w"] = out["batt_w"].clip(lower=0)
    out["batt_discharge_w"] = (-out["batt_w"]).clip(lower=0)
    return out, missing


def validate_export(raw: pd.DataFrame, tidied: pd.DataFrame,
                    missing: list[str]) -> list[str]:
    """Reject unusable exports; return non-fatal warnings for the UI.

    Deliberately loud rather than silent: a CSV that parses into a plausible
    but wrong report is the failure mode worth spending effort on.
    """
    # `load_w` is derived from the L1/L2/L3 columns rather than picked directly,
    # so its absence shows up as an all-null series, not as a missing signal.
    derived_missing = [s for s in ("load_w", "grid_w")
                       if s in tidied and tidied[s].notna().sum() == 0]
    blocking = [s for s in REQUIRED_SIGNALS
                if s in missing or s in derived_missing]
    if blocking:
        raise VrmCsvError(
            "Export is missing required signals: " + ", ".join(blocking) +
            ". In the VRM portal, include the System overview (PV, AC "
            "consumption, battery) and Battery Monitor data in the export, "
            "not only a subset of devices."
        )
    if len(raw) < 2:
        raise VrmCsvError("Export contains fewer than two samples.")

    warnings: list[str] = []
    # Phase-3 columns are absent on every split-phase (120/240 V) site, which is
    # most of them — reporting that as a problem trains the operator to ignore
    # warnings.
    notable = [s for s in missing if s not in ("load_l3_w", "grid_l3_w")]
    if notable:
        warnings.append("Signals not found in this export: " + ", ".join(notable))

    step = raw.index.to_series().diff().dt.total_seconds()
    big_gaps = int((step > MAX_GAP_S).sum())
    if big_gaps:
        warnings.append(
            f"{big_gaps} gap(s) longer than {MAX_GAP_S}s — energy across those "
            "gaps is not integrated, so affected days read low."
        )
    if tidied["grid_w"].notna().sum() == 0:
        warnings.append("No grid power data — grid import will be reported as zero.")
    return warnings


def integrate(series: pd.Series, index: pd.DatetimeIndex,
              max_gap_s: int = MAX_GAP_S) -> float:
    """Integrate power [W] to energy [kWh] using real sample spacing."""
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


def _grid_outages(raw: pd.DataFrame) -> pd.DataFrame:
    """Grid outages from `Grid alarm` transitions, matching Node-RED.

    The flow's `Grid Lost` node starts an outage on 0 → ≥1 and ends it on
    ≥1 → 0. The CSV encodes the same signal as text, so state is derived by
    comparing against the known-good values rather than by casting to a number.
    """
    cols = _pick_all(raw, "System overview", "Grid alarm")
    if not cols:
        return pd.DataFrame(columns=["start", "end", "minutes"])

    state = cols[0].dropna()
    if state.empty:
        return pd.DataFrame(columns=["start", "end", "minutes"])

    lost = (~state.astype(str).str.strip().str.lower().isin(_OK_VALUES)).astype(int)
    edges = lost.diff().fillna(0)
    starts = list(lost.index[edges == 1])
    ends = list(lost.index[edges == -1])

    rows = []
    for start in starts:
        later = [e for e in ends if e > start]
        # An outage still open at the end of the export is measured to the last
        # sample rather than dropped — dropping it would under-report a real,
        # ongoing failure.
        end = later[0] if later else lost.index[-1]
        rows.append({"start": start, "end": end,
                     "minutes": round((end - start).total_seconds() / 60.0, 1)})
    return pd.DataFrame(rows, columns=["start", "end", "minutes"])


def _category_active(raw: pd.DataFrame,
                     specs: list[tuple[str, str]]) -> pd.Series | None:
    """Boolean series: is any column in this alarm category non-OK?

    Overload spans L1 and L2; a warning on either is one overload condition,
    not two, so they're OR-ed before edge detection rather than emitted
    separately.
    """
    parts = []
    for device, desc in specs:
        for col in _pick_all(raw, device, desc):
            s = col.dropna()
            if not s.empty:
                parts.append(~s.astype(str).str.strip().str.lower().isin(_OK_VALUES))
    if not parts:
        return None
    combined = pd.concat(parts, axis=1).fillna(False).any(axis=1)
    return combined.sort_index()


def alarm_events(raw: pd.DataFrame, site_id: str) -> list[dict]:
    """`alarm_events`-shaped rows, so the ported `count_alarm_episodes()` SQL
    counts episodes exactly as it does for the Node-RED path.

    Emitting events and reusing the existing SQL keeps one definition of
    "episode" rather than a second one in Python that could drift from it.
    """
    events: list[dict] = []
    for source, (label, specs) in ALARM_CATEGORIES.items():
        active = _category_active(raw, specs)
        if active is None or active.empty:
            continue
        edges = active.astype(int).diff()
        # A period that opens already in alarm counts as an episode starting at
        # the first sample — otherwise an export beginning mid-event silently
        # loses it.
        edges.iloc[0] = 1 if bool(active.iloc[0]) else 0
        for ts in active.index[edges == 1]:
            events.append({"site_id": site_id, "alarm": label, "severity": "WARNING",
                           "source": source, "timestamp": ts.isoformat()})
        for ts in active.index[edges == -1]:
            events.append({"site_id": site_id, "alarm": label, "severity": "CLEARED",
                           "source": source, "timestamp": ts.isoformat()})
    events.sort(key=lambda e: e["timestamp"])
    return events


def unscored_alarm_summary(raw: pd.DataFrame) -> dict[str, int]:
    """Non-OK sample counts for alarm signals that exist but aren't scored.

    Reported so a real fault (cell imbalance, internal failure) is visible in
    the ingestion log even though it deliberately doesn't move the health
    score. Silently discarding these would be worse than not reading them.
    """
    summary: dict[str, int] = {}
    for device, desc in UNSCORED_ALARM_SIGNALS:
        for col in _pick_all(raw, device, desc):
            s = col.dropna()
            if s.empty:
                continue
            n = int((~s.astype(str).str.strip().str.lower().isin(_OK_VALUES)).sum())
            if n:
                summary[f"{device}::{desc}"] = summary.get(f"{device}::{desc}", 0) + n
    return summary


def to_energy_daily_rows(raw: pd.DataFrame, tidied: pd.DataFrame, site_id: str,
                         dump_type: str = "csv_upload",
                         pv_kwp: float | None = None,
                         battery_usable_kwh: float | None = None) -> list[dict]:
    """Per-day `energy_daily` rows.

    Every day present in the export is emitted, including partial ones — the
    caller decides what to do with them. `hours_covered` and `complete_day`
    travel alongside so a partial first/last day can be excluded from a report
    without having to re-derive that from the row itself.
    """
    outages = _grid_outages(raw)
    if not outages.empty:
        outages["day"] = outages["start"].dt.date
    yields = _pick_all(raw, *YIELD_TODAY)
    charge_states = _pick_all(raw, *CHARGE_STATE)

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

            "pv_kwh": round(integrate(g["pv_w"], idx), 2),
            "load_kwh": round(integrate(g["load_w"], idx), 2),
            "grid_kwh": round(integrate(g["grid_import_w"], idx), 2),
            "grid_export_kwh": round(integrate(g["grid_export_w"], idx), 3),
            "battery_charge_kwh": round(integrate(g["batt_charge_w"], idx), 2),
            "battery_discharge_kwh": round(integrate(g["batt_discharge_w"], idx), 2),

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


def parse_export(source, site_id: str, filename: str = "",
                 pv_kwp: float | None = None,
                 battery_usable_kwh: float | None = None) -> dict:
    """Full pipeline: file → daily rows + alarm events + warnings.

    Raises `VrmCsvError` on anything that would produce a bad report rather
    than returning partial results.
    """
    raw, timezone_label = load_vrm_csv(source)
    tidied, missing = tidy(raw)
    warnings = validate_export(raw, tidied, missing)
    unscored = unscored_alarm_summary(raw)
    if unscored:
        warnings.append(
            "Alarm signals present but not scored (see ALARM_CATEGORIES): "
            + ", ".join(f"{k} ({v} samples)" for k, v in sorted(unscored.items()))
        )
    rows = to_energy_daily_rows(raw, tidied, site_id,
                                pv_kwp=pv_kwp,
                                battery_usable_kwh=battery_usable_kwh)
    return {
        "site_id": site_id,
        "installation_id": installation_id(filename or getattr(source, "name", "")),
        "timezone_label": timezone_label,
        "sample_count": int(len(raw)),
        "period_start": raw.index[0].isoformat(),
        "period_end": raw.index[-1].isoformat(),
        "rows": rows,
        "alarm_events": alarm_events(raw, site_id),
        "unscored_alarms": unscored,
        "outages": _grid_outages(raw).to_dict("records"),
        "missing_signals": missing,
        "warnings": warnings,
    }
