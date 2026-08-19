from __future__ import annotations
"""
Report strings, ported from Apps Script's TRANSLATIONS
(`victron-monitor/apps-script/Victron_Events_App_Script_v1p7.js` ~lines 395-590).

English is complete and is what the V1 port targets. Spanish keys are carried
over verbatim from the same source so the `es` template can be finished without
re-deriving them, but the `es` layout has not been verified against a reference
PDF yet — see the plan doc.
"""

EN = {
    "reportTitle": "Weekly Energy Report",
    "reportSubtitle": "Reporte semanal de energía",
    "dateRange": "Reporting period",
    "healthScore": "Weekly Health Score",
    "healthStatus": {"Excellent": "Excellent", "Good": "Good",
                     "Watch": "Watch", "Attention": "Attention"},
    "sectionBattery": "Battery Health",
    "sectionGrid": "Grid Quality",
    "sectionEvents": "Events this week",
    "sectionDaily": "Daily solar vs. consumption",
    "pvGenerated": "Solar Generated",
    "bestDayLabel": "Best",
    "gridIndependence": "Grid Independence",
    "lowestSoc": "Lowest SOC of the Week",
    "daysFullCharge": "Days Battery Reached Full Charge",
    "avgFrequency": "Grid Frequency Range",
    "voltageRangeL1": "Voltage Range L1",
    "voltageRangeL2": "Voltage Range L2",
    "gridDataDays": "Days With Grid Data",
    "alarmEpisodes": "Total Alarm Episodes",
    # Display labels for `alarm_events.alarm`'s two scored categories
    # (`victron/vrm_csv.py:ALARM_CATEGORIES`) — the Events section's
    # per-category breakdown (report bug fix, 2026-08-19). Shorter than the
    # stored label ("Low Battery Alarm") since the section header already
    # says "alarm episodes", so repeating "Alarm" on every row is noise.
    "alarmCategoryLowBattery": "Low battery",
    "alarmCategoryOverload": "Overload",
    "outages": "Grid Outages",
    "noOutagesShort": "No outages",
    # Outages come only from the device's own Grid alarm flag — a brief
    # frequency/voltage excursion the device didn't treat as a full loss
    # won't set it, even though it's exactly what tanks the Grid Quality
    # score below. Shown on the Grid Outages KPI card itself (the number a
    # reader sees first) when that happens, so "No outages" doesn't read as a
    # clean bill of health. Kept short — this sits in the KPI card's one-line
    # sub-label slot, which has no wrap or truncation.
    "outagesGridQualityNote": "See Grid Quality",
    "minutes": "minutes",
    "days": "days",
    "kwh": "kWh",
    "energyMix": "Where your energy came from",
    "avgTemp": "Avg temperature",
    "voltageRange": "Voltage range",
    "weatherTitle": "Weather this week",
    "weatherSunshine": "Avg sunshine",
    "weatherRainDays": "Significant rain days",
    "weatherCloudCover": "Avg cloud cover",
    "weatherUnavailable": "Weather data unavailable",
    "wowTrendLabel": "vs prev",
    "socTimeline": "Battery SOC this week",
    "solarPerformance": "Solar performance",
    "solarExpected": "Expected output",
    "solarActual": "Actual output",
    "solarPerformancePct": "Performance ratio",
    "gridQualityScore": "Grid quality score",
    "batteryHealthLabel": "Battery stress",
    "subDaily": "Compares daily solar production against household consumption "
                "for each day this week.",
    "subEnergyMix": "Shows how much of your energy came from solar panels, "
                    "batteries, and the utility grid.",
    "subBattery": "Tracks how well your batteries charged and discharged "
                  "throughout the week.",
    "subGrid": "Measures the quality and stability of the utility grid supply "
               "at your site.",
    "subEvents": "Logs grid outages and alarm events recorded by the system "
                 "this week.",
    # Period-neutral, unlike `subEvents` above (no "this week"/"this period"
    # distinction needed) — same reason `subSavingsOffGrid` only needs one
    # definition per language rather than one per num_days/is_overview
    # combination: off-grid wording doesn't vary by report length.
    "subEventsOffGrid": "Logs alarm events recorded by the system during "
                        "this period. This site has no grid connection.",
    "subSocChart": "Shows the daily high and low battery charge level — a dip "
                   "below 20% signals heavy use.",
    "subSolarPerf": "Compares real solar production to the theoretical maximum "
                    "based on your panel capacity and available sunlight.",
    "subWeather": "Local weather conditions for the week — cloud cover and rain "
                  "directly reduce solar output.",
    "labelSolar": "Solar",
    "labelBattery": "Battery",
    "labelGrid": "Grid",
    "labelConsumption": "Consumption",
    "labelMaxSocBand": "Max SOC (band)",
    "labelMinSoc": "Min SOC",
    "dayAbbr": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    "gridExport": "Energy Exported to Grid",
    "gridExportKpi": "Energy Exported",
    "ofGeneration": "of generation",
    # Off-grid-only KPI cards (report bug fix, 2026-08-18) — replace the
    # grid-independence/outage cards that have no meaning without a grid.
    "inverterShutdowns": "Inverter Shutdowns",
    # KPI-card sub-labels render on one unwrapped line — see report_svg.py's
    # kpi_svg() `sub()` helper — so these must stay short (~35 chars max,
    # calibrated against a real generated report; a full-sentence caption
    # like the original draft here overflowed past the card's edge).
    # Shortened 2026-08-19: the original text overflowed the card's own
    # width (text_width() at font-size 8: 115.1 vs. ~113.5 available) —
    # caught from the actual rendered PDF, not the source alone.
    "inverterShutdownsSubZero": "Uninterrupted power",
    "inverterShutdownsSub": "Low-battery shutdown(s)",
    "batteryAutonomy": "Battery Autonomy",
    "batteryAutonomyUnit": "days",
    "batteryAutonomySub": "Battery reserve with no sun",
    "batteryAutonomyUnavailable": "not enough data",
    # Battery stress' third state (report bug fix, 2026-08-18): distinct from
    # "Normal" — battery_charge_kwh/battery_discharge_kwh are NULL on every
    # row for this ingestion path/window, so cycles genuinely cannot be
    # computed, which must not read as a scored "Normal (0.0 cyc)".
    "battStressNoData": "No data",
    "solarExpectedEstimated": "Expected output (estimated)",
    "weatherFallbackNote": "no weather data — estimate only",
    "fourWeekChart": "4-week solar trend",
    "sub4Week": "Compares solar production across the past 4 weeks to help spot "
                "seasonal trends.",
    "trendNote": "▲▼ = change in that week's solar production vs. the previous "
                 "week (mostly driven by weather).",
    "tariffSavings": "Estimated savings",
    "tariffComingSoon": "Tariff data coming soon",
    "savingsThisWeek": "This week",
    "savingsBasisLabel": "Basis",
    "savingsBasisCr": "Average of {n} Costa Rica T-RE tariffs",
    "savingsBasisFlat": "Configured rate",
    "subSavingsOffGrid": "This site has no grid connection. Estimated cost "
                         "avoided by using solar instead of buying this "
                         "energy from the grid, had the site been connected.",
    "subSavings": "Estimated electricity cost avoided this week by using solar "
                  "instead of buying from the grid.",
    "comingSoonValue": "— soon",
    "poweredBy": "Monitoring powered by Pauly & Co.",
    "pageOf": "Page",
    "narrativeLang": "Respond in English, in a professional but approachable tone.",
    "narrativeUnavailable": "Narrative unavailable this week.",
    "narrativeNoKey": "Narrative unavailable (API key not configured).",
}

