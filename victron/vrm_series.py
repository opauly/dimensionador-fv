from __future__ import annotations
"""
Victron VRM cloud time series → `energy_daily` / `alarm_events` rows.

Third ingestion path for the weekly monitoring report (after Node-RED direct
writes and `victron/vrm_csv.py`'s CSV-export mapper), and `vrm_csv.py`'s
deliberate sibling (PLAN_PHASE15.md §0.4): this module maps Victron's cloud
`stats` API — arrays of `[epoch_ms, value]` per attribute code — onto the
same canonical shape, so `victron/ingest.py:ingest_parsed()` consumes either
mapper's output with no branching. `fetch_and_map()`'s return dict matches
`vrm_csv.parse_export()`'s key set exactly (`site_id`, `installation_id`,
`sample_count`, `period_start`, `period_end`, `rows`, `alarm_events`,
`unscored_alarms`, `outages`, `missing_signals`, `warnings`).

This module is a pure mapper: it takes an already-constructed
`victron.vrm_remote.VrmRemoteClient` and never reads an env var, never
constructs a client, and never touches Postgres. Token handling stays
entirely in `vrm_remote.py` / the caller (PLAN_PHASE15.md §8 Step 3).

── Traps inherited from `victron/vrm_daily.py`, unchanged ──────────────────
`vrm_daily.py` (PLAN_PHASE15.md §4.1) is the format-independent core this
module reuses for everything downstream of the tidied frame — outage
detection, the NaN-inherits-previous-state rule, the alarm episode state
machine, and the integrator. All three of `vrm_daily.py`'s own traps
(outages are AC-input-voltage absence, not `Grid alarm`; an all-NaN sample
must let the previous state persist; sample spacing is derived from the
index itself, never assumed) therefore hold here exactly as they do for the
CSV path, because both mappers feed the same functions the same canonical
columns (`grid_v_l1`, `grid_v_l2`, `soc_pct`, `batt_v`, `batt_temp_c`, …).

── Traps that do NOT apply to this path ─────────────────────────────────────
`vrm_csv.py`'s "duplicate column names are real data" trap (`_pick_all`) is
CSV-specific — this module never parses a CSV. The 3-row-header quirk and
`Device::Description` naming don't exist here either.

── Traps that ARE new to this path ──────────────────────────────────────────
1. **`MAX_GAP_S` interval mismatch (PLAN_PHASE15.md §4.3).** `vrm_csv.py`'s
   `MAX_GAP_S = 300` was tuned for ~1-minute CSV sampling. At `interval=
   "15mins"` every real sample gap is 900s, so passing 300 here would make
   `integrate()`/`_grid_outages()` refuse to integrate across *any* gap and
   silently produce ~0 kWh / 0 outage-minutes for every day. This module
   always computes `max_gap_s = 2 * <seconds for `interval`>` and passes it
   explicitly into every `vrm_daily.py` call that takes it — never the CSV
   path's constant. (In practice this only bites the *state* columns and
   outage detection below — see point 2.)
2. **Energy columns are NOT produced by integrating a power series here.**
   Per §4.4, `pv_kwh`/`load_kwh`/`grid_kwh`/`grid_export_kwh` are taken from
   Victron's own `interval=days` energy-flow totals (`Pb,Pc,Pg,Gb,Gc,Bc,Bg`),
   combined per §4.4's formulas, and substituted into the rows `vrm_daily.
   to_energy_daily_rows()` produces — replacing the values that function
   computed from the tidied frame's `pv_w`/`load_w`/… columns, which this
   module deliberately leaves all-NaN (so `integrate()` harmlessly returns
   0.0 for each before being overwritten). Two consequences worth stating
   plainly, not discovering while reading a report: (a) VRM's own daily
   accumulation and this module's integration of the *state* series are
   different numbers computed from different underlying data — they are not
   expected to match to the last decimal, only within the tolerance measured
   and recorded in PLAN_PHASE15.md §4's Step 3 validation subsection; (b)
   the `MAX_GAP_S` landmine therefore does **not** show up in the energy
   columns the way §4.3 originally worried about (a wrong `max_gap_s` would
   zero out an *integrated* pv_kwh, but this path's pv_kwh never goes
   through `integrate()`) — it would instead show up in `outage_minutes`
   and in the state extremes' honesty about gaps. The Step 3 validation
   asserts `pv_kwh > 0` on a sunny day regardless, both because it is a
   basic sanity check on the days-totals formula and because a caller that
   swaps interval without re-deriving `max_gap_s` would still break outage
   detection silently otherwise.
2b. **`battery_charge_kwh`/`battery_discharge_kwh` are `NULL`+warning, a
   deliberate deviation from §4.4's literal `Pb+Gb`/`Bc+Bg` formula, decided
   by Step 3's empirical validation, not by this step improvising a new
   design.** §4's own validation instructions pre-authorize exactly this:
   "a column that can't meet a reasonable tolerance ships as NULL-with-
   warning". Measured against the `vista-atenas-lp-m3` fixture (a
   DC-coupled architecture — PV feeds the battery/DC bus directly, there is
   no "PV - AC-coupled" signal on this installation), `Pb+Gb` and `Bc+Bg`
   disagreed with the CSV path's battery-monitor-derived
   `battery_charge_kwh`/`battery_discharge_kwh` by a mean of 26%/35% and up
   to 97%/58% on individual days — far outside the ~1-8% agreement every
   other energy column achieved on the same fixture. The reason is
   structural, not noise: `(Pb+Gb) - (Bc+Bg)` is algebraically forced to
   equal `pv_kwh - load_kwh` (confirmed empirically: identical to two
   decimal places on every sampled day) because Victron's flow-diagram
   attribution is a *derived complement* of the PV/load balance, not an
   independent measurement — whereas the CSV path's battery figures come
   from an actual battery-monitor/shunt (or GX-estimated) power reading,
   which captures real conversion losses and self-consumption the simple
   flow-balance arithmetic never sees. Both numbers are real Victron output;
   they answer different questions ("what does the flow diagram attribute
   to the battery" vs. "what did the battery's own sensor measure"), and
   only the second is comparable to what the CSV path — and a customer's own
   VRM portal battery widget — report. Shipping the flow-diagram number under
   the same column name as the CSV path's sensor-derived one would be a
   silently wrong report, not an approximately-right one, so both fields
   are `None` on every row from this module, with a `warnings` entry stating
   why.
3. **Unavailable signals become `NULL` with a warning, never a silent 0
   (§4.5).** Every installation publishes a different subset of Victron's
   attribute codes (`get_diagnostics()` is called first, precisely to find
   out which). Two fields are deliberately downgraded rather than
   fabricated when their inputs aren't available:
   - `outage_count` / `outage_minutes`: if neither `IV1` nor `IV2` (AC input
     voltage, phase 1/2) is published by this installation, these are
     overwritten to `None` on every row (not `0` — `vrm_daily.
     to_energy_daily_rows()` would otherwise happily report zero outages
     because its outage detector finds nothing wrong with an all-absent
     voltage series, which is exactly the silent-zero bug `vrm_csv.py`'s own
     docstring describes fixing once already).
   - `pv_yield_kwh_sc0` / `_sc1` / `_mppt`: Victron's `stats` endpoint has no
     documented way to disambiguate *which* solar-charger instance an
     attribute code like `YT` ("Yield today") belongs to when an
     installation has more than one charger — `get_diagnostics()` shows two
     separate `Solar Charger` device instances both publishing `code="YT"`,
     and a `stats?attributeCodes[]=YT` call returns one series, not two, with
     no visible way from this endpoint to request a specific instance. Rather
     than guess which instance (or silently sum/average across them, which
     would be a fabricated number wearing a real one's name), this module
     always leaves these three fields `None` on the API path and does not
     pass `yields=` into `vrm_daily.to_energy_daily_rows()`.
   - `battery_reached_float`: per §4.4's explicit recommendation (b), this
     module does not pass `charge_states=` either, so `vrm_daily.
     to_energy_daily_rows()`'s own fallback rule — "the pack hit 100%" — is
     the *entire* rule here, not an addition to a per-charger "entered
     Float" check the CSV path also has. This is a real, permanent scoring
     difference between an API-sourced site and a CSV-sourced one for the
     same installation, recorded once here (not per-row) plus once per sync
     run in the `warnings` list, per §4.4's instruction.

── Day-bucketing timezone, a Step 3 gap closed at Step 4 ────────────────────
Victron's `stats` endpoint takes epoch-second `start`/`end` and (empirically
confirmed against installation 844478, Step 3) its `interval=days` buckets
are plain 24-hour windows anchored at the `start` timestamp — **not**
calendar-day-aligned in any timezone. To get one bucket per real local
calendar day (matching the CSV path's day grouping, which is naive-local by
construction — a VRM CSV export's timestamps are already in the
installation's configured portal timezone, tz-unaware), `start`/`end` must
be converted to **local midnight**, in a timezone neither `get_diagnostics()`
nor `get_stats()` return (only `GET /users/{id_user}/installations` does,
and `fetch_and_map()` deliberately isn't given an `id_user` — see the
module's public contract below, so this module can never look it up itself).

Step 3 shipped this hardcoded to `America/Costa_Rica` (`DEFAULT_TZ_NAME`
below) with no way for a caller to override it — flagged explicitly in its
own status note as a real, open gap: `vrm.sites.timezone` already varies per
real site in this product, so every non-Costa-Rica site's calendar days
would have been silently mis-bucketed the first time a real sync job ran.
**Step 4 closes this**: `fetch_and_map()` now takes a keyword-only `tz`
parameter (IANA name, e.g. `"America/Guatemala"`) that the caller — the
`vrm_sync` job, which has the site row and therefore `vrm.sites.timezone` —
is expected to pass through. `tz` defaults to `DEFAULT_TZ_NAME`
(`"America/Costa_Rica"`) only so this module's own signature stays
default-identical to Step 3's for any caller that doesn't (yet) pass one —
not because Costa Rica is still assumed to be correct for every site. The
reference fixture used to validate this module (`vista-atenas-lp-m3`, VRM
portal timezone `America/Guatemala (-06:00)`) happens to share
`America/Costa_Rica`'s exact UTC-6, no-DST offset, which is why Step 3's
byte-for-byte agreement against the CSV fixture held even with the constant
hardcoded — that coincidence is exactly what made the gap easy to miss
before a genuinely different-timezone site synced for real. `start`/`end`
accept a `date`, `datetime`, or `YYYY-MM-DD` string and are always
interpreted as `tz`'s calendar days, inclusive.

── Scope note ────────────────────────────────────────────────────────────────
`vrm_csv.py`'s `UNSCORED_ALARM_SIGNALS` (DC ripple, temperature, Battery
Monitor faults — detected but never scored) has no equivalent here yet.
`get_diagnostics()` does list plausible analogues (`eT*`, `eR*`, and more),
but mapping them was not attempted in this step — out of scope for
PLAN_PHASE15.md §8 Step 3, which names only the two *scored* alarm signals
(`eL`, `eO1`/`eO2`) as confirmed. `unscored_alarms` is always `{}` here; a
future step can extend `ALARM_CATEGORIES`-style mapping without touching
this module's public contract.
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from victron import vrm_daily

# migration 012's default for every `vrm.sites.timezone` row, and this
# module's own default `tz` — see the "Day-bucketing timezone" section of
# the module docstring for why `fetch_and_map()` has to be TOLD a timezone
# (Step 4) rather than assuming one (Step 3).
DEFAULT_TZ_NAME = "America/Costa_Rica"

_INTERVAL_SECONDS = {"15mins": 900, "hours": 3600, "days": 86400}

# Canonical tidied-frame column -> Victron attribute code. Empirically
# confirmed against a real VE.Bus + Pylontech installation (PLAN_PHASE15.md
# §0.2, Step 0 and Step 3's own diagnostics probe against installation
# 844478) — column names match `vrm_csv.py`'s `tidy()` output exactly, since
# that's the contract `vrm_daily.py`'s functions expect.
STATE_CODES = {
    "soc_pct": "SOC",
    "batt_v": "V",
    "batt_temp_c": "BT",
    "grid_v_l1": "IV1",
    "grid_v_l2": "IV2",
    "grid_freq": "IF1",
}

# Scored alarm categories — deliberately the same two categories, the same
# labels, as `vrm_csv.ALARM_CATEGORIES`, so a health score means the same
# thing regardless of ingestion path (see that module's own comment on this
# point). `eL` ("Low battery") is a direct 1:1 analogue of the CSV path's
# single "VE.Bus System::Low battery" column; `eO1`/`eO2` OR together the
# same way the CSV path ORs "Overload L1"/"Overload L2".
ALARM_CATEGORIES = {
    "low_battery": ("Low Battery Alarm", ["eL"]),
    "overload": ("Overload Alarm", ["eO1", "eO2"]),
}

# `stats?type=custom&interval=days` energy-flow codes, combined per
# PLAN_PHASE15.md §4.4's formulas below. `Pg`/`Bg` are legitimately absent
# (returned as the literal `false`, or simply missing from `get_diagnostics`)
# on a self-consumption/non-export installation — that is a real "this flow
# doesn't exist here" fact, not a missing-capability warning, and is treated
# as a zero contribution to that flow, same as the CSV path's own
# `grid_export_kwh` naturally reads 0 on such a site.
ENERGY_CODES = ("Pb", "Pc", "Pg", "Gb", "Gc", "Bc", "Bg")


class VrmSeriesError(ValueError):
    """The requested window produced nothing usable to report on."""


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise VrmSeriesError(
        f"start/end must be a date, datetime, or ISO date string, got {type(value)!r}."
    )


def _local_midnight_epoch_s(d: date, tz: ZoneInfo) -> int:
    """Local midnight (`tz`) of `d`, as a UTC epoch second — the value
    `get_stats(interval=...)` needs so its 24h buckets line up with real
    local calendar days. See the module docstring's day-bucketing section."""
    dt_local = datetime(d.year, d.month, d.day, tzinfo=tz)
    return int(dt_local.astimezone(timezone.utc).timestamp())


