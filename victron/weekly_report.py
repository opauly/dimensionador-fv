from __future__ import annotations
"""
Weekly monitoring report — Python port of Apps Script's `weeklyReport(siteId)`
(`victron-monitor/apps-script/Victron_Events_App_Script_v1p7.js` lines 684-1006).

Reads through `database/vrm_report_db.py`, so it renders from either the
`monitoring` schema (Cerbo GX sites written by Node-RED) or `vrm` (external
customers' sites ingested from VRM CSV exports).

Calibrated against a real sent report,
`Weekly Report - Vista Atenas LP M3 - 2026-07-27.pdf`.

Two intentional differences from the original, both agreed before the port:

1. **True 7-day window.** The original computes `start = today - 7` with both
   bounds inclusive — an 8-day query. In practice it returned 7 rows because
   the final day's row does not exist yet when the Monday trigger runs, so the
   header printed a period one day longer than the data it summarised. Here
   the window is 7 days and the header reports the period actually covered.
2. **`system_type` conditionals are applied.** Grid blocks are dropped for
   `off_grid`, battery blocks for `grid_zero`, rather than rendering cards that
   have no meaning for that system. The original carries `TODO(system_type)`
   markers at the three places this would have required recomputing hardcoded
   SVG column offsets.
"""
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import date

from jinja2 import Environment, FileSystemLoader, select_autoescape

from database import vrm_report_db as db
from proposals.assets.assets import get_logo_b64
from victron import report_i18n, report_svg as S, savings as savings_mod

# The 9 optional report modules render_html() knows how to build
# independently (PLAN_PHASE18.md's Decisions section). KPI header / AI
# narrative / daily bar chart are the report's fixed spine and are never in
# this set — `vrm_api/report_modules.py` imports this tuple rather than
# keeping its own copy, so this file (which actually implements each
# block) is the one source of truth for what a "module id" even means.
ALL_MODULES = (
    "energy_mix", "battery_health", "grid_quality", "events",
    "soc_chart", "solar_performance", "weather", "trend", "savings",
    # PLAN_PHASE18.md §7 — "Phase 2" modules (2026-08-29). Unlike the 9
    # above, these are never gated by has_batt/has_grid — a system with no
    # generator/tank/real meter/critical-alert data just renders zero/
    # unavailable (Oscar's own instruction), not hidden by system_type the
    # way battery_health is hidden for grid_zero.
    "critical_alerts", "grid_meter_detail", "generator_runtime", "tank_level",
)

# The set every report renders when nothing more specific is known — "no
# `selected` was ever passed" (every pre-Phase-18 caller), AND (via
# `vrm_api/report_modules.py:resolve_report_modules()`) "this customer isn't
# entitled to customize at all" / "this customer's own selection is empty."
# Deliberately NOT `ALL_MODULES` since Oscar's decision, 2026-08-29:
# critical_alerts is safety-relevant enough to show everyone by default
# (even as "0 events," the same way the Events section already shows
# "Total Alarm Episodes: 0" for a clean week) — but grid_meter_detail/
# generator_runtime/tank_level are hardware-conditional, and most real
# sites have none of that hardware, so making them default-on would add
# permanent "not detected" boilerplate to every customer's report the
# moment this shipped, for zero customers who didn't ask for it. Those
# three are opt-in only, chosen through the module selection UI, same as
# any other Growth/Fleet personalization.
DEFAULT_MODULES = (
    "energy_mix", "battery_health", "grid_quality", "events",
    "soc_chart", "solar_performance", "weather", "trend", "savings",
    "critical_alerts",
)

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_SYSTEM_EFF = 0.80          # same derating the original uses
_FALLBACK_PEAK_SUN_HRS = 4.5  # CR average, used when weather is unavailable
_OVERVIEW_BUCKET_DAYS = 30
# No weekly tier (plan doc §22, locked with the user 2026-08-15) — every
# Overview report (past db.MAX_CUSTOM_RANGE_DAYS, up to
# db.MAX_OVERVIEW_RANGE_DAYS) buckets monthly, always.
_NARRATIVE_MODEL = "claude-sonnet-4-6"

# Costa Rica has two well-defined seasons that don't shift year to year —
# unlike temperate latitudes there's no ambiguity to hedge on. Every real
# site today is Costa Rica (plan doc), so this is the one place worth
# hardcoding a country's actual calendar rather than leaving the model to
# guess it: it once guessed "dry season approaching" for an August report —
# the real dry season is Dec-Apr, half a year off.
_CR_DRY_MONTHS = {12, 1, 2, 3, 4}


def _season_context(country: str | None, period_end: date, lang: str) -> str | None:
    """A grounded season fact for the narrative prompt, or None when we don't
    have a reliable calendar for this country — never left for the model to
    infer from general knowledge, which is exactly how the wrong-season claim
    happened."""
    if country != "CR":
        return None
    dry = period_end.month in _CR_DRY_MONTHS
    if lang == "es":
        return ("Costa Rica está en temporada seca (diciembre-abril)" if dry
                else "Costa Rica está en temporada lluviosa (mayo-noviembre)")
    return ("Costa Rica is in its dry season (Dec-Apr)" if dry
            else "Costa Rica is in its rainy season (May-Nov)")


# ══════════════════════════════════════════════════════════════════
# Weather
# ══════════════════════════════════════════════════════════════════
_WEATHER_TIMEOUT_S = 8
_WEATHER_RETRIES = 2
_log = logging.getLogger(__name__)


def fetch_weather(lat: float, lng: float, start: str, end: str,
                  timezone: str = "America/Costa_Rica",
                  errors: list[str] | None = None) -> dict | None:
    """Open-Meteo archive, same endpoint and fields as the original.

    Returns None on any failure — the report must still render without it, and
    the weather block has its own "unavailable" state. That fallback must not
    also be silent: a DNS/TLS/timeout failure and "this site has no
    coordinates" produce the identical dict-is-None result to every caller, but
    they are different problems (one is fixed by filling in lat/lng, the other
    is transient). If `errors` is passed, the failure reason is appended to it
    so the caller — the report UI — can tell the two apart instead of always
    showing the same "weather unavailable" message regardless of cause.

    Retries once on a short timeout before giving up: the original single
    20s-timeout attempt was observed to fail outright on a slow/congested
    network path to archive-api.open-meteo.com, where two shorter attempts
    (8s each) succeeded — a transient handshake stall, not a dead host.
    """
    params = {
        "latitude": f"{float(lat):.4f}", "longitude": f"{float(lng):.4f}",
        "start_date": str(start), "end_date": str(end),
        "daily": "sunshine_duration,precipitation_sum,cloud_cover_mean,"
                 "shortwave_radiation_sum",
        "timezone": timezone,
    }
    url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)

    last_reason = None
    for attempt in range(1, _WEATHER_RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=_WEATHER_TIMEOUT_S) as r:
                if r.status != 200:
                    last_reason = f"Open-Meteo returned HTTP {r.status}"
                    continue
                daily = json.loads(r.read()).get("daily") or {}
                break
        except Exception as exc:  # noqa: BLE001 — any failure degrades to "no weather"
            last_reason = f"{type(exc).__name__}: {exc}"
            _log.warning("Weather fetch attempt %d/%d failed for (%.4f, %.4f): %s",
                        attempt, _WEATHER_RETRIES, lat, lng, last_reason)
    else:
        if errors is not None:
            errors.append(last_reason or "Open-Meteo request failed")
        return None

    sun = daily.get("sunshine_duration") or []
    rain = daily.get("precipitation_sum") or []
    cloud = daily.get("cloud_cover_mean") or []
    srad = daily.get("shortwave_radiation_sum") or []
    n = max(len(sun), len(srad)) or 1
    # Open-Meteo returns MJ/m²/day; ÷3.6 converts to kWh/m². This is the
    # irradiance figure the performance ratio depends on, not sunshine hours.
    total_irradiance = sum(v or 0 for v in srad) / 3.6
    return {
        "avgSunshineHrs": round(sum(v or 0 for v in sun) / n / 3600, 1),
        "rainyDays": len([p for p in rain if (p or 0) > 5]),
        "avgCloudPct": round(sum(v or 0 for v in cloud) / n),
        "totalIrradianceKwh": round(total_irradiance, 1),
    }


