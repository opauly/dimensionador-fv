from __future__ import annotations
"""
Fleet Dashboard Phase 3a ("quiet drift") + Phase 3c ("underperformance vs.
design") anomaly detection (2026-09-03, PLAN_PHASE19_FLEET_P3.md §4/§5).

Sibling of `victron/anomaly_silence.py` (3b, already shipped) — same
`vrm.site_anomalies` table (migration 038, whose `anomaly_type` CHECK
constraint already includes `'quiet_drift'`/`'underperformance'`, no new
migration needed), same "one open row per (site_id, anomaly_type)" shape,
same deterministic/no-ML posture. Different cadence: 3b runs on the
~15-minute live-snapshot sweep (`vrm_fleet.py:post_refresh_snapshots()`); 3a
and 3c are DAILY checks (they read `vrm.energy_daily`, which is itself only
daily-grain and only advances once per site per day) — both are called from
`vrm_fleet.py:post_detect_anomalies_daily()`, hooked into the existing
`scheduled-reports.yml` hourly cron (piggybacking the same job that already
keeps `vrm.energy_daily` current via `vrm_sync.py:post_run_due()`, rather
than inventing a new schedule — PLAN_PHASE19_FLEET_P3.md §4 point 4 / §5's
own "same cadence as 3a" instruction).

── A shared PR-computation core, per the plan's own instruction ───────────
§4/§5 both say: "write one utility function, parameterize... rather than
duplicating the PVGIS plumbing twice." `_site_monthly_shape()` +
`_build_daily_series()` below are that shared core — both read
`calculations.pvgis.fetch_irradiance()` (per-site MONTHLY kWh/kWp, a
multi-year climatological average, Supabase-cached by lat/lon) and turn it
into a per-calendar-day "expected shape" any site's real `pv_kwh` history
can be compared against. The two checks below differ only in HOW they use
that shape:
  * `check_quiet_drift()` (3a) — self-baseline mode. No `pv_kwp` needed:
    each day's real `pv_kwh` is deseasonalized by PVGIS's own *relative*
    shape (that calendar month's average daily expected kWh/kWp / the
    site's own annual average daily kWh/kWp), producing an "as if every day
    had average irradiance" output series, then a 14-day recent window is
    compared to a ~90-day trailing baseline of that SAME series — a decline
    shows up as a real drop even though no absolute kWp conversion (and so
    no `pv_kwp`) was ever used. See `_build_daily_series()`'s `adjusted_kwh`
    field.
  * `check_underperformance()` (3c) — design-relative mode. Genuinely
    requires `pv_kwp` (no substitute exists for "what should this size of
    array produce" — §5): each day's real `pv_kwh` is compared directly to
    PVGIS's absolute expected kWh for that `pv_kwp` in that calendar month,
    producing a real day-level PR. See `_build_daily_series()`'s `pr` field
    (only populated when `pv_kwp` is passed in).

── Why MONTHLY shape, not `fetch_daily_series()`'s single reference year —
   a real bug found and fixed during THIS build, not a design choice made
   up front ─────────────────────────────────────────────────────────────
The first draft of this module matched each real calendar day against
`fetch_daily_series()`'s daily kWh/kWp for the SAME calendar date in ONE
specific historical PVGIS reference year (e.g. 2015) — the tool
`wizard/off_grid.py`'s battery-SoC simulation already uses, deliberately,
BECAUSE it preserves real day-to-day/cloudy-streak variability (see that
module's own docstring). That is exactly the wrong property for THIS use:
backtesting against real fleet data (rebeca-ruiz-el-encino-casona, this
build's own report has the numbers) surfaced day-level PR readings above
1.0 that traced directly to a single real day being compared against an
unusually CLOUDY day in the one arbitrary reference year PVGIS happened to
pick — noise from a DIFFERENT year's weather leaking into what should be a
smooth seasonal baseline, not a second source of real variance layered on
top of the fleet's own actual variance. `fetch_irradiance()`'s MONTHLY
kWh/kWp (a genuine multi-year climatological average, already the function
`docs/design-calibration-2026-08.md` §8 itself names as what Phase 11 used
for PR: "calculations/pvgis.py::fetch_irradiance — per-site monthly kWh/kWp
for PR") does not have this problem — every day in the same calendar month
gets that month's smoothed multi-year average, so all of the day-to-day
spread a real fleet site shows is real, not partly an artifact of which
single historical year PVGIS's daily series happened to use. Coarser
seasonal grain (12 buckets, not 365) is an accepted, already-precedented
trade-off here — `docs/design-calibration-2026-08.md` §6 open assumption 1
makes the same monthly-grain call for its own "seasonality is modelled, not
measured" caveat.

── Exclusion rules — Phase 11's, reused not reinvented ────────────────────
Both checks apply the exact same `vrm.energy_daily` row filter
`anomaly_silence.py:_site_productive_window()` already established for 3b:
drop a day with `pv_kwh IS NULL` (a day this pipeline has no real PV number
for at all) and drop a day with `complete_day = false` (a partial day — a
CSV-origin site mid-window, or a VRM sync that only covers part of a day).
That is `docs/design-calibration-2026-08.md` §8's own "drop partial days" /
"drop all-signal-null days" rule, applied the only way it is actually
computable from what `vrm.energy_daily` stores (a per-day `pv_kwh` total,
not an intraday signal) — the same posture `anomaly_silence.py`'s own module
docstring already explains for the identical constraint on 3b.

── Fail-closed posture, and how "insufficient data" differs from "clear" ──
PLAN_PHASE19_FLEET_P3.md §6: "<30 valid days produces no flag, not a
guessed one." Both checks below return immediately, doing nothing at all
(no insert, no clear, no update), the moment there isn't enough real history
to evaluate — same as `anomaly_silence.py`'s own `_site_productive_window()`
returning `None`. This is a deliberate asymmetry, mirroring 3b's own
precedent exactly: "not enough data" means "can't tell right now," which is
different from "checked, and the condition genuinely no longer holds" (which
DOES clear an open anomaly, see each function's own final branch). An
already-open anomaly is never silently cleared just because history became
temporarily unavailable/insufficient to re-derive (e.g. a sync gap) — it
stays open until a real, freshly-computed "no" outcome clears it, exactly
like 3b's "already open" branch skips its own window re-check entirely.

── Underperformance's "peak" — a real data-availability judgment call,
   flagged for Oscar, not silently resolved ─────────────────────────────
PLAN_PHASE19_FLEET_P3.md §5 asks 3c to compare "a site's best-recent-day
peak (or a smoothed recent max)" against PVGIS's expectation. `vrm.
energy_daily` is daily-ENERGY grain only (`pv_kwh` per calendar day) — there
is no stored intraday/instantaneous power series anywhere in this pipeline
to read a literal peak-W value from (the same daily-grain limitation
`anomaly_silence.py`'s own module docstring already had to work around for
3b's "should be producing" window). `docs/design-calibration-2026-08.md`'s
own "Peak W/kWp" capability test (§2/§8) was computed from raw 1-minute CSV
exports that simply do not exist for VRM-API-sourced sites in this schema.
What `check_underperformance()` actually does instead: within the recent
14-day window, pick the day with the HIGHEST day-level PR (`pv_kwh[d] /
(pvgis_expected_kwh_kwp_that_month * pv_kwp)`) — i.e. this site's best real
showing recently, the same "capability, not curtailed/cloudy average"
spirit Phase 11's own peak-W/kWp discriminator was chasing ("*Mean* PR mixes
in curtailment and dead days," docs/design-calibration-2026-08.md line 52)
— and compares THAT single best day's PR against a threshold. This is a
genuine, real proxy for "capability," not the same statistic Phase 11 used,
and its absolute threshold is calibrated separately (see
`_UNDERPERFORMANCE_PR_THRESHOLD` below) — not assumed transferable from
Phase 11's own W/kWp-based cutoffs. Building a literal intraday peak-power
history would need this pipeline to start storing sub-daily VRM data
somewhere, which is new capability, not something achievable by reading
`energy_daily` differently. Flagged for Oscar per this build's own report,
same as 3b flagged its own window-derivation judgment call.

── Threshold numbers below — starting points, not locked (§7 item 1) ──────
Every constant below was picked deliberately conservative (few false
positives over catching everything) and cross-checked against this
pipeline's own real, hand-verified fleet backtest (this build's own report
has the numbers) — but PLAN_PHASE19_FLEET_P3.md §7 item 1 is explicit that
none of these are locked. Expect a real tuning pass once more of the fleet
has accumulated enough history to exercise them.
"""
import calendar
import logging
from datetime import date, datetime, timedelta, timezone

