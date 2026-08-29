from __future__ import annotations
"""
Victron VRM CSV export → `energy_daily` / `alarm_events` rows.

Second ingestion path for the weekly monitoring report. The first path is
Node-RED on a Cerbo GX writing `monitoring.energy_daily` directly; this one
takes a customer's VRM CSV export and produces the same row shape, so the
report reader doesn't care which produced it.

CSV reading (`load_vrm_csv`, `tidy`) is adapted from the `reporte-solar-vrm`
skill's `vrm_parse.py`, which is field-proven against real exports. What's new
here is the mapping onto `energy_daily`'s columns, and the per-day fields the
skill's own report never needed (grid quality, battery voltage/temperature
extremes, per-charger yield).

PLAN_PHASE15.md §4 split this module: everything format-independent —
`integrate`, `_grid_outages`, `to_energy_daily_rows`'s body, the alarm
episode-edge state machine, the non-CSV-shaped half of `validate_export`'s
warnings — moved to `victron/vrm_daily.py`, so a future Victron cloud-API
mapper reuses it instead of re-implementing it. This module keeps every
public name and signature it had before that move (`parse_export`,
`to_energy_daily_rows`, `alarm_events`, `validate_export`, `installation_id`,
`VrmCsvError`, `MAX_GAP_S`) and delegates into `vrm_daily`, passing
`max_gap_s=MAX_GAP_S` — from the outside this module behaves exactly as it
did before the split.

Every mapping rule below was verified against a real 80-day export
(`vista-atenas-lp-m3`, 2026-05-10..07-28) compared row-by-row against the same
site's Node-RED-written rows, and against the flow's own logic in
`victron-monitor/node-red/victron_monitor_v1p8.json`. Full findings and the
agreement table: `victron-monitor/docs/vrm-report-v1-implementation-plan.md` §7.

Three traps that this module exists to avoid, all of which produce
plausible-looking wrong numbers rather than errors:

1. **Outages are AC-input voltage absence, not inverter state and not
   `Grid alarm`.** The skill's `find_outages()` flags "system is inverting" as
   an island event; at an ESS site that is normal self-consumption (95% of the
   reference period, 49 events, 111,258 minutes). But `Grid alarm` — the
   signal this module used until the voltage rewrite — is the opposite failure:
   flat `Grid ok` across all 9 reference exports even while the AC input reads
   0.00 V for hours, i.e. silently "no outages ever". Voltage is the signal
   that matches reality and cross-validates across sites on one feeder. See
   `_grid_outages()`.
2. **VRM emits an all-NaN row on each exact hour boundary.** Any state machine
   over these files must let NaN inherit the previous state; treating it as a
   reading splits one long event into 59.9-minute pieces. See `_grid_outages()`.
3. **Duplicate column names are real data, not noise.** A site with two solar
   chargers repeats all 48 `Solar Charger::` names. Selecting by name returns
   only the first, so per-charger yield silently halves. See `_pick_all()`.
"""
import io
import re

import numpy as np
import pandas as pd

from victron import vrm_daily

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

# Critical alerts (PLAN_PHASE18.md §7 item 9) — a NAMED, 3-category subset
# of UNSCORED_ALARM_SIGNALS above, re-grouped so it can produce discrete
# WARNING/CLEARED episodes (via vrm_daily.alarm_episode_events(), same as
# ALARM_CATEGORIES) rather than only a per-column sample count. Deliberately
# excludes UNSCORED_ALARM_SIGNALS' other entries (Low voltage alarm, High
# charge/discharge current alarm, Internal Failure, High cell voltage) —
# PLAN_PHASE18.md §7 item 9 names exactly DC ripple, cell imbalance, and
# temperature faults as the safety-relevant trio to surface as their own
# report section; unscored_alarm_summary() below still catches the full,
# wider list as an ingestion-log-only warning, unchanged.
CRITICAL_ALARM_CATEGORIES = {
    "dc_ripple": ("High DC Ripple", [("VE.Bus System", "High DC Ripple")]),
    "cell_imbalance": ("Cell Imbalance Alarm", [("Battery Monitor", "Cell Imbalance alarm")]),
    "temp_fault": ("Battery Temperature Alarm", [
        ("VE.Bus System", "Temperature L1"), ("VE.Bus System", "Temperature L2"),
        ("Battery Monitor", "High battery temperature alarm"),
    ]),
}

# ── Phase 2 hardware-conditional columns (PLAN_PHASE18.md §7 items 4a-c) ──
# UNVERIFIED against a real CSV export, unlike everything above this
# comment: none of the 13 real installations this product manages have a
# live-reporting generator or tank sensor (confirmed via a 90-day VRM API
# probe, 2026-08-29), so there is no real CSV export containing these
# columns to check the exact "Device::Description" spelling against.
# `("Grid meter", ...)` is the one exception — that device name is already
# confirmed correct (SIGNALS above already uses it for grid_l1_w/l2/l3), so
# only the voltage/current/power-factor DESCRIPTION strings below are
# unverified, inferred from Victron's own VRM API `description` field seen
# on a real installation (Emtec, 2026-08-26) on the assumption CSV export
# labels match the API's description text — true everywhere else this
# module was checked, but not confirmed for these specific new columns.
# If a future subscriber's export doesn't match, `_pick_all()` simply finds
# nothing and these columns read `None` — the same safe "missing, not
# wrong" failure mode every other optional signal in this module already
# has, so shipping this ahead of a real sample costs nothing.
GENERATOR_ACCUMULATED_TIME = ("Generator", "Accumulated time")
GRID_METER_VOLTAGE = {"l1": ("Grid meter", "Grid meter voltage L1"),
                       "l2": ("Grid meter", "Grid meter voltage L2"),
                       "l3": ("Grid meter", "Grid meter voltage L3")}