ES = dict(EN, **{
    "reportTitle": "Reporte Semanal de Energía",
    "reportSubtitle": "Weekly energy report",
    "dateRange": "Periodo del reporte",
    "healthScore": "Puntaje de Salud Semanal",
    "healthStatus": {"Excellent": "Excelente", "Good": "Bueno",
                     "Watch": "Vigilar", "Attention": "Atención"},
    "sectionBattery": "Salud de la Batería",
    "sectionGrid": "Calidad de la Red",
    "sectionEvents": "Eventos de la semana",
    "sectionDaily": "Solar vs. consumo diario",
    "pvGenerated": "Generación Solar",
    "bestDayLabel": "Mejor",
    "gridIndependence": "Independencia de la Red",
    "lowestSoc": "SOC Mínimo de la Semana",
    "daysFullCharge": "Días que la Batería Cargó Completa",
    "avgFrequency": "Rango de Frecuencia de Red",
    "voltageRangeL1": "Rango de Voltaje L1",
    "voltageRangeL2": "Rango de Voltaje L2",
    "gridDataDays": "Días con Datos de Red",
    "alarmEpisodes": "Total de Episodios de Alarma",
    "alarmCategoryLowBattery": "Batería baja",
    "alarmCategoryOverload": "Sobrecarga",
    "outages": "Cortes de Red",
    "noOutagesShort": "Sin cortes",
    "outagesGridQualityNote": "Ver Calidad de Red",
    "minutes": "minutos",
    "days": "días",
    "energyMix": "De dónde vino su energía",
    "avgTemp": "Temperatura promedio",
    "voltageRange": "Rango de voltaje",
    "weatherTitle": "Clima de la semana",
    "weatherSunshine": "Sol promedio",
    "weatherRainDays": "Días con lluvia significativa",
    "weatherCloudCover": "Nubosidad promedio",
    "weatherUnavailable": "Datos de clima no disponibles",
    "wowTrendLabel": "vs ant",
    "socTimeline": "SOC de la batería esta semana",
    "solarPerformance": "Rendimiento solar",
    "solarExpected": "Producción esperada",
    "solarActual": "Producción real",
    "solarPerformancePct": "Índice de rendimiento",
    "gridQualityScore": "Puntaje de calidad de red",
    "batteryHealthLabel": "Estrés de batería",
    "labelBattery": "Batería",
    "labelGrid": "Red",
    "labelConsumption": "Consumo",
    "dayAbbr": ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"],
    # Block subtitles. These inherit from EN via the dict(EN, **{...}) spread,
    # so anything not overridden here silently renders in English inside an
    # otherwise-Spanish report.
    "subDaily": "Compara la producción solar diaria contra el consumo de la "
                "propiedad para cada día de esta semana.",
    "subEnergyMix": "Muestra cuánta de su energía vino de los paneles solares, "
                    "las baterías y la red eléctrica.",
    "subBattery": "Indica qué tan bien cargaron y descargaron sus baterías "
                  "durante la semana.",
    "subGrid": "Mide la calidad y estabilidad del suministro de la red "
               "eléctrica en su sitio.",
    "subEvents": "Registra los cortes de red y eventos de alarma detectados "
                 "por el sistema esta semana.",
    "subEventsOffGrid": "Registra los eventos de alarma detectados por el "
                        "sistema durante este período. Este sitio no tiene "
                        "conexión a la red.",
    "subSocChart": "Muestra el nivel de carga máximo y mínimo diario de la "
                   "batería — bajar de 20% indica uso intenso.",
    "subSolarPerf": "Compara la producción solar real contra el máximo teórico "
                    "según la capacidad instalada y la luz disponible.",
    "subWeather": "Condiciones climáticas locales de la semana — la nubosidad y "
                  "la lluvia reducen directamente la producción solar.",
    "gridExport": "Energía exportada a la red",
    "gridExportKpi": "Energía Exportada",
    "ofGeneration": "de lo generado",
    "inverterShutdowns": "Cortes del Inversor",
    # Shortened 2026-08-19: the original text overflowed the card's own
    # width (text_width() at font-size 8: 118.3 vs. ~113.5 available) —
    # caught from the actual rendered PDF, not the source alone.
    "inverterShutdownsSubZero": "Energía sin interrupciones",
    "inverterShutdownsSub": "Corte(s) por batería baja",
    "batteryAutonomy": "Autonomía de Batería",
    "batteryAutonomyUnit": "días",
    "batteryAutonomySub": "Reserva de batería sin sol",
    "batteryAutonomyUnavailable": "datos insuficientes",
    "battStressNoData": "Sin datos",
    "solarExpectedEstimated": "Producción esperada (estimada)",
    "weatherFallbackNote": "sin datos de clima — solo estimación",
    "fourWeekChart": "Tendencia solar de 4 semanas",
    "sub4Week": "Compara la producción solar de las últimas 4 semanas para "
                "identificar tendencias estacionales.",
    "trendNote": "▲▼ = cambio en la producción solar de esa semana vs. la "
                 "semana anterior (principalmente por el clima).",
    "tariffSavings": "Ahorro estimado",
    "tariffComingSoon": "Datos de tarifa próximamente",
    "savingsThisWeek": "Esta semana",
    "savingsBasisLabel": "Base de cálculo",
    "savingsBasisCr": "Promedio de {n} tarifas T-RE de Costa Rica",
    "savingsBasisFlat": "Tarifa configurada",
    "subSavingsOffGrid": "Este sitio no tiene conexión a la red. Costo "
                         "eléctrico estimado que se habría evitado usando "
                         "energía solar en vez de comprarla a la red, si el "
                         "sitio estuviera conectado.",
    "subSavings": "Estimado del costo eléctrico evitado esta semana al usar "
                  "energía solar en vez de comprarla a la red.",
    "comingSoonValue": "— pronto",
    "poweredBy": "Monitoreo por Pauly & Co.",
    "pageOf": "Página",
    "narrativeLang": "Responde en español, en un tono profesional pero cercano.",
    "narrativeUnavailable": "Resumen no disponible esta semana.",
    "narrativeNoKey": "Resumen no disponible (clave API no configurada).",
})