from calculations.pvgis import fetch_irradiance

logger = logging.getLogger("victron.anomaly_drift")

QUIET_DRIFT_TYPE = "quiet_drift"
UNDERPERFORMANCE_TYPE = "underperformance"

# Shared fail-closed history gate — same number PLAN_PHASE19_FLEET_P3.md §6
# states for both 3a and 3c ("<30 valid days produces no flag").
_MIN_VALID_HISTORY_DAYS = 30

# ── 3a: quiet drift ─────────────────────────────────────────────────────
_RECENT_WINDOW_DAYS = 14
_BASELINE_WINDOW_DAYS = 90
# Sub-gates within the 30-day floor above: even a site that clears the
# overall history floor might have all of its valid days concentrated in
# one window (e.g. 30 valid days, but only 3 of them fall in the last 14
# calendar days) — these keep the recent/baseline comparison itself
# meaningful, not just the raw count. Fails closed (no flag, no state
# change) below either, same posture as the top-level floor.
_MIN_RECENT_VALID_DAYS = 7
_MIN_BASELINE_VALID_DAYS = 21
# A recent day counts as "low" if its deseasonalized output falls below
# this fraction of the trailing baseline mean.
_DROP_RATIO_THRESHOLD = 0.75
# Sustained-drop gate — PLAN_PHASE19_FLEET_P3.md §4 point 3's own starting
# number ("≥7 of the last 14 days").
_SUSTAINED_DAYS_REQUIRED = 7

