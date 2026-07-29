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
    "gridIndependence": "Grid Independence",
    "lowestSoc": "Lowest SOC of the Week",
    "daysFullCharge": "Days Battery Reached Full Charge",
    "avgFrequency": "Grid Frequency Range",
    "voltageRangeL1": "Voltage Range L1",
    "voltageRangeL2": "Voltage Range L2",
    "gridDataDays": "Days With Grid Data",
    "alarmEpisodes": "Total Alarm Episodes",
    "outages": "Grid Outages",
    "noOutagesShort": "No outages",
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
    "fourWeekChart": "4-week solar trend",
    "sub4Week": "Compares solar production across the past 4 weeks to help spot "
                "seasonal trends.",
    "trendNote": "▲▼ = change in that week's solar production vs. the previous "
                 "week (mostly driven by weather).",
    "tariffSavings": "Estimated savings",
    "tariffComingSoon": "Tariff data coming soon",
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
    "gridIndependence": "Independencia de la Red",
    "lowestSoc": "SOC Mínimo de la Semana",
    "daysFullCharge": "Días que la Batería Cargó Completa",
    "avgFrequency": "Rango de Frecuencia de Red",
    "voltageRangeL1": "Rango de Voltaje L1",
    "voltageRangeL2": "Rango de Voltaje L2",
    "gridDataDays": "Días con Datos de Red",
    "alarmEpisodes": "Total de Episodios de Alarma",
    "outages": "Cortes de Red",
    "noOutagesShort": "Sin cortes",
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
    "fourWeekChart": "Tendencia solar de 4 semanas",
    "sub4Week": "Compara la producción solar de las últimas 4 semanas para "
                "identificar tendencias estacionales.",
    "trendNote": "▲▼ = cambio en la producción solar de esa semana vs. la "
                 "semana anterior (principalmente por el clima).",
    "tariffSavings": "Ahorro estimado",
    "tariffComingSoon": "Datos de tarifa próximamente",
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


def get(lang: str) -> dict:
    return TRANSLATIONS.get((lang or "en").lower(), EN)