TRANSLATIONS = {"en": EN, "es": ES}

# Keys whose EN/ES text hardcodes "week"/"semana" and must read correctly for
# a `vrm` custom-range report of any length (plan doc §21, Phase A). The
# 4-week trend chart's own keys (fourWeekChart, sub4Week, trendNote) are
# deliberately absent — that chart is always a fixed 4x7-day view regardless
# of the report's own window, so its wording never changes.
_PERIOD_OVERRIDES_EN = {
    "reportTitle": "Energy Report",
    "reportSubtitle": "Reporte de energía",
    "healthScore": "Health Score",
    "sectionEvents": "Events this period",
    "lowestSoc": "Lowest SOC of the period",
    "weatherTitle": "Weather this period",
    "socTimeline": "Battery SOC this period",
    "subDaily": "Compares daily solar production against household "
                "consumption for each day in this period.",
    "subBattery": "Tracks how well your batteries charged and discharged "
                  "throughout this period.",
    "subEvents": "Logs grid outages and alarm events recorded by the system "
                 "during this period.",
    "subWeather": "Local weather conditions for this period — cloud cover "
                  "and rain directly reduce solar output.",
    "savingsThisWeek": "This period",
    "subSavings": "Estimated electricity cost avoided this period by using "
                  "solar instead of buying from the grid.",
    "narrativeUnavailable": "Narrative unavailable for this period.",
}
_PERIOD_OVERRIDES_ES = {
    "reportTitle": "Reporte de Energía",
    "reportSubtitle": "Energy report",
    "healthScore": "Puntaje de Salud",
    "sectionEvents": "Eventos del período",
    "lowestSoc": "SOC Mínimo del Período",
    "weatherTitle": "Clima del período",
    "socTimeline": "SOC de la batería en este período",
    "subDaily": "Compara la producción solar diaria contra el consumo de la "
                "propiedad para cada día de este período.",
    "subBattery": "Indica qué tan bien cargaron y descargaron sus baterías "
                  "durante este período.",
    "subEvents": "Registra los cortes de red y eventos de alarma detectados "
                 "por el sistema durante este período.",
    "subWeather": "Condiciones climáticas locales de este período — la "
                  "nubosidad y la lluvia reducen directamente la producción "
                  "solar.",
    "savingsThisWeek": "Este período",
    "subSavings": "Estimado del costo eléctrico evitado en este período al "
                  "usar energía solar en vez de comprarla a la red.",
    "narrativeUnavailable": "Resumen no disponible para este período.",
}
_PERIOD_OVERRIDES = {"en": _PERIOD_OVERRIDES_EN, "es": _PERIOD_OVERRIDES_ES}