# ── 3c: underperformance vs. design ─────────────────────────────────────
_UNDERPERFORMANCE_RECENT_WINDOW_DAYS = 14
_UNDERPERFORMANCE_MIN_RECENT_VALID_DAYS = 5
# Best-recent-day PR (see module docstring's "peak" section) below this
# counts as underperforming. Chosen from this build's own real backtest
# (see this build's own report): rebeca-ruiz-el-encino-casona (Phase 11's
# own "healthy, best-matched" label, measured mean PR 0.93) computes a
# best-recent-day PR comfortably above this line; roberto-villalobos
# (Phase 11's own "array underperforming ~70-75%" label) computes one
# clearly below it.
_UNDERPERFORMANCE_PR_THRESHOLD = 0.70


def _parse_date(value) -> date | None:
    """Same permissive, never-raises posture as `anomaly_silence.py`'s own
    `_parse_dt()` -- a bad/missing date on one row must not break the whole
    check."""
    if value is None:
        return None
    if isinstance(value, date):
        return value if not isinstance(value, datetime) else value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _valid_daily_rows(energy_daily_rows: list[dict]) -> list[dict]:
    """Phase 11's exclusion rules, applied the way `anomaly_silence.py`'s
    own `_site_productive_window()` already applies them for 3b -- see the
    module docstring's "Exclusion rules" section. Rows missing/failing to
    parse a `date` are dropped too (can't place them in a window at all)."""
    out = []
    for r in energy_daily_rows:
        if r.get("pv_kwh") is None or r.get("complete_day") is False:
            continue
        if _parse_date(r.get("date")) is None:
            continue
        out.append(r)
    return out