# ══════════════════════════════════════════════════════════════════
# Narrative
# ══════════════════════════════════════════════════════════════════
def _bucket_trend_lines(overview_buckets: list[dict], overview_trend: list[dict]) -> str:
    """One line per Overview bucket — solar/load plus health/independence/
    cycles — for the narrative prompt to describe an actual trend across the
    period instead of restating one aggregate as if the whole span were a
    single week (plan doc §22, step 6)."""
    lines = []
    for eb, tb in zip(overview_buckets, overview_trend):
        health = f"{tb['healthScore']}/100" if tb.get("healthScore") is not None else "n/a"
        # "n/a", not a literal "None" — battery_charge_kwh/battery_discharge_kwh
        # are NULL for every row on some ingestion paths (vrm_api), which makes
        # tb['batteryCycles'] None rather than a fabricated 0.0 (see
        # build_report_data's battery_kwh_available guard).
        cycles = tb["batteryCycles"] if tb["batteryCycles"] is not None else "n/a"
        lines.append(
            f"- {eb['start']} to {eb['end']} ({eb['days']} days): "
            f"{eb['pv']} kWh solar, {eb['load']} kWh consumption, "
            f"health {health}, grid independence {tb['gridIndependencePct']}%, "
            f"{cycles} battery cycles"
        )
    return "\n".join(lines)


def generate_narrative(stats: dict, lang: str) -> str:
    """Port of `generateWeeklyNarrative()` — same prompt, same fail-soft.

    A missing key or an API error returns a placeholder rather than raising:
    the report is the deliverable, and losing one paragraph must not lose it.

    Overview mode (plan doc §22, step 6) gets a genuinely different frame —
    "how did this trend across the period" — rather than the weekly prompt
    reworded with a bigger day count. Without this, a multi-month period
    read as a single oversized "week," describing one lump total with no
    sense of whether the site improved, worsened, or stayed flat across it.
    """
    t = report_i18n.get(lang, stats["totalDays"])
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return t["narrativeNoKey"]

    is_overview = bool(stats.get("isOverview"))
    period_label = ("week" if stats["totalDays"] <= 8
                    else f"{stats['totalDays']}-day period")

    is_off_grid = stats.get("systemType") == "off_grid"

    if is_overview:
        framing = (
            "You are writing the insights paragraph for a residential "
            f"solar+battery monitoring report covering a {period_label}, "
            f"broken into {len(stats['bucketTrendLines'].splitlines())} "
            f"monthly segments. {t['narrativeLang']}"
            "\n\nWrite exactly 2 short paragraphs (60-90 words total). Plain "
            "prose only - no headers, no bullets, no markdown."
            " Warm, professional tone. Be specific with numbers. Describe how "
            "the system trended across the segments below — improving, "
            "worsening, or holding steady — rather than only restating the "
            "period's totals; that trend is the most meaningful story of a "
            "multi-segment report, more than any single number."
            " If the battery kept the home running during outages, say so."
            " A forward-looking closing sentence is welcome, but only restate "
            "a fact given below (e.g. the season named, if one is given) or a "
            "trend visible in these numbers — never invent a date, a "
            "transition month, or any other detail not explicitly given, even "
            "one that sounds plausible. If a season is given, do not guess "
            "when it changes."
            f"\n\nPer-segment breakdown:\n{stats['bucketTrendLines']}"
            f"\n\nFull {period_label} totals:"
        )
    else:
        framing = (
            "You are writing the insights paragraph for a residential "
            f"solar+battery monitoring report covering a {period_label}. "
            f"{t['narrativeLang']}"
            "\n\nWrite exactly 2 short paragraphs (60-90 words total). Plain prose "
            "only - no headers, no bullets, no markdown."
            " Warm, professional tone. Be specific with numbers. Lead with the most "
            f"meaningful story of the {period_label}."
            " If the battery kept the home running during outages, say so."
            " A forward-looking closing sentence is welcome, but only restate a "
            "fact given below (e.g. the season named, if one is given) or a trend "
            "visible in these numbers — never invent a date, a transition month, "
            "or any other detail not explicitly given, even one that sounds "
            "plausible. If a season is given, do not guess when it changes."
            f"\n\nThis {period_label}'s data:"
        )

    # Off-grid sites have no utility grid concept at all — not a grid
    # connection that happens to read zero. Omitting the grid *numbers* below
    # is not enough on its own: without an explicit negative instruction the
    # model reliably invents generic "went completely off-grid, achieved X%
    # independence" framing anyway (observed verbatim in a real generated
    # report for karen-montealegre-proyecto-km-ukiyo, 2026-08-18).
    if is_off_grid:
        framing += (
            " This site has no utility grid connection of any kind (fully "
            "off-grid) — do not mention grid connection, disconnection, "
            "independence percentage, or grid outages anywhere in the "
            "narrative; frame everything purely in terms of solar generation "
            "and battery performance."
        )

    prompt = (
        framing +
        f"\n- Site: {stats['site']}"
        f"\n- Report period: {stats['periodStart']} to {stats['periodEnd']}"
        f"\n- Solar generated: {stats['pv']} kWh"
        f"\n- Total consumption: {stats['load']} kWh"
    )
    if not is_off_grid:
        prompt += (
            f"\n- Grid consumption: {stats['grid']} kWh"
            f"\n- Grid independence: {stats['gridIndependencePct']}%"
        )
    prompt += (
        f"\n- Health score: {stats['healthScore']}/100 ({stats['healthStatus']})"
        f"\n- Lowest battery SOC: {stats['minSoc']}%"
        f"\n- Battery cycles this {period_label}: {stats['batteryCycles']}"
        f"\n- Days battery reached full charge: {stats['daysFullCharge']} of {stats['totalDays']}"
    )
    if not is_off_grid:
        prompt += (
            f"\n- Grid outages: {stats['outageCount']} ({stats['outageMinutes']} minutes total)"
            f"\n- Longest single outage: {stats['longestOutageMinutes']} minutes"
            f"\n- Battery covered loads during outages: "
            f"{'yes' if stats['batteryProtectedDuringOutage'] else 'no / unknown'}"
        )
    prompt += (
        f"\n- Alarm episodes: {stats['alarmEpisodes']}"
        f"\n- Best production day: {stats['bestDay']} kWh"
        f"\n- Worst production day: {stats['worstDay']} kWh"
    )
    if stats.get("seasonContext"):
        prompt += f"\n- Season: {stats['seasonContext']}"
    # Only for sites that feed back. Without this the narrative can describe a
    # heavily exporting week purely in terms of what was consumed, which reads
    # as though the surplus went nowhere.
    if stats.get("gridExportKwh"):
        prompt += (
            f"\n- Energy exported to the grid: {stats['gridExportKwh']} kWh "
            f"({stats['gridExportPct']}% of what the system generated). This "
            "site feeds surplus back to the utility, so treat the export as a "
            "positive outcome of a well-sized system, not as waste."
        )
    if stats.get("weatherAvailable"):
        prompt += (
            f"\n- Weather: avg {stats['avgSunshineHrs']} sunshine hrs/day, days "
            f"with significant rain (>5mm): {stats['rainyDays']}, avg cloud "
            f"cover: {stats['avgCloudPct']}%."
            " If weather affected generation, mention it."
            f"\n- Solar performance ratio: {stats['solarPerformancePct']}% of expected"
        )
    if not is_off_grid:
        prompt += (f"\n- Grid quality: {stats['gridQualityScore']}/100 "
                   f"({stats['gridQualityStatus']})")

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(model=_NARRATIVE_MODEL, max_tokens=400,
                                     messages=[{"role": "user", "content": prompt}])
        return msg.content[0].text.strip()
    except Exception:
        return t["narrativeUnavailable"]