def _epoch_ms_to_local_naive(epoch_ms, tz: ZoneInfo) -> pd.Timestamp:
    """Victron's UTC epoch-ms -> a tz-naive local timestamp, so this
    module's frame indexes and groups by calendar day the same way
    `vrm_csv.py`'s tz-naive, already-local CSV timestamps do."""
    ts_utc = pd.Timestamp(int(epoch_ms), unit="ms", tz="UTC")
    return ts_utc.tz_convert(tz).tz_localize(None)


def _series_to_pandas(points, tz: ZoneInfo) -> pd.Series:
    """`[epoch_ms, value]` (or the `bs`-style 4-element quirk) points ->
    a float `pd.Series` indexed by local-naive timestamp.

    Handles both response-shape quirks `vrm_remote.py`'s docstring documents
    and deliberately does not normalise itself: a no-data code returns the
    literal JSON value `False`, not a list (guarded by `isinstance(points,
    list)` below); a 4-element point takes `value = points[1]`, never the
    last element, per that module's guidance.
    """
    if not isinstance(points, list) or not points:
        return pd.Series(dtype=float)
    idx: list[pd.Timestamp] = []
    vals: list[float] = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            continue
        try:
            idx.append(_epoch_ms_to_local_naive(p[0], tz))
            vals.append(float(p[1]))
        except (TypeError, ValueError):
            continue
    if not idx:
        return pd.Series(dtype=float)
    s = pd.Series(vals, index=pd.DatetimeIndex(idx), dtype=float)
    return s[~s.index.duplicated(keep="last")].sort_index()