def _site_monthly_shape(lat: float, lon: float) -> tuple[list[float], float] | None:
    """The shared PVGIS half of both checks (module docstring). Returns
    `(monthly_kwh_kwp, annual_avg_daily_kwh_kwp)` for this site's own
    lat/lon -- `monthly_kwh_kwp` is `fetch_irradiance()`'s own 12-value
    list (index 0 = January), a genuine multi-year climatological average,
    Supabase-cached by lat/lon (cheap cache hit on every call after the
    first for a given site). `annual_avg_daily_kwh_kwp` is that same
    series' yearly total divided by 365 -- the denominator for 3a's
    relative-shape ratio. `None` (fail closed, same as everywhere else in
    this module) if PVGIS returned nothing usable -- never raises for that
    case, though a genuine network/PVGIS-API failure DOES propagate (the
    caller's own per-site try/except in `vrm_fleet.py` is what isolates
    that, same as every other per-site VRM/PVGIS call already isolated
    there)."""
    data = fetch_irradiance(lat, lon)
    monthly = data.get("monthly_kwh_kwp") or []
    if len(monthly) != 12:
        return None
    yearly = data.get("yearly_kwh_kwp") or sum(monthly)
    if not yearly or yearly <= 0:
        return None
    return monthly, yearly / 365.0


def _expected_daily_kwh_kwp(d: date, monthly_kwh_kwp: list[float]) -> float | None:
    """That calendar day's expected kWh/kWp, at MONTH grain (module
    docstring's "Why MONTHLY shape" section) -- this month's total kWh/kWp
    spread evenly across this month's real number of calendar days (a
    genuine days-in-month, via `calendar.monthrange`, not a fixed 30)."""
    month_total = monthly_kwh_kwp[d.month - 1]
    if month_total is None or month_total <= 0:
        return None
    days_in_month = calendar.monthrange(d.year, d.month)[1]
    return month_total / days_in_month


def _build_daily_series(valid_rows: list[dict], monthly_kwh_kwp: list[float], annual_avg_daily: float,
                        *, pv_kwp: float | None = None) -> list[dict]:
    """The shared per-day series both checks are built from -- module
    docstring's "A shared PR-computation core" section. One entry per valid
    row (chronological), each `{"date", "pv_kwh", "shape_factor",
    "adjusted_kwh", "expected_kwh" | None, "pr" | None}`. `shape_factor` is
    that calendar day's month-level PVGIS-expected kWh/kWp relative to this
    site's own annual average daily kWh/kWp (3a's whole "relative shape,
    not absolute kWp" trick); `adjusted_kwh` is `pv_kwh` deseasonalized by
    it (what 3a actually trends). `expected_kwh`/`pr` are only populated
    when `pv_kwp` is given (3c's design-relative mode) -- `pv_kwh` against
    PVGIS's real absolute expectation for that installed size in that
    calendar month. Rows whose expected value is non-positive are skipped
    (not fabricated)."""
    out: list[dict] = []
    for r in valid_rows:
        d = _parse_date(r.get("date"))
        if d is None:
            continue
        expected_kwh_kwp = _expected_daily_kwh_kwp(d, monthly_kwh_kwp)
        if not expected_kwh_kwp or expected_kwh_kwp <= 0:
            continue
        shape_factor = expected_kwh_kwp / annual_avg_daily
        if shape_factor <= 0:
            continue
        pv_kwh = float(r["pv_kwh"])
        entry: dict = {
            "date": d, "pv_kwh": pv_kwh, "shape_factor": shape_factor,
            "adjusted_kwh": pv_kwh / shape_factor,
            "expected_kwh": None, "pr": None,
        }
        if pv_kwp:
            expected_kwh = expected_kwh_kwp * pv_kwp
            if expected_kwh > 0:
                entry["expected_kwh"] = expected_kwh
                entry["pr"] = pv_kwh / expected_kwh
        out.append(entry)
    out.sort(key=lambda e: e["date"])
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


