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
import os
import urllib.parse
import urllib.request
from datetime import date

from jinja2 import Environment, FileSystemLoader, select_autoescape

from database import vrm_report_db as db
from victron import report_i18n, report_svg as S

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_SYSTEM_EFF = 0.80          # same derating the original uses
_FALLBACK_PEAK_SUN_HRS = 4.5  # CR average, used when weather is unavailable
_NARRATIVE_MODEL = "claude-sonnet-4-6"


# ══════════════════════════════════════════════════════════════════
# Weather
# ══════════════════════════════════════════════════════════════════
def fetch_weather(lat: float, lng: float, start: str, end: str,
                  timezone: str = "America/Costa_Rica") -> dict | None:
    """Open-Meteo archive, same endpoint and fields as the original.

    Returns None on any failure — the report must still render without it, and
    the weather block has its own "unavailable" state.
    """
    params = {
        "latitude": f"{float(lat):.4f}", "longitude": f"{float(lng):.4f}",
        "start_date": str(start), "end_date": str(end),
        "daily": "sunshine_duration,precipitation_sum,cloud_cover_mean,"
                 "shortwave_radiation_sum",
        "timezone": timezone,
    }
    url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            if r.status != 200:
                return None
            daily = json.loads(r.read()).get("daily") or {}
    except Exception:
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
def generate_narrative(stats: dict, lang: str) -> str:
    """Port of `generateWeeklyNarrative()` — same prompt, same fail-soft.

    A missing key or an API error returns a placeholder rather than raising:
    the report is the deliverable, and losing one paragraph must not lose it.
    """
    t = report_i18n.get(lang)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return t["narrativeNoKey"]

    prompt = (
        "You are writing the weekly insights paragraph for a residential "
        f"solar+battery monitoring report. {t['narrativeLang']}"
        "\n\nWrite exactly 2 short paragraphs (60-90 words total). Plain prose "
        "only - no headers, no bullets, no markdown."
        " Warm, professional tone. Be specific with numbers. Lead with the most "
        "meaningful story of the week."
        " If the battery kept the home running during outages, say so. End with "
        "one forward-looking sentence if warranted."
        "\n\nThis week's data:"
        f"\n- Site: {stats['site']}"
        f"\n- Solar generated: {stats['pv']} kWh"
        f"\n- Total consumption: {stats['load']} kWh"
        f"\n- Grid consumption: {stats['grid']} kWh"
        f"\n- Grid independence: {stats['gridIndependencePct']}%"
        f"\n- Health score: {stats['healthScore']}/100 ({stats['healthStatus']})"
        f"\n- Lowest battery SOC: {stats['minSoc']}%"
        f"\n- Battery cycles this week: {stats['batteryCycles']}"
        f"\n- Days battery reached full charge: {stats['daysFullCharge']} of {stats['totalDays']}"
        f"\n- Grid outages: {stats['outageCount']} ({stats['outageMinutes']} minutes total)"
        f"\n- Longest single outage: {stats['longestOutageMinutes']} minutes"
        f"\n- Battery covered loads during outages: "
        f"{'yes' if stats['batteryProtectedDuringOutage'] else 'no / unknown'}"
        f"\n- Alarm episodes: {stats['alarmEpisodes']}"
        f"\n- Best production day: {stats['bestDay']} kWh"
        f"\n- Worst production day: {stats['worstDay']} kWh"
    )
    if stats.get("weatherAvailable"):
        prompt += (
            f"\n- Weather: avg {stats['avgSunshineHrs']} sunshine hrs/day, days "
            f"with significant rain (>5mm): {stats['rainyDays']}, avg cloud "
            f"cover: {stats['avgCloudPct']}%."
            " If weather affected generation, mention it."
            f"\n- Solar performance ratio: {stats['solarPerformancePct']}% of expected"
        )
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