def _available_codes(diagnostics: dict) -> set[str]:
    records = diagnostics.get("records", diagnostics) if isinstance(diagnostics, dict) else diagnostics
    if not isinstance(records, list):
        return set()
    return {r.get("code") for r in records if isinstance(r, dict) and r.get("code")}


def fetch_and_map(client, id_site, site_id: str, start, end, *,
                  pv_kwp: float | None = None,
                  battery_usable_kwh: float | None = None,
                  interval: str = "15mins",
                  tz: str = DEFAULT_TZ_NAME) -> dict:
    """Victron VRM cloud -> the same shape `vrm_csv.parse_export()` returns.

    `client` is an already-constructed `victron.vrm_remote.VrmRemoteClient`
    (this function never reads an env var or builds a client itself — see
    the module docstring). `start`/`end` are inclusive local calendar dates
    (accepts `date`, `datetime`, or `YYYY-MM-DD`) in `tz` (an IANA name,
    e.g. `"America/Guatemala"`; defaults to `DEFAULT_TZ_NAME` for a caller
    that doesn't have a better answer — see the module docstring's
    "Day-bucketing timezone" section for why a real sync job should instead
    pass the site's own `vrm.sites.timezone`).

    Raises `VrmSeriesError` if `tz` doesn't name a real IANA timezone, if
    `get_diagnostics()` shows nothing this module knows how to map, or if
    the fine-grained series comes back with no samples for the whole window
    — the same "refuse rather than report nothing meaningful" posture
    `vrm_csv.VrmCsvError` takes.
    """
    try:
        zone = ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise VrmSeriesError(f"Unknown timezone {tz!r}.") from exc

    start_date = _as_date(start)
    end_date = _as_date(end)
    if end_date < start_date:
        raise VrmSeriesError(f"end ({end_date}) is before start ({start_date}).")

    interval_seconds = _INTERVAL_SECONDS.get(interval)
    if interval_seconds is None:
        raise VrmSeriesError(
            f"Unsupported interval {interval!r}; expected one of {sorted(_INTERVAL_SECONDS)}."
        )
    # The MAX_GAP_S landmine (§4.3): never vrm_csv.MAX_GAP_S here.
    max_gap_s = 2 * interval_seconds

    diagnostics = client.get_diagnostics(id_site)
    available = _available_codes(diagnostics)
    if not available:
        raise VrmSeriesError(
            f"Victron VRM API returned no diagnostics attributes for installation {id_site}."
        )

    window_start_s = _local_midnight_epoch_s(start_date, zone)
    window_end_s = _local_midnight_epoch_s(end_date + timedelta(days=1), zone)

    missing_signals: list[str] = []
    state_code_of = {}
    for column, code in STATE_CODES.items():
        if code in available:
            state_code_of[column] = code
        else:
            missing_signals.append(column)

    alarm_codes_present: dict[str, list[str]] = {}
    for source, (_label, codes) in ALARM_CATEGORIES.items():
        present = [c for c in codes if c in available]
        if present:
            alarm_codes_present[source] = present
        else:
            missing_signals.append(f"{source}_alarm")

    energy_codes_present = [c for c in ENERGY_CODES if c in available]
    for c in ENERGY_CODES:
        if c not in available:
            missing_signals.append(f"energy:{c}")

    # ── Fine-grained series (state columns + alarm booleans) ───────────────
    requested_codes = sorted(
        set(state_code_of.values())
        | {c for codes in alarm_codes_present.values() for c in codes}
    )
    series_by_code: dict[str, pd.Series] = {}
    raw_index = pd.DatetimeIndex([])
    if requested_codes:
        body = client.get_stats(id_site, type="custom", interval=interval,
                                start=window_start_s, end=window_end_s,
                                attribute_codes=requested_codes)
        records = body.get("records", body) if isinstance(body, dict) else {}
        for code in requested_codes:
            series_by_code[code] = _series_to_pandas(
                records.get(code, False) if isinstance(records, dict) else False, zone
            )
        non_empty = [s.index for s in series_by_code.values() if not s.empty]
        if non_empty:
            raw_index = pd.DatetimeIndex(sorted(set().union(*non_empty)))

    if raw_index.empty:
        raise VrmSeriesError(
            f"No time-series samples returned for installation {id_site} "
            f"between {start_date} and {end_date}."
        )

    tidied = pd.DataFrame(index=raw_index)
    for column in STATE_CODES:
        code = state_code_of.get(column)
        tidied[column] = (series_by_code[code].reindex(raw_index)
                          if code else np.nan)
    # Placeholder power columns `vrm_daily.to_energy_daily_rows()` requires.
    # Energy is taken from Victron's own daily totals below, not by
    # integrating a power series — see the module docstring, point 2. Left
    # all-NaN so `integrate()` harmlessly returns 0.0 before being
    # overwritten.
    for column in ("pv_w", "load_w", "grid_import_w", "grid_export_w",
                   "batt_charge_w", "batt_discharge_w", "grid_w"):
        tidied[column] = np.nan

    rows = vrm_daily.to_energy_daily_rows(
        tidied, site_id, max_gap_s=max_gap_s, dump_type="vrm_api",
        pv_kwp=pv_kwp, battery_usable_kwh=battery_usable_kwh,
        yields=None, charge_states=None,
    )

    # ── Energy columns: Victron's own daily energy-flow totals (§4.4) ──────
    energy_by_code: dict[str, dict[date, float]] = {}
    if energy_codes_present:
        ebody = client.get_stats(id_site, type="custom", interval="days",
                                 start=window_start_s, end=window_end_s,
                                 attribute_codes=energy_codes_present)
        erecords = ebody.get("records", ebody) if isinstance(ebody, dict) else {}
        for code in energy_codes_present:
            s = _series_to_pandas(
                erecords.get(code, False) if isinstance(erecords, dict) else False, zone
            )
            energy_by_code[code] = {ts.date(): float(v) for ts, v in s.items()}

    def _e(code: str, day: date) -> float:
        return energy_by_code.get(code, {}).get(day, 0.0)

    for row in rows:
        day = date.fromisoformat(row["date"])
        pb, pc, pg = _e("Pb", day), _e("Pc", day), _e("Pg", day)
        gb, gc = _e("Gb", day), _e("Gc", day)
        bc, bg = _e("Bc", day), _e("Bg", day)
        row["pv_kwh"] = round(pb + pc + pg, 2)
        row["load_kwh"] = round(pc + gc + bc, 2)
        row["grid_kwh"] = round(gb + gc, 2)
        row["grid_export_kwh"] = round(pg + bg, 3)
        # NOT `round(pb + gb, 2)` / `round(bc + bg, 2)` — see the module
        # docstring, point 2b. `Pb+Gb`/`Bc+Bg` is a derived complement of
        # `pv_kwh - load_kwh`, not an independent battery measurement, and
        # Step 3's fixture showed it disagrees with the CSV path's
        # battery-monitor-derived figure by up to 97%/58% on real days.
        # NULL-with-warning, not a number nobody should trust.
        row["battery_charge_kwh"] = None
        row["battery_discharge_kwh"] = None

    warnings: list[str] = []
    if energy_codes_present:
        warnings.append(
            "battery_charge_kwh/battery_discharge_kwh are not available on the API "
            "path (Victron's Pb+Gb/Bc+Bg flow-diagram totals are a derived complement "
            "of pv_kwh-load_kwh, not an independent battery measurement, and disagreed "
            "with the CSV path's battery-monitor figure by up to 97%/58% on real days "
            "— see vrm_series.py's module docstring, point 2b)"
        )

    # ── Outages: no data is better than fabricated data (§4.5) ─────────────
    voltage_available = "grid_v_l1" not in missing_signals or "grid_v_l2" not in missing_signals
    if not voltage_available:
        for row in rows:
            row["outage_count"] = None
            row["outage_minutes"] = None
        warnings.append(
            "outages cannot be detected on the API path for this installation"
        )

    # ── Alarm episodes (§4.5: no derivable signal -> zero events + warning) ─
    alarm_events: list[dict] = []
    for source, (label, _codes) in ALARM_CATEGORIES.items():
        codes = alarm_codes_present.get(source)
        if not codes:
            continue
        parts = []
        for code in codes:
            s = series_by_code.get(code)
            if s is None or s.empty:
                continue
            parts.append((s.reindex(raw_index) != 0).fillna(False))
        if not parts:
            continue
        active = parts[0]
        for p in parts[1:]:
            active = active | p
        alarm_events.extend(vrm_daily.alarm_episode_events(
            active, site_id=site_id, alarm=label, source=source))
    alarm_events.sort(key=lambda e: e["timestamp"])
    if not alarm_codes_present:
        warnings.append(
            "no alarm signal available on the API path for this installation "
            "— alarm episodes will read as zero"
        )

    # ── Remaining warnings ───────────────────────────────────────────────
    step = raw_index.to_series().diff().dt.total_seconds()
    big_gaps = int((step > max_gap_s).sum())
    if big_gaps:
        warnings.append(
            f"{big_gaps} gap(s) longer than {max_gap_s}s in the {interval} series "
            "— state extremes (SOC/voltage/temperature) and outage detection "
            "may be less accurate across those gaps."
        )
    if missing_signals:
        warnings.append(
            "Signals not published by this installation: " + ", ".join(missing_signals)
        )
    # §4.4's recommendation (b), recorded once per run as instructed, not
    # per row: pv_yield_kwh_sc0/sc1/mppt are always NULL and
    # battery_reached_float is derived from max_soc >= 100 only — half of
    # the CSV path's own rule — because per-charger attributes cannot be
    # disambiguated through this endpoint for a multi-charger installation.
    warnings.append(
        "pv_yield_kwh_sc0/sc1/mppt are not available on the API path (Victron's "
        "stats endpoint cannot disambiguate multiple solar-charger instances "
        "sharing one attribute code); battery_reached_float is derived only "
        "from max_soc >= 100, not per-charger Float state — a known scoring "
        "difference from the CSV path."
    )

    outages = vrm_daily._grid_outages(tidied, max_gap_s).to_dict("records")

    return {
        "site_id": site_id,
        "installation_id": id_site,
        "timezone_label": str(zone),
        "sample_count": int(len(raw_index)),
        "period_start": raw_index[0].isoformat(),
        "period_end": raw_index[-1].isoformat(),
        "rows": rows,
        "alarm_events": alarm_events,
        "unscored_alarms": {},
        "outages": outages,
        "missing_signals": missing_signals,
        "warnings": warnings,
    }