def check_quiet_drift(
    anomalies_table,
    *,
    site_id: str,
    lat: float | None,
    lon: float | None,
    energy_daily_rows: list[dict],
    now_utc: datetime | None = None,
) -> None:
    """One site's quiet-drift check (3a), meant to run once daily -- see
    the module docstring. `anomalies_table` is a Supabase `postgrest-py`
    table handle already scoped to `vrm.site_anomalies`, same calling
    convention as `anomaly_silence.check_unexpected_silence()`.
    `energy_daily_rows` is this site's own recent `vrm.energy_daily` rows
    (`{"date", "pv_kwh", "complete_day"}` shape, extra keys ignored) --
    needs at least `_BASELINE_WINDOW_DAYS + _RECENT_WINDOW_DAYS` of
    coverage to be worth anything, but the caller is free to pass more.

    Deliberately does NOT require `pv_kwp` (module docstring) -- only
    `lat`/`lon` (for PVGIS's relative shape). A site missing coordinates
    is a real, separate gap from missing `pv_kwp` (both blocked this
    build's own real coverage in practice -- see this build's report) and
    is treated the same as insufficient history: nothing happens, no state
    change, fail closed."""
    now_utc = now_utc or datetime.now(timezone.utc)
    open_rows = (
        anomalies_table.select("id,detail")
        .eq("site_id", site_id).eq("anomaly_type", QUIET_DRIFT_TYPE)
        .is_("cleared_at", "null").limit(1).execute().data
    )
    open_row = open_rows[0] if open_rows else None

    if lat is None or lon is None:
        return  # no coordinates -- can't derive a PVGIS shape at all; fail closed, no state change

    valid = _valid_daily_rows(energy_daily_rows)
    if len(valid) < _MIN_VALID_HISTORY_DAYS:
        return  # fail closed -- §6

    shape = _site_monthly_shape(lat, lon)
    if shape is None:
        return
    monthly_kwh_kwp, annual_avg_daily = shape

    series = _build_daily_series(valid, monthly_kwh_kwp, annual_avg_daily)
    today = now_utc.date()
    recent_cutoff = today - timedelta(days=_RECENT_WINDOW_DAYS)
    baseline_cutoff = recent_cutoff - timedelta(days=_BASELINE_WINDOW_DAYS)

    recent = [e for e in series if recent_cutoff <= e["date"] < today]
    baseline = [e for e in series if baseline_cutoff <= e["date"] < recent_cutoff]

    if len(recent) < _MIN_RECENT_VALID_DAYS or len(baseline) < _MIN_BASELINE_VALID_DAYS:
        return  # not enough real coverage in either window to say anything -- fail closed, no state change

    baseline_mean = sum(e["adjusted_kwh"] for e in baseline) / len(baseline)
    if baseline_mean <= 0:
        return  # a genuinely dormant/near-zero site -- nothing meaningful to compare a drop against

    low_days = [e for e in recent if e["adjusted_kwh"] < _DROP_RATIO_THRESHOLD * baseline_mean]
    recent_mean = sum(e["adjusted_kwh"] for e in recent) / len(recent)

    if len(low_days) < _SUSTAINED_DAYS_REQUIRED:
        # A real, freshly-computed "no" -- clears an open anomaly (unlike
        # the fail-closed branches above, which never touch state; see the
        # module docstring's "Fail-closed posture" section for why these
        # are different).
        _clear_open(anomalies_table, open_row, now_utc, site_id=site_id,
                   log_msg="anomaly_drift: cleared quiet_drift for site %s")
        return

    detail = {
        "recent_mean_kwh_adj": round(recent_mean, 3),
        "baseline_mean_kwh_adj": round(baseline_mean, 3),
        "ratio_recent_to_baseline": round(recent_mean / baseline_mean, 3),
        "days_flagged": len(low_days),
        "recent_window_days": len(recent),
        "baseline_window_days": len(baseline),
        "drop_ratio_threshold": _DROP_RATIO_THRESHOLD,
        "sustained_days_required": _SUSTAINED_DAYS_REQUIRED,
        "last_checked_at": now_utc.isoformat(),
    }
    _open_or_update(anomalies_table, open_row, site_id=site_id, anomaly_type=QUIET_DRIFT_TYPE,
                    detected_at_iso=now_utc.isoformat(), detail=detail,
                    log_msg="anomaly_drift: OPENED quiet_drift for site %s")