GRID_METER_CURRENT = {"l1": ("Grid meter", "Grid meter current L1"),
                       "l2": ("Grid meter", "Grid meter current L2"),
                       "l3": ("Grid meter", "Grid meter current L3")}
GRID_METER_POWER_FACTOR = {"l1": ("Grid meter", "Grid Power factor - L1"),
                            "l2": ("Grid meter", "Grid Power factor - L2"),
                            "l3": ("Grid meter", "Grid Power factor - L3")}
GRID_METER_FREQUENCY = ("Grid meter", "Grid meter frequency L1")
GRID_METER_PEN_VOLTAGE = ("Grid meter", "PEN (Protective earth-Neutral) voltage")
TANK_CAPACITY = ("Tank", "Tank capacity")
TANK_FLUID_TYPE = ("Tank", "Tank fluid type")
TANK_STATUS = ("Tank", "Tank status")
TANK_LEVEL = ("Tank", "Tank level")  # speculative column name — see vrm_series.py's own note; no numeric level code was found on any real installation to confirm against


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

    # The gap/grid-data/AC-voltage warnings only look at the tidied frame's
    # canonical columns and the sample index — format-independent, moved to
    # vrm_daily.py (§4.1). max_gap_s is this path's own constant, passed
    # explicitly (vrm_daily.py never defaults it — see its module docstring).
    warnings.extend(vrm_daily.format_independent_warnings(raw.index, tidied, MAX_GAP_S))
    return warnings


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

    Finding *which columns* feed each alarm category is CSV-column-shaped and
    stays here (`_category_active`); the WARNING/CLEARED episode-boundary
    state machine over the resulting boolean series is format-independent and
    moved to `vrm_daily.alarm_episode_events()` (§4.1).
    """
    events: list[dict] = []
    for source, (label, specs) in ALARM_CATEGORIES.items():
        active = _category_active(raw, specs)
        if active is None or active.empty:
            continue
        events.extend(vrm_daily.alarm_episode_events(
            active, site_id=site_id, alarm=label, source=source))
    events.sort(key=lambda e: e["timestamp"])
    return events


def critical_alerts(raw: pd.DataFrame, site_id: str) -> list[dict]:
    """`vrm.critical_alerts`-shaped rows (PLAN_PHASE18.md §7 item 9) — same
    WARNING/CLEARED episode shape `alarm_events()` produces, over
    CRITICAL_ALARM_CATEGORIES instead of ALARM_CATEGORIES. `source` on each
    event is the 3-value category id (`dc_ripple`/`cell_imbalance`/
    `temp_fault`); the caller renames it to `category` when inserting into
    `vrm.critical_alerts`, which is a plain rename, not a reshape — see that
    table's own migration comment.
    """
    events: list[dict] = []
    for source, (label, specs) in CRITICAL_ALARM_CATEGORIES.items():
        active = _category_active(raw, specs)
        if active is None or active.empty:
            continue
        events.extend(vrm_daily.alarm_episode_events(
            active, site_id=site_id, alarm=label, source=source))
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

    The row-building logic itself is format-independent and lives in
    `vrm_daily.to_energy_daily_rows()` (§4.1); this wrapper's only job is the
    CSV-specific part — pulling out each physical charger's "Yield today" /
    "Charge state" series by column name, plus (PLAN_PHASE18.md §7) each
    hardware-conditional signal the export happens to contain — and passing
    this path's own `max_gap_s=MAX_GAP_S` explicitly (`vrm_daily.py` never
    defaults it).
    """
    yields = _pick_all(raw, *YIELD_TODAY)
    charge_states = _pick_all(raw, *CHARGE_STATE)

    generator_series = _pick_all(raw, *GENERATOR_ACCUMULATED_TIME)
    generator_time_s = generator_series[0] if generator_series else None

    grid_meter: dict[str, pd.Series] = {}
    for phase, spec in GRID_METER_VOLTAGE.items():
        cols = _pick_all(raw, *spec)
        if cols:
            grid_meter[f"v_{phase}"] = cols[0]
    for phase, spec in GRID_METER_CURRENT.items():
        cols = _pick_all(raw, *spec)
        if cols:
            grid_meter[f"c_{phase}"] = cols[0]
    for phase, spec in GRID_METER_POWER_FACTOR.items():
        cols = _pick_all(raw, *spec)
        if cols:
            grid_meter[f"pf_{phase}"] = cols[0]
    freq_cols = _pick_all(raw, *GRID_METER_FREQUENCY)
    if freq_cols:
        grid_meter["freq"] = freq_cols[0]
    pen_cols = _pick_all(raw, *GRID_METER_PEN_VOLTAGE)
    if pen_cols:
        grid_meter["pen_v"] = pen_cols[0]

    tank: dict[str, pd.Series] = {}
    for key, spec in (("capacity", TANK_CAPACITY), ("fluid_type", TANK_FLUID_TYPE),
                      ("status", TANK_STATUS), ("level_pct", TANK_LEVEL)):
        cols = _pick_all(raw, *spec)
        if cols:
            tank[key] = cols[0]

    return vrm_daily.to_energy_daily_rows(
        tidied, site_id, max_gap_s=MAX_GAP_S, dump_type=dump_type,
        pv_kwp=pv_kwp, battery_usable_kwh=battery_usable_kwh,
        yields=yields, charge_states=charge_states,
        generator_time_s=generator_time_s, grid_meter=grid_meter, tank=tank,
    )


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
        "critical_alerts": critical_alerts(raw, site_id),
        "unscored_alarms": unscored,
        "outages": vrm_daily._grid_outages(tidied, MAX_GAP_S).to_dict("records"),
        "missing_signals": missing,
        "warnings": warnings,
    }