def build_report_data(site_id: str, week_ending: str | date, schema: str,
                      with_narrative: bool = True,
                      with_weather: bool = True) -> dict:
    """Everything the template needs. Port of `weeklyReport()`'s computation."""
    window = db.fetch_report_window(site_id, week_ending, schema)
    site = window["site"]
    days = window["days"]
    if not days:
        raise ValueError(
            f"No energy_daily rows for {site_id!r} between "
            f"{window['period_start']} and {window['period_end']}"
        )

    lang = (site.get("report_language") or "en").lower()
    lang = "es" if lang == "es" else "en"
    t = report_i18n.get(lang)
    system_type = site.get("system_type") or "hybrid"

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
    min_f, _ = _minmax(days, "min_grid_freq")
    _, max_f = _minmax(days, "max_grid_freq")
    min_l1, _ = _minmax(days, "min_grid_v_l1")
    _, max_l1 = _minmax(days, "max_grid_v_l1")
    min_l2, _ = _minmax(days, "min_grid_v_l2")
    _, max_l2 = _minmax(days, "max_grid_v_l2")

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
        alarm_total = sum(int(_num(r.get("alarms_count"))) for r in grouped)

    grid_independence = (round(100 - totals["grid"] / totals["load"] * 100, 1)
                         if totals["load"] > 0 else 100)
    batt_usable = _num(site.get("battery_usable_kwh"), 0) or 1
    battery_cycles = round(totals["discharge"] / batt_usable, 2)
    longest_outage = window["longest_outage_minutes"]

    weather = None
    if with_weather and site.get("latitude") is not None:
        weather = fetch_weather(site["latitude"], site["longitude"],
                                window["period_start"], window["period_end"],
                                site.get("timezone") or "America/Costa_Rica")

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
    thr = {"batteryCyclesHigh": 10.0, "batteryCyclesMid": 7.0}
    thr.update(site.get("health_thresholds") or {})
    if battery_cycles > thr["batteryCyclesHigh"]:
        stress = "Alto estrés" if lang == "es" else "High stress"
    elif battery_cycles > thr["batteryCyclesMid"]:
        stress = "Uso activo" if lang == "es" else "Working hard"
    else:
        stress = "Normal"
    stress_color = S.AMBER if battery_cycles > thr["batteryCyclesMid"] else S.GREEN

    narrative = ""
    if with_narrative:
        narrative = generate_narrative({
            "site": site["display_name"], "pv": f"{totals['pv']:.1f}",
            "load": f"{totals['load']:.1f}", "grid": f"{totals['grid']:.1f}",
            "gridIndependencePct": grid_independence,
            "healthScore": avg_health, "healthStatus": health_status,
            "minSoc": min_soc, "batteryCycles": battery_cycles,
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
        }, lang)

    return {
        "t": t, "lang": lang, "schema": schema, "systemType": system_type,
        "site": site, "siteName": site["display_name"],
        "startStr": window["period_start"], "endStr": window["period_end"],
        "dailyGrouped": days, "totals": totals, "prevTotals": prev_totals,
        "avgHealth": avg_health, "healthStatus": health_status,
        "alarmEpisodesTotal": alarm_total,
        "gridIndependencePct": grid_independence, "batteryCycles": battery_cycles,
        "minSoc": min_soc, "maxSoc": max_soc,
        "minVoltage": min_v, "maxVoltage": max_v, "maxTemp": max_temp,
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
        "trend": window["trend"],
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
        {"label": t["avgTemp"], "value": fmt(d["maxTemp"], 1, " °C")},
        {"label": t["batteryHealthLabel"],
         "value": f"{d['battStressLabel']} ({d['batteryCycles']} cyc)",
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
    events = [
        {"label": t["outages"],
         "value": (t["noOutagesShort"] if oc == 0
                   else f"{oc} ({d['totals']['outageMinutes']} min)"),
         "valueColor": S.AMBER if oc > 0 else "#222"},
        {"label": t["alarmEpisodes"], "value": str(d["alarmEpisodesTotal"])},
    ]
    perf = [
        {"label": t["solarActual"], "value": f"{d['totals']['pv']:.1f} {t['kwh']}"},
        {"label": t["solarExpected"], "value": fmt(d["expectedPv"], 1, f" {t['kwh']}")},
        {"label": t["solarPerformancePct"],
         "value": f"{d['solarPerformancePct']}%" if d["solarPerformancePct"] is not None else "—",
         "valueColor": (S.GREEN if (d["solarPerformancePct"] or 0) >= 90
                        else S.AMBER if (d["solarPerformancePct"] or 0) >= 70 else S.RED)},
    ]
    w = d["weather"]
    weather = ([
        {"label": t["weatherSunshine"], "value": f"{w['avgSunshineHrs']} hrs/day"},
        {"label": t["weatherRainDays"], "value": f"{w['rainyDays']} days (>5mm)"},
        {"label": t["weatherCloudCover"], "value": f"{w['avgCloudPct']}%"},
    ] if w else [{"label": t["weatherUnavailable"], "value": ""}])
    return batt, grid, events, perf, weather


def render_html(d: dict) -> str:
    t = d["t"]
    batt, grid, events, perf, weather = _rows(d)
    has_grid = d["systemType"] in ("grid_zero", "hybrid")
    has_batt = d["systemType"] in ("off_grid", "hybrid")

    if has_grid:
        row2 = S.two_block_row_svg(t["sectionGrid"], grid, t["subGrid"],
                                   t["sectionEvents"], events, t["subEvents"])
    else:
        # No grid to assess — Events takes the full width rather than sitting
        # beside an empty half.
        row2 = S.single_block_row_svg(t["sectionEvents"], events, t["subEvents"])

    row3 = S.two_block_row_svg(
        t["solarPerformance"], perf, t["subSolarPerf"],
        t["weatherTitle"], weather, t["subWeather"],
        right_bg=S.BG_MINT if d["weather"] else S.BG_GREY,
    )

    env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR),
                      autoescape=select_autoescape(["html"]))
    tpl = env.get_template("weekly_report.html")
    return tpl.render(
        lang=d["lang"], t=t, site_name=d["siteName"],
        start_str=d["startStr"], end_str=d["endStr"],
        narrative_paragraphs=[p for p in (d["narrative"] or "").split("\n") if p.strip()],
        # Pre-built SVG must not be HTML-escaped by autoescape.
        kpi_svg=_safe(S.kpi_svg(d, t)),
        bar_svg=_safe(S.bar_chart_svg(d, t)),
        row1_svg=_safe(S.row1_svg(d, t, batt) if has_batt
                       else S.single_block_row_svg(t["sectionGrid"], grid, t["subGrid"])),
        row2_svg=_safe(row2),
        soc_svg=_safe(S.soc_chart_svg(d, t)) if has_batt else "",
        row3_svg=_safe(row3),
        trend_svg=_safe(S.four_week_trend_svg(d["trend"], t)),
        savings_svg=_safe(S.savings_placeholder_svg(t)),
    )


def _safe(s: str):
    from markupsafe import Markup
    return Markup(s)


def render_pdf(d: dict) -> bytes:
    """HTML → PDF via WeasyPrint, replacing Apps Script's
    `newBlob(html, 'text/html').getAs('application/pdf')`."""
    from weasyprint import HTML
    return HTML(string=render_html(d)).write_pdf()


def generate(site_id: str, week_ending: str | date, schema: str,
             with_narrative: bool = True, with_weather: bool = True) -> bytes:
    return render_pdf(build_report_data(site_id, week_ending, schema,
                                        with_narrative=with_narrative,
                                        with_weather=with_weather))