# Overview mode only (plan doc §22) — `_PERIOD_OVERRIDES` above still says
# "daily"/"diario" because it was written for a longer *Detallado* range
# (Phase A: still one bar per day, just not exactly 7 of them), where that
# wording is accurate. Overview's bar/SOC charts draw one bar/point per
# monthly bucket instead, so "daily" is wrong there specifically — a real
# bug a generated report surfaced (2026-08-16), not something the Phase A
# override was ever meant to cover.
_OVERVIEW_OVERRIDES_EN = {
    "sectionDaily": "Solar vs. consumption",
    "subDaily": "Compares solar production against household consumption "
               "for each segment of this period.",
    "subSocChart": "Shows each segment's high and low battery charge level "
                   "— a dip below 20% signals heavy use.",
}
_OVERVIEW_OVERRIDES_ES = {
    "sectionDaily": "Solar vs. consumo",
    "subDaily": "Compara la producción solar contra el consumo de la "
               "propiedad para cada tramo de este período.",
    "subSocChart": "Muestra el nivel de carga máximo y mínimo de cada tramo "
                   "de la batería — bajar de 20% indica uso intenso.",
}
_OVERVIEW_OVERRIDES = {"en": _OVERVIEW_OVERRIDES_EN, "es": _OVERVIEW_OVERRIDES_ES}


def get(lang: str, num_days: int = 7, is_overview: bool = False) -> dict:
    """Translation dict for `lang`, worded for a window of `num_days`.

    `num_days == 7` and not `is_overview` (the only combination `monitoring`
    ever passes, and the common case for `vrm`) returns the original dict
    unchanged — same object identity even — so the already-verified 7-day
    report is byte-for-byte unaffected. Any other length swaps in
    period-neutral wording so a 20-day `vrm` report doesn't call itself
    "weekly"; `is_overview` layers a further correction on top for the
    "daily" chart text that's specifically wrong once bars represent
    monthly buckets rather than days.
    """
    lang = (lang or "en").lower()
    base = TRANSLATIONS.get(lang, EN)
    if num_days == 7 and not is_overview:
        return base
    overrides = _PERIOD_OVERRIDES.get(lang, _PERIOD_OVERRIDES_EN)
    merged = {**base, **overrides}
    if is_overview:
        merged.update(_OVERVIEW_OVERRIDES.get(lang, _OVERVIEW_OVERRIDES_EN))
    return merged