def check_underperformance(
    anomalies_table,
    *,
    site_id: str,
    lat: float | None,
    lon: float | None,
    pv_kwp: float | None,
    energy_daily_rows: list[dict],
    now_utc: datetime | None = None,
) -> None:
    """One site's underperformance-vs-design check (3c), meant to run once
    daily -- see the module docstring. Same calling convention as
    `check_quiet_drift()` above.

    Genuinely requires `pv_kwp` (PLAN_PHASE19_FLEET_P3.md §5 -- "no
    substitute exists"). A site with no `pv_kwp` set is SKIPPED entirely --
    not flagged, not guessed at, same "no data over fabricated data"
    posture as everywhere else in this pipeline. Same for missing
    coordinates."""
    now_utc = now_utc or datetime.now(timezone.utc)
    open_rows = (
        anomalies_table.select("id,detail")
        .eq("site_id", site_id).eq("anomaly_type", UNDERPERFORMANCE_TYPE)
        .is_("cleared_at", "null").limit(1).execute().data
    )
    open_row = open_rows[0] if open_rows else None

    if lat is None or lon is None or not pv_kwp or float(pv_kwp) <= 0:
        return  # out of scope entirely -- fail closed, no state change (§5)

    valid = _valid_daily_rows(energy_daily_rows)
    if len(valid) < _MIN_VALID_HISTORY_DAYS:
        return  # fail closed -- §6

    shape = _site_monthly_shape(lat, lon)
    if shape is None:
        return
    monthly_kwh_kwp, annual_avg_daily = shape

    series = _build_daily_series(valid, monthly_kwh_kwp, annual_avg_daily, pv_kwp=float(pv_kwp))
    today = now_utc.date()
    recent_cutoff = today - timedelta(days=_UNDERPERFORMANCE_RECENT_WINDOW_DAYS)
    recent = [e for e in series if recent_cutoff <= e["date"] < today and e["pr"] is not None]

    if len(recent) < _UNDERPERFORMANCE_MIN_RECENT_VALID_DAYS:
        return  # not enough real recent coverage -- fail closed, no state change

    best = max(recent, key=lambda e: e["pr"])

    if best["pr"] >= _UNDERPERFORMANCE_PR_THRESHOLD:
        _clear_open(anomalies_table, open_row, now_utc, site_id=site_id,
                   log_msg="anomaly_drift: cleared underperformance for site %s")
        return

    detail = {
        "best_recent_pr": round(best["pr"], 3),
        "best_recent_date": best["date"].isoformat(),
        "best_recent_pv_kwh": round(best["pv_kwh"], 3),
        "best_recent_expected_kwh": round(best["expected_kwh"], 3),
        "pv_kwp": float(pv_kwp),
        "recent_window_days": len(recent),
        "pr_threshold": _UNDERPERFORMANCE_PR_THRESHOLD,
        "last_checked_at": now_utc.isoformat(),
    }
    _open_or_update(anomalies_table, open_row, site_id=site_id, anomaly_type=UNDERPERFORMANCE_TYPE,
                    detected_at_iso=now_utc.isoformat(), detail=detail,
                    log_msg="anomaly_drift: OPENED underperformance for site %s")