# ══════════════════════════════════════════════════════════════════
# Aggregation
# ══════════════════════════════════════════════════════════════════
def _num(v, default=0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _minmax(rows: list[dict], key: str) -> tuple[float | None, float | None]:
    vals = [_num(r[key], None) for r in rows if r.get(key) is not None]
    vals = [v for v in vals if v is not None]
    return (min(vals), max(vals)) if vals else (None, None)


def build_report_data(site_id: str, start: str | date, end: str | date, schema: str,
                      with_narrative: bool = True,
                      with_weather: bool = True,
                      branding: dict | None = None) -> dict:
    """Everything the template needs. Port of `weeklyReport()`'s computation.

    `(start, end)` is an inclusive window of any length up to
    `db.MAX_CUSTOM_RANGE_DAYS` — `monitoring` callers pass `db.week_bounds()`
    to keep the fixed 7-day cadence unchanged; `vrm` callers may pass any
    operator-chosen range (plan doc §21, Phase A).

    `branding` (PLAN_PHASE17.md §4, additive, 2026-08-21): the RENDER-READY
    output of `vrm_api/branding.py:resolve_branding()` — `company_name`,
    `contact_email`, `primary_color`, `logo_b64` (already base64-encoded, or
    `None`) — or `None` for the default Pauly & Co branding, which is the
    default here and is what every `monitoring`-schema report and every
    pre-Phase-17 caller gets, byte-for-byte unchanged. This function never
    resolves branding itself — it only carries the ALREADY-RESOLVED dict
    through to `render_html()` via the returned dict's own `"branding"` key,
    the same way every other computed value here flows through one `d`
    dict rather than as a second parallel argument list.
    """
    window = db.fetch_report_window(site_id, start, end, schema)
    site = window["site"]
    days = window["days"]
    if not days:
        raise ValueError(
            f"No energy_daily rows for {site_id!r} between "
            f"{window['period_start']} and {window['period_end']}"
        )

    # Overview mode (plan doc §22): the whole picked period, bucketed
    # monthly, for the bar/SOC charts to draw one bar/point per bucket
    # instead of per day. Empty when not is_overview — nothing reads it then.
    overview_buckets = (
        db.bucket_days(days, date.fromisoformat(window["period_start"]),
                       date.fromisoformat(window["period_end"]), _OVERVIEW_BUCKET_DAYS)
        if window["is_overview"] else []
    )

    lang = (site.get("report_language") or "en").lower()
    lang = "es" if lang == "es" else "en"
    t = report_i18n.get(lang, len(days), is_overview=window["is_overview"])
    system_type = site.get("system_type") or "hybrid"

    # "No data is better than fabricated data" (vrm_series.py's own §4.5
    # principle) — the vrm_api ingestion path deliberately leaves
    # battery_charge_kwh/battery_discharge_kwh NULL on every row (that
    # module's docstring point 2b: VRM's flow-diagram totals disagreed with
    # the CSV path's battery-monitor figure by up to 97%/58%, so NULL rather
    # than a number nobody should trust). `_num()` turns None into 0.0, which
    # is indistinguishable from a site that genuinely discharged zero — only
    # true when *every* day is None, not just some (a CSV-sourced site can
    # have a real zero-discharge day). Only that all-None case means the
    # metric isn't available for this site/window at all.
    battery_kwh_available = not (
        all(r.get("battery_charge_kwh") is None for r in days)
        and all(r.get("battery_discharge_kwh") is None for r in days)
    )

    totals = {
        "pv": sum(_num(r.get("pv_kwh")) for r in days),
        "grid": sum(_num(r.get("grid_kwh")) for r in days),
        "load": sum(_num(r.get("load_kwh")) for r in days),
        "charge": sum(_num(r.get("battery_charge_kwh")) for r in days),
        "discharge": sum(_num(r.get("battery_discharge_kwh")) for r in days),
        "outageCount": sum(int(_num(r.get("outage_count"))) for r in days),
        "outageMinutes": round(sum(_num(r.get("outage_minutes")) for r in days), 1),
        "daysFullCharge": sum(1 for r in days if r.get("battery_reached_float")),
        "daysNoGridData": sum(1 for r in days if not r.get("grid_data_available")),
        "daysSelfSufficient": sum(1 for r in days if _num(r.get("grid_kwh")) <= 0),
        "gridExport": sum(_num(r.get("grid_export_kwh")) for r in days),
        "batteryKwhAvailable": battery_kwh_available,
    }

    prev = window["previous_days"]
    prev_totals = {
        "pv": sum(_num(r.get("pv_kwh")) for r in prev),
        "grid": sum(_num(r.get("grid_kwh")) for r in prev),
        "load": sum(_num(r.get("load_kwh")) for r in prev),
    } if prev else None

    min_soc, _ = _minmax(days, "min_soc")
    _, max_soc = _minmax(days, "max_soc")
    min_v, _ = _minmax(days, "min_voltage")
    _, max_v = _minmax(days, "max_voltage")
    _, max_temp = _minmax(days, "max_temperature")
    # `_rows()`'s "avg temperature" row displayed `max_temp` under that label
    # until this fix — a real bug, not a naming choice (found while surveying
    # `energy_daily`'s columns for the report-personalization project;
    # `avg_temperature` has been ingested and stored on every row all along,
    # just never read anywhere in this file). Mean of each day's own stored
    # average, not a min/max of daily averages — matches what "average
    # temperature over the period" actually means.
    avg_temp_vals = [_num(r.get("avg_temperature"), None) for r in days]
    avg_temp_vals = [v for v in avg_temp_vals if v is not None]
    avg_temp = round(sum(avg_temp_vals) / len(avg_temp_vals), 1) if avg_temp_vals else None
    min_f, _ = _minmax(days, "min_grid_freq")
    _, max_f = _minmax(days, "max_grid_freq")
    min_l1, _ = _minmax(days, "min_grid_v_l1")
    _, max_l1 = _minmax(days, "max_grid_v_l1")
    min_l2, _ = _minmax(days, "min_grid_v_l2")
    _, max_l2 = _minmax(days, "max_grid_v_l2")

    # ── PLAN_PHASE18.md §7 items 4a-c, 9 — Phase 2 hardware-conditional /
    # critical-alert data. Every one of these reads `None`/0/empty exactly
    # the same way whether the underlying signal was never published by this
    # installation or simply had nothing to report this period — per
    # Oscar's own instruction (2026-08-29), the module always renders,
    # showing zero/unavailable rather than being hidden, so a future
    # subscriber's generator/tank/meter "just works" the day it starts
    # reporting, with no separate hardware-detection step to wire up first.
    generator_hours_total = round(sum(_num(r.get("generator_hours")) for r in days), 1)

    def _grid_meter_stat(phase: str, metric: str, agg: str) -> float | None:
        vals = [r["grid_meter"][phase][f"{metric}_{agg}"] for r in days
                if r.get("grid_meter") and phase in r["grid_meter"]
                and f"{metric}_{agg}" in r["grid_meter"][phase]]
        return round(sum(vals) / len(vals), 2) if vals else None

    grid_meter_detail: dict[str, dict] = {}
    for phase in ("l1", "l2", "l3"):
        v_mins = [r["grid_meter"][phase]["v_min"] for r in days
                 if r.get("grid_meter") and phase in r["grid_meter"] and "v_min" in r["grid_meter"][phase]]
        v_maxs = [r["grid_meter"][phase]["v_max"] for r in days
                 if r.get("grid_meter") and phase in r["grid_meter"] and "v_max" in r["grid_meter"][phase]]
        if not (v_mins or v_maxs):
            continue
        grid_meter_detail[phase] = {
            "v_min": min(v_mins) if v_mins else None,
            "v_max": max(v_maxs) if v_maxs else None,
            "v_avg": _grid_meter_stat(phase, "v", "avg"),
            "c_avg": _grid_meter_stat(phase, "c", "avg"),
            "p_avg": _grid_meter_stat(phase, "p", "avg"),
            "pf_avg": _grid_meter_stat(phase, "pf", "avg"),
        }
    has_grid_meter = bool(grid_meter_detail)

    def _tank_last(field: str):
        for r in reversed(days):
            gm = r.get(field)
            if gm is not None:
                return gm
        return None

    tank_detail = {
        "capacity_m3": _tank_last("tank_capacity_m3"),
        "fluid_type": _tank_last("tank_fluid_type"),
        "status": _tank_last("tank_status"),
        "level_pct": _tank_last("tank_level_pct"),
    }
    has_tank = any(v is not None for v in tank_detail.values())

    # Same shape/reasoning as alarm_by_category/alarm_total above, over the
    # separate, never-scored vrm.critical_alerts table (see that table's own
    # migration comment) — {} for every monitoring-schema report
    # (get_critical_alert_counts_by_category() returns {} for schema !=
    # 'vrm' without a query, since that table doesn't exist there).
    critical_by_category = window.get("critical_alert_counts_by_category") or {}
    critical_total = sum(critical_by_category.values())

    pv_by_day = [(r["date"], _num(r.get("pv_kwh"))) for r in days]
    best = max(pv_by_day, key=lambda x: x[1], default=None)
    worst = min(pv_by_day, key=lambda x: x[1], default=None)
    best_day = {"date": best[0], "pv": best[1]} if best else None
    worst_day = {"date": worst[0], "pv": worst[1]} if worst else None

    # Health: dedupe by date keeping the highest score, exactly like the original.
    health = window["health"]
    avg_health, health_status, alarm_total = "", "", 0
    if health:
        by_date: dict[str, dict] = {}
        for r in health:
            d0 = r["date"]
            if d0 not in by_date or _num(r.get("health_score")) > _num(by_date[d0].get("health_score")):
                by_date[d0] = r
        grouped = [by_date[k] for k in sorted(by_date)]
        avg_health = round(sum(_num(r.get("health_score")) for r in grouped) / len(grouped))
        health_status = grouped[-1].get("health_status") or ""
    # The "Total" shown in the Events section and referenced by the AI
    # narrative is the sum of the per-category breakdown (report bug fix,
    # 2026-08-19) — NOT `sum(daily_health.alarms_count)` as it was until
    # today. Empirically confirmed on a real site (vista-atenas-2-floor-pool,
    # 2026-07-21..28) that these two definitions genuinely disagree, and not
    # by a rounding sliver: 68 Low battery + 29 Overload = 97, vs. 83 from
    # `alarms_count` — an 18% gap, not the "rare" edge case the breakdown
    # feature's own first draft assumed. Root cause: `vrm.count_alarm_
    # episodes()` (migration 012) tracks ONE in/out state per site per day
    # across every category combined, so a second category's episode start
    # while the first is still active is not counted there — this function's
    # per-category count (`get_alarm_episode_counts_by_category()`) does not
    # have that limitation, so it is the more complete number, not just a
    # differently-defined one. Does NOT touch the persisted `daily_health.
    # health_score` itself (an independent, Postgres-trigger-computed value
    # this Python code never recalculates) — only what the customer reads as
    # "how many alarm episodes."
    alarm_by_category = window.get("alarm_episode_counts_by_category") or {}
    alarm_total = sum(alarm_by_category.values())

    grid_independence = (round(100 - totals["grid"] / totals["load"] * 100, 1)
                         if totals["load"] > 0 else 100)
    batt_usable = _num(site.get("battery_usable_kwh"), 0) or 1
    # None, not 0.0, when the underlying data isn't available — see
    # battery_kwh_available above. A fabricated 0.0 here is what the stress
    # label below used to score as "Normal", which is the single worst
    # possible label for data that is actually just absent.
    battery_cycles = (round(totals["discharge"] / batt_usable, 2)
                      if battery_kwh_available else None)
    # Estimated fallback (2026-09-03, matching vrm.compute_daily_health()'s
    # own migration 039 and admin.ts:_periodIndicators()) — min_soc/max_soc
    # ARE trustworthy for VRM-API sites even when discharge_kwh isn't; a
    # day's SOC swing gives a real, approximate cycle count. Sum of each
    # day's own swing across the window, same "per-day rate accumulated
    # over the period" shape the exact metric already has. A day missing
    # either end of its swing contributes 0, same convention `_num()`
    # already applies to discharge_kwh above.
    battery_cycles_estimated = False
    if battery_cycles is None:
        est_cycles = sum(
            (_num(r.get("max_soc")) - _num(r.get("min_soc"))) / 100
            for r in days if r.get("min_soc") is not None and r.get("max_soc") is not None
        )
        if any(r.get("min_soc") is not None and r.get("max_soc") is not None for r in days):
            battery_cycles = round(est_cycles, 2)
            battery_cycles_estimated = True
    longest_outage = window["longest_outage_minutes"]

    # Overview mode (plan doc §22): health/grid-independence/battery-cycling
    # trend, one point per bucket. Independence and cycles are *derived* per
    # bucket with the exact same formulas as the period totals just above —
    # not a second definition — from `overview_buckets`' own grid/discharge
    # sums. Health comes from a separate bucketing pass since `daily_health`
    # is a different table with its own dedup rule.
    overview_trend: list[dict] = []
    if window["is_overview"]:
        health_buckets = db.bucket_health_days(
            health, date.fromisoformat(window["period_start"]),
            date.fromisoformat(window["period_end"]), _OVERVIEW_BUCKET_DAYS)
        for eb, hb in zip(overview_buckets, health_buckets):
            overview_trend.append({
                "label": eb["label"],
                "healthScore": hb["health_score"],
                "gridIndependencePct": (round(100 - eb["grid"] / eb["load"] * 100, 1)
                                        if eb["load"] > 0 else 100),
                # Same battery_kwh_available guard as the period total above —
                # a site/window where charge/discharge is NULL for every row
                # stays NULL per bucket too, not a second un-fixed copy of the
                # fabricated-zero bug.
                "batteryCycles": (round(eb["discharge"] / batt_usable, 2)
                                  if battery_kwh_available else None),
            })

    weather = None
    weather_errors: list[str] = []
    if with_weather and site.get("latitude") is not None:
        weather = fetch_weather(site["latitude"], site["longitude"],
                                window["period_start"], window["period_end"],
                                site.get("timezone") or "America/Costa_Rica",
                                errors=weather_errors)

    pv_kwp = _num(site.get("pv_kwp"), 0)
    if weather and weather["totalIrradianceKwh"] > 0:
        expected_pv = round(weather["totalIrradianceKwh"] * pv_kwp * _SYSTEM_EFF, 1)
    else:
        expected_pv = round(_FALLBACK_PEAK_SUN_HRS * len(days) * pv_kwp * _SYSTEM_EFF, 1)
    solar_perf = round(totals["pv"] / expected_pv * 100, 1) if expected_pv > 0 else None

    # ── Grid quality score ────────────────────────────────────────
    gq = 100
    if min_f is not None and max_f is not None:
        gq -= min(round((max(0, 59.5 - min_f) + max(0, max_f - 60.5)) * 20), 20)
    if min_l1 is not None:
        gq -= 15 if (min_l1 < 108 or max_l1 > 132) else (8 if (min_l1 < 112 or max_l1 > 128) else 0)
    if min_l2 is not None:
        gq -= 15 if (min_l2 < 108 or max_l2 > 132) else (8 if (min_l2 < 112 or max_l2 > 128) else 0)
    gq -= totals["daysNoGridData"] * 5
    gq = max(0, min(100, gq))
    if gq >= 90:
        gq_status = "Estable" if lang == "es" else "Stable"
    elif gq >= 70:
        gq_status = "Fluctuaciones menores" if lang == "es" else "Minor fluctuations"
    else:
        gq_status = "Irregular" if lang == "es" else "Poor"
    gq_color = S.GREEN if gq >= 90 else (S.AMBER if gq >= 70 else S.RED)

    # ── Battery stress, using the site's own thresholds ───────────
    # `battery_cycles` is a total over the whole window, not a rate — a
    # 30-day custom range naturally accumulates ~4x the cycles a 7-day one
    # does for the exact same daily usage pattern. These thresholds (and any
    # site override) were set assuming a week, so they scale with the
    # window's length; at exactly 7 days this is a no-op.
    week_scale = len(days) / 7
    thr = {"batteryCyclesHigh": 10.0, "batteryCyclesMid": 7.0}
    thr.update(site.get("health_thresholds") or {})
    thr = {k: v * week_scale for k, v in thr.items()}
    # Estimated basis thresholds (SOC swing, migration 039) are PER-DAY
    # (0.85/0.65), unlike the exact metric's per-WEEK 10.0/7.0 -- scale by
    # the real day count directly, never by week_scale (which would give a
    # 30-day window ~4.3x too little headroom instead of ~4.3x too much).
    est_thr = {"estCyclesHigh": 0.85, "estCyclesMid": 0.65}
    est_thr.update(site.get("health_thresholds") or {})
    est_thr = {k: v * len(days) for k, v in est_thr.items()}
    # A genuine third state, not "Normal" and not the existing high-stress
    # tier — "Normal" would actively assert everything's fine for data that
    # is actually just absent (battery_kwh_available is False; see above).
    # Neutral grey on purpose so it doesn't visually read as either the good
    # green or the bad amber/red the other two states use.
    if battery_cycles is None:
        stress = t["battStressNoData"]
        stress_color = "#999"
    elif battery_cycles_estimated and battery_cycles > est_thr["estCyclesHigh"]:
        stress = "Alto estrés" if lang == "es" else "High stress"
        stress_color = S.AMBER
    elif battery_cycles_estimated and battery_cycles > est_thr["estCyclesMid"]:
        stress = "Uso activo" if lang == "es" else "Working hard"
        stress_color = S.AMBER
    elif battery_cycles_estimated:
        stress = "Normal"
        stress_color = S.GREEN
    elif battery_cycles > thr["batteryCyclesHigh"]:
        stress = "Alto estrés" if lang == "es" else "High stress"
        stress_color = S.AMBER
    elif battery_cycles > thr["batteryCyclesMid"]:
        stress = "Uso activo" if lang == "es" else "Working hard"
        stress_color = S.AMBER
    else:
        stress = "Normal"
        stress_color = S.GREEN

    narrative = ""
    if with_narrative:
        narrative = generate_narrative({
            "site": site["display_name"], "pv": f"{totals['pv']:.1f}",
            "load": f"{totals['load']:.1f}", "grid": f"{totals['grid']:.1f}",
            "systemType": system_type,
            "periodStart": window["period_start"], "periodEnd": window["period_end"],
            "seasonContext": _season_context(site.get("country"),
                                            date.fromisoformat(window["period_end"]), lang),
            "gridIndependencePct": grid_independence,
            "healthScore": avg_health, "healthStatus": health_status,
            "minSoc": min_soc,
            # "not available" text, not a bare None, so the model sees why
            # the number is missing rather than rendering "None" verbatim —
            # see battery_kwh_available above.
            "batteryCycles": (
                "not available (no per-day battery charge/discharge or SOC data for this site)"
                if battery_cycles is None else
                f"{battery_cycles} (estimated from SOC swing, not exact discharge data)"
                if battery_cycles_estimated else
                battery_cycles
            ),
            "daysFullCharge": totals["daysFullCharge"], "totalDays": len(days),
            "outageCount": totals["outageCount"],
            "outageMinutes": totals["outageMinutes"],
            "longestOutageMinutes": longest_outage,
            "batteryProtectedDuringOutage": totals["outageCount"] > 0,
            "alarmEpisodes": alarm_total,
            "bestDay": f"{best_day['pv']:.1f}" if best_day else "n/a",
            "worstDay": f"{worst_day['pv']:.1f}" if worst_day else "n/a",
            "weatherAvailable": weather is not None,
            "avgSunshineHrs": weather["avgSunshineHrs"] if weather else None,
            "rainyDays": weather["rainyDays"] if weather else None,
            "avgCloudPct": weather["avgCloudPct"] if weather else None,
            "solarPerformancePct": solar_perf,
            "gridQualityScore": gq, "gridQualityStatus": gq_status,
            "gridExportKwh": (round(totals["gridExport"], 1)
                              if site.get("exports_to_grid") else None),
            "gridExportPct": (round(totals["gridExport"] / totals["pv"] * 100)
                              if site.get("exports_to_grid") and totals["pv"] else 0),
            "isOverview": window["is_overview"],
            "bucketTrendLines": (_bucket_trend_lines(overview_buckets, overview_trend)
                                 if window["is_overview"] else ""),
        }, lang)

    return {
        "t": t, "lang": lang, "schema": schema, "systemType": system_type,
        "site": site, "siteName": site["display_name"],
        "startStr": window["period_start"], "endStr": window["period_end"],
        "dailyGrouped": days, "totals": totals, "prevTotals": prev_totals,
        "avgHealth": avg_health, "healthStatus": health_status,
        "alarmEpisodesTotal": alarm_total,
        "gridIndependencePct": grid_independence, "batteryCycles": battery_cycles,
        "batteryCyclesEstimated": battery_cycles_estimated,
        "minSoc": min_soc, "maxSoc": max_soc,
        "minVoltage": min_v, "maxVoltage": max_v, "maxTemp": max_temp, "avgTemp": avg_temp,
        "minFreq": min_f, "maxFreq": max_f,
        "minVL1": min_l1, "maxVL1": max_l1, "minVL2": min_l2, "maxVL2": max_l2,
        "bestDay": best_day, "worstDay": worst_day,
        "longestOutageMinutes": longest_outage,
        "weather": weather, "expectedPv": expected_pv,
        "solarPerformancePct": solar_perf, "pvKwp": pv_kwp,
        "gridQualityScore": gq, "gridQualityStatus": gq_status,
        "gridQualityColor": gq_color,
        "battStressLabel": stress, "battStressColor": stress_color,
        "narrative": narrative, "missingDays": window["missing_days"],
        # Distinguishes "no coordinates on this site" from "Open-Meteo request
        # failed" — both leave `weather` at None, but only one is fixed by
        # filling in lat/lng. Empty unless with_weather=True and coordinates
        # were present but the fetch still failed.
        "weatherErrors": weather_errors,
        "savings": savings_mod.compute_weekly_savings(totals, site, len(days)),
        "exportsToGrid": bool(site.get("exports_to_grid")),
        "trend": window["trend"],
        # Past db.MAX_CUSTOM_RANGE_DAYS (plan doc §22, Phase B), the bar and
        # SOC charts switch to `overviewBuckets` (monthly, always — no
        # weekly tier); `overviewTrend` (health/grid-independence/battery
        # cycling, one point per bucket) feeds the new health/grid/battery
        # trend block. Seasonal coverage and the overview-framed narrative
        # don't exist yet as of this step landing.
        "isOverview": window["is_overview"],
        "overviewBuckets": overview_buckets,
        "overviewTrend": overview_trend,
        # Off-grid-only KPI card data (report bug fix, 2026-08-18) — None for
        # every other system_type (fetch_report_window skips the query then).
        "lowBatteryShutdownCount": window["low_battery_shutdown_count"],
        # Events section per-category breakdown (report bug fix, 2026-08-19)
        # — every system_type. `sum(...)` of this dict IS `alarmEpisodesTotal`
        # above (see that variable's own comment, a few lines up in this
        # function, for why it's no longer `sum(daily_health.alarms_count)`).
        "alarmEpisodesByCategory": window["alarm_episode_counts_by_category"],
        # PLAN_PHASE18.md §7 — Phase 2 hardware-conditional / critical-alert
        # data. See this function's own "Phase 2" computation block, a few
        # lines up, for how each is derived.
        "generatorHoursTotal": generator_hours_total,
        "gridMeterDetail": grid_meter_detail, "hasGridMeter": has_grid_meter,
        "tankDetail": tank_detail, "hasTank": has_tank,
        "criticalAlertsByCategory": critical_by_category,
        "criticalAlertsTotal": critical_total,
        # PLAN_PHASE17.md §4 — see this function's own docstring. `None`
        # unless a caller explicitly resolved and passed one.
        "branding": branding,
    }


# `alarm_events.alarm`'s stored label -> the i18n key for its Events-section
# display label (report bug fix, 2026-08-19). Only the two categories
# `victron/vrm_csv.py:ALARM_CATEGORIES` actually scores — an unrecognised
# label (there shouldn't be one, but `alarmEpisodesByCategory` is a raw
# group-by, not validated against this list) is skipped in `_rows()` below
# rather than crashing the report.
_ALARM_CATEGORY_LABEL_KEYS = {
    "Low Battery Alarm": "alarmCategoryLowBattery",
    "Overload Alarm": "alarmCategoryOverload",
}


# ══════════════════════════════════════════════════════════════════
# Render
# ══════════════════════════════════════════════════════════════════
def _rows(d: dict) -> tuple[list, list, list, list, list]:
    t, n = d["t"], len(d["dailyGrouped"])
    fmt = lambda v, nd=1, suf="": f"{v:.{nd}f}{suf}" if v is not None else "—"

    batt = [
        {"label": t["daysFullCharge"],
         "value": f"{d['totals']['daysFullCharge']} / {n} {t['days']}",
         "valueColor": S.GREEN},
        {"label": t["lowestSoc"],
         "value": f"{d['minSoc']:.0f}%" if d["minSoc"] is not None else "—"},
        {"label": t["avgTemp"], "value": fmt(d["avgTemp"], 1, " °C")},
        {"label": t["batteryHealthLabel"],
         # No "(N cyc)" suffix when cycles genuinely can't be computed —
         # "Sin datos (0.0 cyc)" would still assert a number that isn't real.
         "value": (f"{d['battStressLabel']} ({d['batteryCycles']} cyc)"
                   if d["batteryCycles"] is not None else d["battStressLabel"]),
         "valueColor": d["battStressColor"]},
        {"label": t["voltageRange"],
         "value": (f"{d['minVoltage']:.1f} – {d['maxVoltage']:.1f} V"
                   if d["minVoltage"] is not None else "—")},
    ]
    grid = [
        {"label": t["avgFrequency"],
         "value": (f"{d['minFreq']:.2f} – {d['maxFreq']:.2f} Hz"
                   if d["minFreq"] is not None else "—")},
        {"label": t["voltageRangeL1"],
         "value": (f"{d['minVL1']:.1f} – {d['maxVL1']:.1f} V"
                   if d["minVL1"] is not None else "—")},
        {"label": t["voltageRangeL2"],
         "value": (f"{d['minVL2']:.1f} – {d['maxVL2']:.1f} V"
                   if d["minVL2"] is not None else "—")},
        {"label": t["gridDataDays"],
         "value": f"{n - d['totals']['daysNoGridData']} / {n}"},
        {"label": t["gridQualityScore"],
         "value": f"{d['gridQualityScore']}/100 — {d['gridQualityStatus']}",
         "valueColor": d["gridQualityColor"]},
    ]
    oc = d["totals"]["outageCount"]
    events = []
    # "Cortes de Red" implies "we monitor grid outages here and found none" —
    # wrong for a site with no grid concept at all. The underlying detector
    # already returns 0 for a genuinely off-grid site (vrm_daily._grid_outages'
    # own _GRID_SITE_MIN_V/_GRID_SITE_MIN_SHARE guard), so this row must be
    # dropped explicitly rather than relying on "0" to read as "not
    # applicable" — it doesn't. Alarm episodes are a different, still
    # meaningful metric for off-grid (e.g. overload/low-battery alarms) and
    # stay.
    if d["systemType"] != "off_grid":
        events.append({
            "label": t["outages"],
            "value": (t["noOutagesShort"] if oc == 0
                      else f"{oc} ({d['totals']['outageMinutes']} min)"),
            "valueColor": S.AMBER if oc > 0 else "#222",
        })
    events.append({"label": t["alarmEpisodes"], "value": str(d["alarmEpisodesTotal"])})
    # Per-category breakdown (report bug fix, 2026-08-19) — categories with
    # zero episodes are omitted rather than shown as "Batería baja: 0",
    # matching this section's own existing "Sin cortes" convention (a zero
    # row for something that didn't happen is noise, not information).
    # Sorted by count, descending, so the most frequent alarm reads first.
    #
    # Every category in `by_category` gets a row — `_ALARM_CATEGORY_LABEL_KEYS`
    # supplies a translated label for the two known ones (confirmed live,
    # 2026-08-19: 'Low Battery Alarm'/'Overload Alarm' are the only labels
    # that exist in either schema's real `alarm_events` today), and an
    # UNRECOGNISED label — a category added later, or one only `monitoring`
    # ever writes — falls back to its raw stored text rather than being
    # silently dropped. This is not cosmetic: `alarmEpisodesTotal` is the
    # sum of every value in `by_category` (see that variable's own comment,
    # `_build_report_data()`), so silently skipping a row here would make
    # the visible breakdown undercount the Total sitting right above it —
    # the exact bug this feature just replaced, reappearing through a
    # different door.
    by_category = d.get("alarmEpisodesByCategory") or {}
    for alarm_label, count in sorted(by_category.items(), key=lambda kv: -kv[1]):
        if count <= 0:
            continue
        key = _ALARM_CATEGORY_LABEL_KEYS.get(alarm_label)
        display_label = t[key] if key else alarm_label
        events.append({"label": f"— {display_label}", "value": str(count)})
    # A poor Grid Quality score alongside a clean outage count is flagged on
    # the Grid Outages KPI card itself (report_svg.kpi_svg) rather than here —
    # that's the number a reader sees first, so the pointer belongs there,
    # not in a second row an operator could easily miss further down the page.
    # Only on sites configured as exporting. On a site that never feeds back, an
    # always-zero row is noise; on one that does, omitting it hides a large part
    # of its grid interaction.
    if d.get("exportsToGrid"):
        events.append({
            "label": t["gridExport"],
            "value": f"{d['totals']['gridExport']:.1f} {t['kwh']}",
            "valueColor": S.GREEN,
        })

    # Without weather, expected output is a flat 4.5 peak-sun-hours assumption,
    # so the "ratio" is really actual-vs-assumption and lands suspiciously near
    # 100%. Say so rather than presenting it as a measured performance figure.
    has_weather = d["weather"] is not None
    perf = [
        {"label": t["solarActual"], "value": f"{d['totals']['pv']:.1f} {t['kwh']}"},
        {"label": t["solarExpected"] if has_weather else t["solarExpectedEstimated"],
         "value": fmt(d["expectedPv"], 1, f" {t['kwh']}")},
        {"label": t["solarPerformancePct"],
         "value": (f"{d['solarPerformancePct']}%" if d["solarPerformancePct"] is not None
                   else "—") + ("" if has_weather else f" · {t['weatherFallbackNote']}"),
         "valueColor": ("#999" if not has_weather else
                        S.GREEN if (d["solarPerformancePct"] or 0) >= 90
                        else S.AMBER if (d["solarPerformancePct"] or 0) >= 70 else S.RED)},
    ]
    w = d["weather"]
    weather = ([
        {"label": t["weatherSunshine"], "value": f"{w['avgSunshineHrs']} hrs/day"},
        {"label": t["weatherRainDays"], "value": f"{w['rainyDays']} days (>5mm)"},
        {"label": t["weatherCloudCover"], "value": f"{w['avgCloudPct']}%"},
    ] if w else [{"label": t["weatherUnavailable"], "value": ""}])
    return batt, grid, events, perf, weather


# PLAN_PHASE18.md §7 item 9 — same shape/reasoning as _ALARM_CATEGORY_LABEL_KEYS
# above, over vrm.critical_alerts' `category` values instead of alarm_events'
# `alarm` labels.
_CRITICAL_CATEGORY_LABEL_KEYS = {
    "dc_ripple": "criticalDcRipple",
    "cell_imbalance": "criticalCellImbalance",
    "temp_fault": "criticalTempFault",
}


def _phase2_rows(d: dict) -> tuple[list, list, list, list]:
    """PLAN_PHASE18.md §7 — rows for the four Phase 2 modules, same
    `[{"label", "value", ...}]` shape `_rows()` above builds for the
    original nine so `S.single_block_row_svg()`/`S.two_block_row_svg()`
    render them identically. Every one of these renders SOMETHING even when
    the underlying signal has never reported for this site (Oscar's own
    instruction, 2026-08-29) — zero counts, "0.0 hrs", or an explicit
    "not detected" row, never an empty block.
    """
    t = d["t"]
    by_category = d.get("criticalAlertsByCategory") or {}
    critical = []
    for cat_id, key in _CRITICAL_CATEGORY_LABEL_KEYS.items():
        count = by_category.get(cat_id, 0)
        critical.append({"label": t[key], "value": str(count),
                         "valueColor": S.AMBER if count > 0 else "#222"})

    gm = d.get("gridMeterDetail") or {}
    if gm:
        phase_key = {"l1": "gridMeterPhaseL1", "l2": "gridMeterPhaseL2", "l3": "gridMeterPhaseL3"}
        grid_meter_rows = []
        for phase in ("l1", "l2", "l3"):
            stats = gm.get(phase)
            if not stats:
                continue
            v = f"{stats['v_avg']:.1f} V" if stats.get("v_avg") is not None else "—"
            c = f"{stats['c_avg']:.1f} A" if stats.get("c_avg") is not None else "—"
            pf = f"PF {stats['pf_avg']:.2f}" if stats.get("pf_avg") is not None else ""
            grid_meter_rows.append({"label": t[phase_key[phase]],
                                    "value": " · ".join(x for x in (v, c, pf) if x)})
    else:
        grid_meter_rows = [{"label": t["gridMeterUnavailable"], "value": ""}]

    generator_hours = [
        {"label": t["generatorHours"],
         "value": f"{d.get('generatorHoursTotal', 0.0):.1f} {t['generatorHoursUnit']}"},
    ]

    tank = d.get("tankDetail") or {}
    if d.get("hasTank"):
        tank_rows = [
            {"label": t["tankCapacity"],
             "value": f"{tank['capacity_m3']:.2f} m³" if tank.get("capacity_m3") is not None else "—"},
            {"label": t["tankFluidType"], "value": tank.get("fluid_type") or "—"},
            {"label": t["tankStatus"], "value": tank.get("status") or "—"},
            {"label": t["tankLevel"],
             "value": f"{tank['level_pct']:.0f}%" if tank.get("level_pct") is not None else "—"},
        ]
    else:
        tank_rows = [{"label": t["tankUnavailable"], "value": ""}]

    return critical, grid_meter_rows, generator_hours, tank_rows


def render_html(d: dict, selected: set[str] | None = None) -> str:
    """`selected` is the OUTPUT of `vrm_api.report_modules.resolve_report_modules()`
    (PLAN_PHASE18.md §3) — a set of module ids to actually render, already
    resolved against tier/entitlement by that function. This function never
    resolves entitlement itself and never reads a customer's raw
    `report_modules` column — same "receives the ALREADY-RESOLVED output,
    never the raw stored value" shape `branding` (below) already uses.
    `None` (every caller before this feature existed, and any caller that
    hasn't been updated yet) means `DEFAULT_MODULES` — the original 9
    modules (today's exact, unchanged pre-Phase-18 behavior) plus
    `critical_alerts` (Oscar's own decision, 2026-08-29: safety-relevant
    enough to show every customer by default) — NOT the full
    `ALL_MODULES`, which would also silently add grid_meter_detail/
    generator_runtime/tank_level boilerplate to every report that has
    never customized its selection. Not an entitlement decision made here
    either way — see `resolve_report_modules()`, which makes the same
    `DEFAULT_MODULES` choice for every non-entitled/never-customized
    customer.

    KPI header / narrative / daily bar chart are never gated by `selected`
    at all — they're the report's fixed spine (PLAN_PHASE18.md's Decisions
    section), not a selectable module.

    `energy_mix` and `battery_health` are independent even though they
    share a row when both are on: `energy_mix_full_svg()` (Solar/Grid,
    `grid_zero` only) and `energy_mix_full_svg_3way()` (Solar/Battery/Grid,
    any `has_batt` system) both exist as real full-width-alone renderers
    (PLAN_PHASE18.md §4), so no combination of the two falls back to
    showing more than was actually selected.
    """
    if selected is None:
        selected = set(DEFAULT_MODULES)
    t = d["t"]
    # PLAN_PHASE17.md §4 — `d["branding"]` is either `None` (every
    # `monitoring` report, every pre-Phase-17 caller, and any `vrm` report
    # whose customer isn't white-labeled/entitled — see
    # vrm_api/branding.py:resolve_branding()) or the already-validated,
    # render-ready dict that function returns. `.get(...)` on `branding`
    # itself (not `d`) is what makes every one of these four lines a no-op
    # when `branding` is `None` — the template's own defaults (the literal
    # "Pauly & Co." / #1FAE6E / proyectos@paulyco.com strings, unchanged
    # from before this feature existed) apply exactly as they always have.
    branding = d.get("branding") or {}
    company_name = branding.get("company_name") or "Pauly & Co."
    brand_color = branding.get("primary_color") or "#1FAE6E"
    contact_email = branding.get("contact_email") or "proyectos@paulyco.com"
    logo_b64 = branding.get("logo_b64") or get_logo_b64()
    batt, grid, events, perf, weather = _rows(d)
    critical, grid_meter_rows, generator_hours_rows, tank_rows = _phase2_rows(d)
    has_grid = d["systemType"] in ("grid_zero", "hybrid")
    has_batt = d["systemType"] in ("off_grid", "hybrid")

    savings_rows = None
    if d.get("savings"):
        sv = d["savings"]
        basis = (t["savingsBasisCr"].format(n=sv["basisCount"])
                if sv["basisCount"] is not None else t["savingsBasisFlat"])
        savings_rows = [
            {"label": t["savingsThisWeek"],
             "value": savings_mod.format_money(sv["amount"], sv["currency"]),
             "valueColor": S.GREEN},
            {"label": t["savingsBasisLabel"], "value": basis},
        ]

    # One row font size for the whole report. Sizing each row independently
    # fits tighter but reads as a rendering glitch — a single shrunken line
    # beside full-size neighbours. Solved once here, applied everywhere.
    # PLAN_PHASE18.md §7 — computed here, ahead of `groups` below, so an
    # UNSELECTED Phase 2 module's row content never enters the uniform-size
    # pass at all. Getting this wrong would be a real regression: `batt`/
    # `events`/`perf`/`weather`/`grid` below are Phase 1's own pre-existing
    # groups and are (already, since before this feature existed) always
    # included regardless of `selected` — that was already true when this
    # function had no `selected` parameter at all, so it changes nothing for
    # an existing customer. These four are NEW as of Phase 2, so
    # unconditionally adding them here would size EVERY report — including
    # one that selects none of them — against text that may never render.
    want_critical = "critical_alerts" in selected
    want_grid_meter = "grid_meter_detail" in selected
    want_generator = "generator_runtime" in selected
    want_tank = "tank_level" in selected

    # Page 2's "pool" — every plain info-block module below the SOC/trend
    # charts (PLAN_PHASE18.md §7, real live-test feedback 2026-08-29:
    # Weather/Critical Alerts/Generator Runtime each rendered full-width
    # ALONE whenever their old fixed partner — solar_performance/grid_meter_
    # detail/tank_level respectively — wasn't also selected, wasting half
    # the page). Rather than 4 fixed pairs, every selected pool module packs
    # two-per-row in this fixed priority order, with only a genuinely odd
    # one out ever going full-width. `want_solar_perf`/`want_weather` are
    # computed here (they used to be computed just before `row3` further
    # down) so `pool_specs` can be built once, in the same place `groups`
    # reads it — see `_pack_pool()` below for how a spec becomes SVG.
    want_solar_perf = "solar_performance" in selected
    want_weather = "weather" in selected
    want_savings = "savings" in selected
    events_sub = (t["subEventsOffGrid"] if d["systemType"] == "off_grid"
                 else t["subEvents"])
    savings_sub = (t["subSavingsOffGrid"] if d["systemType"] == "off_grid"
                  else t["subSavings"])

    pool_specs: list[dict] = []
    if want_solar_perf:
        pool_specs.append({"title": t["solarPerformance"], "rows": perf, "sub": t["subSolarPerf"]})
    if want_weather:
        pool_specs.append({"title": t["weatherTitle"], "rows": weather, "sub": t["subWeather"],
                           "right_bg": S.BG_MINT if d["weather"] else S.BG_GREY})
    # Only the REAL savings block is poolable — the "not configured yet"
    # placeholder (`savings_placeholder_svg`) is a bespoke full-width-only
    # SVG with no half-width form, so it stays its own always-full-width row
    # exactly as before, outside the pool.
    if want_savings and savings_rows:
        pool_specs.append({"title": t["tariffSavings"], "rows": savings_rows, "sub": savings_sub})
    if want_critical:
        pool_specs.append({"title": t["sectionCriticalAlerts"], "rows": critical, "sub": t["subCriticalAlerts"]})
    if want_grid_meter:
        pool_specs.append({"title": t["sectionGridMeter"], "rows": grid_meter_rows, "sub": t["subGridMeter"]})
    if want_generator:
        pool_specs.append({"title": t["sectionGenerator"], "rows": generator_hours_rows, "sub": t["subGenerator"]})
    if want_tank:
        pool_specs.append({"title": t["sectionTank"], "rows": tank_rows, "sub": t["subTank"]})

    half, full = S.IW - 2 * S.IPAD, S.PW - 2 * S.IPAD
    groups = [(batt, half), (events, half)]
    groups.append((grid, half if has_grid else full))
    groups.extend((spec["rows"], half) for spec in pool_specs)
    row_size = S.uniform_row_size(groups)

    # The savings placeholder ("not configured yet") has no half-width form
    # (see the pool-building comment above) — rendered on its own, outside
    # the pool, exactly as before. When real savings data exists, it was
    # already appended to `pool_specs` above instead.
    savings_svg = S.savings_placeholder_svg(t) if (want_savings and not savings_rows) else ""

    # Same pattern as `subSavingsOffGrid` above: the Events caption still
    # said "Registra los cortes de red..." even after the outages row itself
    # was dropped from `events` for off_grid (Bug 2's fix removed the row but
    # missed this static caption, which then contradicted its own section —
    # caught by inspecting the actual rendered PDF, not just the code).
    want_grid_quality = "grid_quality" in selected and has_grid
    want_events = "events" in selected
    if want_grid_quality and want_events:
        row2 = S.two_block_row_svg(t["sectionGrid"], grid, t["subGrid"],
                                   t["sectionEvents"], events, events_sub,
                                   row_size=row_size)
    elif want_events:
        # No grid to assess, or grid_quality deselected — Events takes the
        # full width rather than sitting beside an empty half.
        row2 = S.single_block_row_svg(t["sectionEvents"], events, events_sub,
                                      row_size=row_size)
    elif want_grid_quality:
        row2 = S.single_block_row_svg(t["sectionGrid"], grid, t["subGrid"],
                                      row_size=row_size)
    else:
        row2 = ""

    # Pack `pool_specs` two-per-row (PLAN_PHASE18.md §7, 2026-08-29 live-test
    # feedback) — a genuinely odd one out is the ONLY case that still goes
    # full-width alone. `right_bg` (currently only Weather sets it) only
    # applies when that spec lands in the RIGHT slot of a pair —
    # `two_block_row_svg` has no equivalent left-side param, so a spec that
    # lands on the left keeps the function's own default background. A
    # cosmetic limitation (Weather's "real data" mint tint doesn't show up
    # when Weather happens to pack on the left), not a correctness one.
    packed_svgs: list[str] = []
    i = 0
    while i < len(pool_specs):
        if i + 1 < len(pool_specs):
            left, right = pool_specs[i], pool_specs[i + 1]
            packed_svgs.append(S.two_block_row_svg(
                left["title"], left["rows"], left["sub"],
                right["title"], right["rows"], right["sub"],
                right_bg=right.get("right_bg", S.BG_GREY),
                row_size=row_size,
            ))
            i += 2
        else:
            only = pool_specs[i]
            packed_svgs.append(S.single_block_row_svg(
                only["title"], only["rows"], only["sub"], row_size=row_size))
            i += 1

    # Row 1 — energy mix + battery health, independently selectable.
    want_energy_mix = "energy_mix" in selected
    want_battery_health = "battery_health" in selected and has_batt
    if not has_batt:
        # grid_zero — battery_health never applies regardless of selection.
        row1_svg = S.energy_mix_full_svg(d, t) if want_energy_mix else ""
    elif want_energy_mix and want_battery_health:
        row1_svg = S.row1_svg(d, t, batt, row_size=row_size)
    elif want_battery_health:
        row1_svg = S.single_block_row_svg(t["sectionBattery"], batt, t["subBattery"], row_size=row_size)
    elif want_energy_mix:
        row1_svg = S.energy_mix_full_svg_3way(d, t)
    else:
        row1_svg = ""

    env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR),
                      autoescape=select_autoescape(["html"]))
    tpl = env.get_template("weekly_report.html")
    return tpl.render(
        lang=d["lang"], t=t, site_name=d["siteName"],
        start_str=d["startStr"], end_str=d["endStr"],
        # `logo_b64` is either the customer's own uploaded logo (already
        # base64-encoded by resolve_branding()) or, same as before this
        # feature existed, the shared Pauly & Co asset the proposal PDFs
        # also use (proposals/assets/assets.py) — one shared source, so an
        # UNBRANDED report's logo can never drift between the two PDF
        # families (PLAN_PHASE17.md §4).
        logo_b64=logo_b64,
        company_name=company_name,
        brand_color=brand_color,
        contact_email=contact_email,
        narrative_paragraphs=[p for p in (d["narrative"] or "").split("\n") if p.strip()],
        # Pre-built SVG must not be HTML-escaped by autoescape. KPI header /
        # bar chart are the fixed spine — never gated by `selected` at all.
        kpi_svg=_safe(S.kpi_svg(d, t)),
        bar_svg=_safe(S.bar_chart_svg(d, t)),
        # A system with no battery (grid_zero) still has a meaningful energy
        # mix — Solar vs. Grid — so this is a real report block, not a
        # meaningless one hidden behind has_grid the way the battery/SOC
        # blocks are hidden behind has_batt elsewhere in this function. The
        # earlier version put Grid Quality here instead, which duplicated the
        # Grid Quality block row2 already renders for any grid-connected
        # system — found by checking system_type behaviour end to end, not
        # by a report ever actually being generated for a grid_zero site.
        row1_svg=_safe(row1_svg) if row1_svg else "",
        row2_svg=_safe(row2) if row2 else "",
        soc_svg=(_safe(S.soc_chart_svg(d, t)) if (has_batt and "soc_chart" in selected) else ""),
        trend_svg=(_safe(S.four_week_trend_svg(d["trend"], t)) if "trend" in selected else ""),
        savings_svg=_safe(savings_svg) if savings_svg else "",
        # PLAN_PHASE18.md §7, 2026-08-29 live-test feedback — replaces the
        # old fixed row3/row4/row5 slots with a dynamically-sized, packed
        # list (see `packed_svgs`'s own construction above).
        packed_svgs=[_safe(s) for s in packed_svgs],
    )


def _safe(s: str):
    from markupsafe import Markup
    return Markup(s)


def render_pdf(d: dict, selected: set[str] | None = None) -> bytes:
    """HTML → PDF via WeasyPrint, replacing Apps Script's
    `newBlob(html, 'text/html').getAs('application/pdf')`. `selected` is
    plain pass-through to `render_html()` — see that function's own
    docstring."""
    from weasyprint import HTML
    return HTML(string=render_html(d, selected)).write_pdf()


def generate(site_id: str, start: str | date, end: str | date, schema: str,
             with_narrative: bool = True, with_weather: bool = True,
             selected: set[str] | None = None) -> bytes:
    return render_pdf(build_report_data(site_id, start, end, schema,
                                        with_narrative=with_narrative,
                                        with_weather=with_weather),
                      selected)
