// ╔══════════════════════════════════════════════════════════════╗
// ║  VICTRON EVENTS — Google Apps Script                        ║
// ║  All project-specific config now lives in Node-RED.         ║
// ║  Site specs (kWh, kWp, thresholds) arrive in the payload.   ║
// ║  The CONFIG block below is kept only as a fallback.         ║
// ╚══════════════════════════════════════════════════════════════╝

const CONFIG = {
  // Deployment-level settings — the only values that belong here.
  // All site-specific data (battery kWh, PV kWp, thresholds) comes
  // from the Node-RED Project Config node via the POST payload.
  reportEmail:    "proyectos@paulyco.com",
  reportFolderId: "155p6NQJd8fGlesPeV419lDtzl--yt5Rj",

  // Default health thresholds — used only if Node-RED does not send
  // health_thresholds in the payload (should always be sent).
  defaultHealthThresholds: {
    socLowAlarm:       20,
    socLowWarning:     30,
    socLowWatch:       40,
    outageMinLong:    120,
    outageMinMid:      30,
    outageCountHigh:    5,
    gridDepHigh:       50,
    gridDepMid:        20,
    batteryCyclesHigh: 1.5,
    batteryCyclesMid:  1.0
  }
};

// ─────────────────────────────────────────────────────────────────
// HTTP endpoint — receives POSTs from Node-RED
// ─────────────────────────────────────────────────────────────────
function doPost(e) {
  try {
    Logger.log("=== RAW POST BODY ===");
    Logger.log(e.postData.contents);

    const data = JSON.parse(e.postData.contents);
    const sheetName = data.sheet || "Sheet1";

    Logger.log("=== PARSED DATA KEYS (" + Object.keys(data).length + " total) ===");
    Logger.log(Object.keys(data).join(", "));

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = ss.getSheetByName(sheetName);

    if (!sheet) {
      return ContentService.createTextOutput("ERROR: Sheet not found: " + sheetName);
    }

    if (sheetName === "ACInput" || sheetName === "GridLost") {
      sheet.appendRow([
        data.timestamp || "",
        data.site || "",
        data.source || "",
        data.event || "",
        data.previous_state || "",
        data.new_state || "",
        data.duration_minutes || "",
        data.grid_lost_status || ""
      ]);
    }

    else if (sheetName === "DailySummary") {

      Logger.log("=== FIELD VALUES BEFORE APPENDROW ===");
      Logger.log("battery_reached_float = " + data.battery_reached_float + " | type: " + typeof data.battery_reached_float);
      Logger.log("min_grid_freq = " + data.min_grid_freq + " | type: " + typeof data.min_grid_freq);
      Logger.log("max_grid_freq = " + data.max_grid_freq + " | type: " + typeof data.max_grid_freq);
      Logger.log("min_grid_v_l1 = " + data.min_grid_v_l1 + " | type: " + typeof data.min_grid_v_l1);
      Logger.log("grid_data_available = " + data.grid_data_available + " | type: " + typeof data.grid_data_available);
      Logger.log("reportLanguage = " + data.reportLanguage + " | type: " + typeof data.reportLanguage);

      const rowToWrite = [
        data.date || "",
        data.site || "",
        data.pv_kWh || 0,
        data.grid_kWh || 0,
        data.load_kWh || 0,
        data.battery_charge_kWh || 0,
        data.battery_discharge_kWh || 0,
        data.min_soc || "",
        data.max_soc || "",
        data.avg_soc || "",
        data.outage_count || 0,
        data.outage_minutes || 0,
        // Battery health (new v1p4)
        data.min_voltage     || "",
        data.max_voltage     || "",
        data.min_temperature || "",
        data.max_temperature || "",
        data.avg_temperature || "",
        // PV / MPPT (new v1p4)
        data.pv_yield_kwh_sc0  || "",
        data.pv_yield_kwh_sc1  || "",
        data.pv_yield_kwh_mppt || "",
        data.battery_reached_float === true ? "YES" : "NO",
        // Grid quality (new v1p4)
        data.min_grid_freq || "",
        data.max_grid_freq || "",
        data.min_grid_v_l1 || "",
        data.max_grid_v_l1 || "",
        data.min_grid_v_l2 || "",
        data.max_grid_v_l2 || "",
        // Grid data availability (new)
        data.grid_data_available === false ? "NO" : "YES",
        // Report language (new)
        data.reportLanguage || "en"
      ];

      Logger.log("=== ROW TO WRITE ===");
      Logger.log("Length: " + rowToWrite.length);
      Logger.log("Contents: " + JSON.stringify(rowToWrite));

      sheet.appendRow(rowToWrite);

      Logger.log("=== ROW WRITTEN SUCCESSFULLY ===");

      appendDailyHealth(data);
      saveDriveBackup(data);
      return ContentService.createTextOutput("OK + DailyHealth written");
    }

    else if (sheetName === "AlarmEvents") {
      sheet.appendRow([
        data.timestamp || "",
        data.site || "",
        data.source || "",
        data.alarm || "",
        data.status || "",
        data.severity || ""
      ]);
    }

    else {
      return ContentService.createTextOutput("ERROR: Unsupported sheet: " + sheetName);
    }

    return ContentService.createTextOutput("OK");

  } catch (err) {
    return ContentService.createTextOutput("ERROR: " + err.toString());
  }
}

// ─────────────────────────────────────────────────────────────────
// Daily health row — derived from DailySummary payload
// ─────────────────────────────────────────────────────────────────
function appendDailyHealth(data) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("DailyHealth");

  if (!sheet) {
    throw new Error("DailyHealth sheet not found");
  }

  const date = data.date || "";
  const site = data.site || "Unknown";

  const load      = Number(data.load_kWh || 0);
  const grid      = Number(data.grid_kWh || 0);
  const discharge = Number(data.battery_discharge_kWh || 0);
  const minSoc    = Number(data.min_soc || 0);
  const outageCount   = Number(data.outage_count || 0);
  const outageMinutes = Number(data.outage_minutes || 0);

  const alarmsCount = countAlarmEpisodesForDate(site, date);

  // ── Battery capacity: always comes from payload (Project Config node) ──
  const batteryCapacity =
    (data.battery_usable_kwh != null && data.battery_usable_kwh > 0)
      ? Number(data.battery_usable_kwh)
      : 1;  // 1 as safe fallback — prevents division by zero

  const batteryCycles = discharge / batteryCapacity;

  const gridDependencyPct = load > 0 ? (grid / load) * 100 : 0;

  // ── Health thresholds: payload takes priority, CONFIG is fallback ──
  const thresholds = Object.assign(
    {},
    CONFIG.defaultHealthThresholds,
    data.health_thresholds || {}
  );

  const result = calculateHealthScore({
    alarmsCount,
    minSoc,
    outageCount,
    outageMinutes,
    gridDependencyPct,
    batteryCycles,
    maxTemperature:    Number(data.max_temperature || 0) || null,
    minVoltage:        Number(data.min_voltage || 0) || null,
    mpptReachedFloat:  data.battery_reached_float === true || data.battery_reached_float === "YES",
    gridDataAvailable: data.grid_data_available !== false
  }, thresholds);

  sheet.appendRow([
    date,
    site,
    result.score,
    result.status,
    alarmsCount,
    minSoc,
    outageCount,
    outageMinutes,
    Number(gridDependencyPct.toFixed(1)),
    Number(batteryCycles.toFixed(2)),
    result.notes.join("; ")
  ]);
}

// ─────────────────────────────────────────────────────────────────
// Health score calculation — thresholds are now a parameter
// ─────────────────────────────────────────────────────────────────
function calculateHealthScore(x, t) {
  // x.alarmsCount, x.minSoc, x.outageCount, x.outageMinutes,
  // x.gridDependencyPct, x.batteryCycles,
  // x.maxTemperature (new), x.minVoltage (new), x.mpptReachedFloat (new)
  let score = 100;
  let notes = [];

  if (x.alarmsCount > 0) {
    const penalty = Math.min(25, x.alarmsCount * 5);
    score -= penalty;
    notes.push(x.alarmsCount + " alarm event(s)");
  }

  if (x.minSoc > 0 && x.minSoc < t.socLowAlarm) {
    score -= 25;
    notes.push("Very low SOC");
  } else if (x.minSoc < t.socLowWarning) {
    score -= 15;
    notes.push("Low SOC");
  } else if (x.minSoc < t.socLowWatch) {
    score -= 8;
    notes.push("SOC below " + t.socLowWatch + "%");
  }

  if (x.outageMinutes > t.outageMinLong) {
    score -= 20;
    notes.push("Long outage time");
  } else if (x.outageMinutes > t.outageMinMid) {
    score -= 10;
    notes.push("Moderate outage time");
  } else if (x.outageMinutes > 0) {
    score -= 5;
    notes.push("Grid outage detected");
  }

  if (x.outageCount > t.outageCountHigh) {
    score -= 10;
    notes.push("Frequent outages");
  }

  if (x.gridDependencyPct > t.gridDepHigh) {
    score -= 10;
    notes.push("High grid dependency");
  } else if (x.gridDependencyPct > t.gridDepMid) {
    score -= 5;
    notes.push("Moderate grid dependency");
  }

  if (x.batteryCycles > t.batteryCyclesHigh) {
    score -= 10;
    notes.push("High battery cycling");
  } else if (x.batteryCycles > t.batteryCyclesMid) {
    score -= 5;
    notes.push("Moderate battery cycling");
  }

  // Battery temperature (new)
  if (x.maxTemperature && x.maxTemperature > 45) {
    score -= 15;
    notes.push("High battery temperature (" + x.maxTemperature + "°C)");
  } else if (x.maxTemperature && x.maxTemperature > 40) {
    score -= 5;
    notes.push("Elevated battery temperature (" + x.maxTemperature + "°C)");
  }

  // Battery voltage low (new)
  if (x.minVoltage && x.minVoltage < 46.0) {
    score -= 10;
    notes.push("Low battery voltage (" + x.minVoltage + "V)");
  }

  // MPPT never reached float (new)
  if (x.mpptReachedFloat === false) {
    score -= 5;
    notes.push("Battery did not fully charge today");
  }

  // Grid data availability (no score penalty — data quality flag)
  if (x.gridDataAvailable === false) {
    notes.push("No grid measurements recorded — verify AC input connections");
  }

  score = Math.max(0, Math.min(100, Math.round(score)));

  let status = "Excellent";
  if (score < 70) status = "Attention";
  else if (score < 80) status = "Watch";
  else if (score < 90) status = "Good";

  if (notes.length === 0) notes.push("Normal operation");

  return { score, status, notes };
}


// ─────────────────────────────────────────────────────────────────
// Count alarm EPISODES for a site+date (not raw event rows).
// An episode = one WARNING/ALARM that eventually CLEARs.
// Rapid oscillation = 1 episode, not many.
// ─────────────────────────────────────────────────────────────────
function countAlarmEpisodesForDate(site, date) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("AlarmEvents");
  if (!sheet) return 0;

  const values = sheet.getDataRange().getValues();
  let episodes = 0;
  let inEpisode = false;

  // Sort by timestamp ascending (col 0)
  const rows = values.slice(1)
    .filter(r => {
      const ts = r[0];
      const rowSite = r[1];
      const severity = r[5];
      if (!ts || rowSite !== site) return false;
      let rowDate = ts instanceof Date
        ? Utilities.formatDate(ts, "America/Costa_Rica", "yyyy-MM-dd")
        : String(ts).slice(0, 10);
      return rowDate === date;
    })
    .sort((a, b) => new Date(a[0]) - new Date(b[0]));

  for (const row of rows) {
    const severity = row[5];
    if ((severity === "WARNING" || severity === "ALARM") && !inEpisode) {
      episodes++;
      inEpisode = true;
    } else if (severity === "CLEARED") {
      inEpisode = false;
    }
  }

  return episodes;
}

// ─────────────────────────────────────────────────────────────────
// Count alarm events for a given site + date
// ─────────────────────────────────────────────────────────────────
function countAlarmsForDate(site, date) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("AlarmEvents");
  if (!sheet) return 0;

  const values = sheet.getDataRange().getValues();
  let count = 0;

  for (let i = 1; i < values.length; i++) {
    const timestamp = values[i][0];
    const rowSite   = values[i][1];
    const severity  = values[i][5];

    if (!timestamp) continue;

    let rowDate = "";

    if (timestamp instanceof Date) {
      rowDate = Utilities.formatDate(
        timestamp,
        "America/Costa_Rica",
        "yyyy-MM-dd"
      );
    } else {
      rowDate = String(timestamp).slice(0, 10);
    }

    if (
      rowDate === date &&
      rowSite === site &&
      (severity === "WARNING" || severity === "ALARM")
    ) {
      count++;
    }
  }

  return count;
}

// ─────────────────────────────────────────────────────────────────
// LOGO — Pauly & Co., embedded as base64 (no external dependency)
// ─────────────────────────────────────────────────────────────────
const LOGO_BASE64 = "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";

// ─────────────────────────────────────────────────────────────────
// TRANSLATIONS — bilingual report labels
// ─────────────────────────────────────────────────────────────────
const TRANSLATIONS = {
  en: {
    reportTitle:        "Weekly Energy Report",
    dateRange:           "Reporting period",
    healthScore:         "Weekly Health Score",
    healthStatus:        { Excellent: "Excellent", Good: "Good", Watch: "Watch", Attention: "Attention" },
    sectionOverview:     "Energy Week at a Glance",
    sectionDaily:        "Daily Breakdown",
    sectionBattery:      "Battery Health",
    sectionGrid:         "Grid Quality",
    sectionPV:           "Solar Performance",
    sectionAlarms:       "Alarms & Events",
    sectionInsights:     "Weekly Insights",
    sectionRecs:         "Recommendations",
    metric:              "Metric",
    value:               "Value",
    date:                "Date",
    pvGenerated:         "Solar Generated",
    totalConsumption:    "Total Consumption",
    gridConsumption:     "Grid Consumption",
    gridIndependence:    "Grid Independence",
    batteryCycles:       "Battery Cycles",
    daysSelfSufficient:  "Days Self-Sufficient",
    minVoltage:          "Minimum Voltage",
    maxVoltage:          "Maximum Voltage",
    minTemp:             "Minimum Temperature",
    maxTemp:             "Maximum Temperature",
    lowestSoc:           "Lowest SOC of the Week",
    daysFullCharge:      "Days Battery Reached Full Charge",
    avgFrequency:        "Grid Frequency Range",
    voltageRangeL1:      "Voltage Range L1",
    voltageRangeL2:      "Voltage Range L2",
    gridDataDays:        "Days With Grid Data",
    pvYieldSC0:          "MPPT 1 Yield",
    pvYieldSC1:          "MPPT 2 Yield",
    bestDay:             "Best Production Day",
    worstDay:            "Lowest Production Day",
    alarmEpisodes:       "Total Alarm Episodes",
    outages:             "Grid Outages",
    outageTime:          "Total Outage Time",
    noOutages:           "No grid outages were recorded this week.",
    outageSummary:       "outage(s) recorded, totaling",
    minutes:             "minutes",
    days:                "days",
    cycles:              "cycles",
    kwh:                 "kWh",
    energyMix:           "Where your energy came from",
    sectionEvents:       "Events this week",
    sectionDaily:        "Daily solar vs. consumption",
    subDaily:            "Compares daily solar production against household consumption for each day this week.",
    batteryProtected:    "System protected by battery",
    longestOutage:       "Longest outage",
    avgTemp:             "Avg temperature",
    voltageRange:        "Voltage range",
    weeklyCycles:        "Weekly cycles",
    weatherTitle:        "Weather this week",
    weatherSunshine:     "Avg sunshine",
    weatherRainDays:     "Significant rain days",
    weatherCloudCover:   "Avg cloud cover",
    weatherUnavailable:  "Weather data unavailable",
    wowTrendLabel:       "vs prev",
    socTimeline:         "Battery SOC this week",
    solarPerformance:    "Solar performance",
    solarExpected:       "Expected output",
    solarActual:         "Actual output",
    solarPerformancePct: "Performance ratio",
    gridQualityScore:    "Grid quality score",
    batteryHealthLabel:  "Battery stress",
    tariffSavings:       "Estimated savings",
    tariffComingSoon:    "Tariff data coming soon",
    subEnergyMix:        "Shows how much of your energy came from solar panels, batteries, and the utility grid.",
    subBattery:          "Tracks how well your batteries charged and discharged throughout the week.",
    subGrid:             "Measures the quality and stability of the utility grid supply at your site.",
    subEvents:           "Logs grid outages and alarm events recorded by the system this week.",
    subSocChart:         "Shows the daily high and low battery charge level — a dip below 20% signals heavy use.",
    subSolarPerf:        "Compares real solar production to the theoretical maximum based on your panel capacity and available sunlight.",
    subWeather:          "Local weather conditions for the week — cloud cover and rain directly reduce solar output.",
    sub4Week:            "Compares solar production across the past 4 weeks to help spot seasonal trends.",
    subSavings:          "Estimated electricity cost avoided this week by using solar instead of buying from the grid.",
    fourWeekChart:       "4-week solar trend",
    trendNote:           "▲▼ = change in that week's solar production vs. the previous week (mostly driven by weather).",
    emailIntro:          "Here is your weekly energy report for",
    emailKeyStats:       "Key stats this week",
    emailAttached:       "The full report is attached as a PDF.",
    emailLblUsed:        "Energy you used",
    emailLblOwnEnergy:   "Powered by your own energy",
    emailLblBatteryFull: "Days battery fully charged",
    emailSavingsSoon:    "Coming soon",
    poweredBy:           "Monitoring powered by Pauly &amp; Co.",
    pageOf:              "Page"
  },
  es: {
    reportTitle:        "Reporte Semanal de Energía",
    dateRange:           "Período del reporte",
    healthScore:         "Puntaje de Salud Semanal",
    healthStatus:        { Excellent: "Excelente", Good: "Bueno", Watch: "Atención", Attention: "Requiere Atención" },
    sectionOverview:     "Resumen Semanal de Energía",
    sectionDaily:        "Detalle Diario",
    sectionBattery:      "Salud de la Batería",
    sectionGrid:         "Calidad de Red Eléctrica",
    sectionPV:           "Rendimiento Solar",
    sectionAlarms:       "Alarmas y Eventos",
    sectionInsights:     "Análisis de la Semana",
    sectionRecs:         "Recomendaciones",
    metric:              "Métrica",
    value:               "Valor",
    date:                "Fecha",
    pvGenerated:         "Energía Solar Generada",
    totalConsumption:    "Consumo Total",
    gridConsumption:     "Consumo de Red",
    gridIndependence:    "Independencia de Red",
    batteryCycles:       "Ciclos de Batería",
    daysSelfSufficient:  "Días Autosuficientes",
    minVoltage:          "Voltaje Mínimo",
    maxVoltage:          "Voltaje Máximo",
    minTemp:             "Temperatura Mínima",
    maxTemp:             "Temperatura Máxima",
    lowestSoc:           "SOC Más Bajo de la Semana",
    daysFullCharge:      "Días con Carga Completa",
    avgFrequency:        "Rango de Frecuencia de Red",
    voltageRangeL1:      "Rango de Voltaje L1",
    voltageRangeL2:      "Rango de Voltaje L2",
    gridDataDays:        "Días con Datos de Red",
    pvYieldSC0:          "Producción MPPT 1",
    pvYieldSC1:          "Producción MPPT 2",
    bestDay:             "Mejor Día de Producción",
    worstDay:            "Día de Menor Producción",
    alarmEpisodes:       "Total de Episodios de Alarma",
    outages:             "Cortes de Red",
    outageTime:          "Tiempo Total de Corte",
    noOutages:           "No se registraron cortes de red esta semana.",
    outageSummary:       "corte(s) registrados, totalizando",
    minutes:             "minutos",
    days:                "días",
    cycles:              "ciclos",
    kwh:                 "kWh",
    energyMix:           "De dónde vino tu energía",
    sectionEvents:       "Eventos de la semana",
    sectionDaily:        "Solar diario vs. consumo",
    subDaily:            "Compara la producción solar diaria con el consumo del hogar para cada día de esta semana.",
    batteryProtected:    "Sistema protegido por batería",
    longestOutage:       "Corte más largo",
    avgTemp:             "Temperatura promedio",
    voltageRange:        "Rango de voltaje",
    weeklyCycles:        "Ciclos semanales",
    weatherTitle:        "Clima esta semana",
    weatherSunshine:     "Luz solar prom.",
    weatherRainDays:     "Días con lluvia significativa",
    weatherCloudCover:   "Nubosidad prom.",
    weatherUnavailable:  "Datos climáticos no disponibles",
    wowTrendLabel:       "vs anterior",
    socTimeline:         "SOC batería esta semana",
    solarPerformance:    "Rendimiento solar",
    solarExpected:       "Producción esperada",
    solarActual:         "Producción real",
    solarPerformancePct: "Ratio de rendimiento",
    gridQualityScore:    "Calidad de red",
    batteryHealthLabel:  "Estrés de batería",
    tariffSavings:       "Ahorro estimado",
    tariffComingSoon:    "Datos de tarifa próximamente",
    subEnergyMix:        "Muestra cuánta energía provino de los paneles solares, las baterías y la red eléctrica.",
    subBattery:          "Indica qué tan bien se cargaron y descargaron las baterías durante la semana.",
    subGrid:             "Mide la calidad y estabilidad del suministro eléctrico de la red en su sitio.",
    subEvents:           "Registra cortes de red y alarmas detectadas por el sistema durante la semana.",
    subSocChart:         "Muestra el nivel máximo y mínimo de carga diaria — una caída bajo 20% indica uso intenso.",
    subSolarPerf:        "Compara la producción solar real con el máximo teórico según la capacidad instalada y la luz solar disponible.",
    subWeather:          "Condiciones climáticas locales de la semana — la nubosidad y la lluvia reducen directamente la producción solar.",
    sub4Week:            "Compara la producción solar de las últimas 4 semanas para identificar tendencias estacionales.",
    subSavings:          "Estimado del costo eléctrico evitado esta semana al usar energía solar en vez de comprarla a la red.",
    fourWeekChart:       "Tendencia solar 4 semanas",
    trendNote:           "▲▼ = cambio en la producción solar de esa semana respecto a la anterior (depende sobre todo del clima).",
    emailIntro:          "Aquí está su reporte semanal de energía para",
    emailKeyStats:       "Datos clave de esta semana",
    emailAttached:       "El reporte completo está adjunto en PDF.",
    emailLblUsed:        "Energía que usó",
    emailLblOwnEnergy:   "Energía propia utilizada",
    emailLblBatteryFull: "Días con batería llena",
    emailSavingsSoon:    "Próximamente",
    poweredBy:           "Monitoreo impulsado por Pauly &amp; Co.",
    pageOf:              "Página"
  }
};

// ─────────────────────────────────────────────────────────────────
// Claude API — generate a short narrative summary of the week
// Requires ANTHROPIC_API_KEY in Script Properties.
// ─────────────────────────────────────────────────────────────────
function generateWeeklyNarrative(stats, lang) {
  const apiKey = PropertiesService.getScriptProperties().getProperty('ANTHROPIC_API_KEY');
  if (!apiKey) {
    return lang === 'es'
      ? "Resumen no disponible (clave API no configurada)."
      : "Narrative unavailable (API key not configured).";
  }

  const langInstruction = lang === 'es'
    ? "Responde en español, en un tono profesional pero cercano."
    : "Respond in English, in a professional but approachable tone.";

  const prompt =
    "You are writing the weekly insights paragraph for a residential solar+battery monitoring report. " + langInstruction +
    "\n\nWrite exactly 2 short paragraphs (60-90 words total). Plain prose only - no headers, no bullets, no markdown." +
    " Warm, professional tone. Be specific with numbers. Lead with the most meaningful story of the week." +
    " If the battery kept the home running during outages, say so. End with one forward-looking sentence if warranted." +
    "\n\nThis week's data:" +
    "\n- Site: " + stats.site +
    "\n- Solar generated: " + stats.pv + " kWh" +
    "\n- Total consumption: " + stats.load + " kWh" +
    "\n- Grid consumption: " + stats.grid + " kWh" +
    "\n- Grid independence: " + stats.gridIndependencePct + "%" +
    "\n- Health score: " + stats.healthScore + "/100 (" + stats.healthStatus + ")" +
    "\n- Lowest battery SOC: " + stats.minSoc + "%" +
    "\n- Battery cycles this week: " + stats.batteryCycles +
    "\n- Days battery reached full charge: " + stats.daysFullCharge + " of " + stats.totalDays +
    "\n- Grid outages: " + stats.outageCount + " (" + stats.outageMinutes + " minutes total)" +
    "\n- Longest single outage: " + stats.longestOutageMinutes + " minutes" +
    "\n- Battery covered loads during outages: " + (stats.batteryProtectedDuringOutage ? "yes" : "no / unknown") +
    "\n- Alarm episodes: " + stats.alarmEpisodes +
    "\n- Best production day: " + stats.bestDay + " kWh" +
    "\n- Worst production day: " + stats.worstDay + " kWh" +
    (stats.weatherAvailable ? (
      "\n- Weather: avg " + stats.avgSunshineHrs + " sunshine hrs/day, days with significant rain (>5mm): " +
      stats.rainyDays + ", avg cloud cover: " + stats.avgCloudPct + "%." +
      " If weather affected generation, mention it." +
      "\n- Solar performance ratio: " + stats.solarPerformancePct + "% of expected"
    ) : "") +
    "\n- Grid quality: " + stats.gridQualityScore + "/100 (" + stats.gridQualityStatus + ")";

  try {
    const response = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
      method: 'post',
      contentType: 'application/json',
      headers: {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01'
      },
      payload: JSON.stringify({
        model: 'claude-sonnet-4-6',
        max_tokens: 400,
        messages: [{ role: 'user', content: prompt }]
      }),
      muteHttpExceptions: true
    });

    const result = JSON.parse(response.getContentText());

    if (result.content && result.content[0] && result.content[0].text) {
      return result.content[0].text.trim();
    }

    Logger.log('Claude API unexpected response: ' + response.getContentText());
    return lang === 'es'
      ? "Resumen no disponible esta semana."
      : "Narrative unavailable this week.";

  } catch (err) {
    Logger.log('Claude API error: ' + err.toString());
    return lang === 'es'
      ? "Resumen no disponible esta semana."
      : "Narrative unavailable this week.";
  }
}

// ─────────────────────────────────────────────────────────────────
// Weekly HTML→PDF report — bilingual, branded, AI narrative
// ─────────────────────────────────────────────────────────────────
function weeklyReport() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const daily  = ss.getSheetByName("DailySummary");
  const health = ss.getSheetByName("DailyHealth");

  if (!daily || !health) return;

  const today = new Date();
  const end   = new Date(today);
  const start = new Date(today);
  start.setDate(today.getDate() - 7);

  const startStr = formatDate(start);
  const endStr   = formatDate(end);

  // Only AUTO dumps for weekly aggregation (skip TEST/MANUAL rows)
  const dailyRowsAll = getRowsByDateRange(daily, startStr, endStr);
  const dailyRows = dailyRowsAll.filter(r => !r.event || r.event !== "TEST_DAILY_SUMMARY");
  const healthRows = getRowsByDateRange(health, startStr, endStr);

  if (dailyRows.length === 0) {
    throw new Error("No DailySummary rows found between " + startStr + " and " + endStr);
  }

  const site = dailyRows[0].site || "Unknown Site";
  const lang = (dailyRows[0].reportLanguage || "en").toString().toLowerCase() === "es" ? "es" : "en";
  const t = TRANSLATIONS[lang];

  // ── Previous week data (week-over-week trends) ───────────────────
  const prevEnd   = new Date(start);
  const prevStart = new Date(start);
  prevStart.setDate(prevStart.getDate() - 7);
  const prevRows = getRowsByDateRange(daily, formatDate(prevStart), formatDate(prevEnd))
    .filter(function(r) { return !r.event || r.event !== "TEST_DAILY_SUMMARY"; });
  const prevDM = {};
  prevRows.forEach(function(r) {
    if (!prevDM[r.date]) prevDM[r.date] = { pv: 0, grid: 0, load: 0 };
    prevDM[r.date].pv   += Number(r.pv_kWh   || 0);
    prevDM[r.date].grid += Number(r.grid_kWh  || 0);
    prevDM[r.date].load += Number(r.load_kWh  || 0);
  });
  const prevTotals = { pv: 0, grid: 0, load: 0 };
  Object.values(prevDM).forEach(function(r) { prevTotals.pv+=r.pv; prevTotals.grid+=r.grid; prevTotals.load+=r.load; });

  // ── 4-week solar trend ────────────────────────────────────────────
  const weekBuckets = [];
  for (var wi = 3; wi >= 0; wi--) {
    var wE = new Date(today); wE.setDate(today.getDate() - wi*7);
    var wS = new Date(wE);    wS.setDate(wE.getDate() - 7);
    var wM = {};
    getRowsByDateRange(daily, formatDate(wS), formatDate(wE))
      .filter(function(r){return !r.event||r.event!=="TEST_DAILY_SUMMARY";})
      .forEach(function(r){if(!wM[r.date])wM[r.date]={pv:0,load:0}; wM[r.date].pv+=Number(r.pv_kWh||0); wM[r.date].load+=Number(r.load_kWh||0);});
    var wVals=Object.values(wM); var wPv=wVals.reduce(function(a,b){return a+b.pv;},0); var wLoad=wVals.reduce(function(a,b){return a+b.load;},0);
    weekBuckets.push({ label: formatDate(wS).slice(5), pv: Number(wPv.toFixed(1)), load: Number(wLoad.toFixed(1)) });
  }

  // ── Group DailySummary rows by date ──────────────────────────────
  const dateMap = {};
  dailyRows.forEach(function(r) {
    const dt = r.date;
    if (!dateMap[dt]) {
      dateMap[dt] = {
        date: dt, site: r.site, reportLanguage: r.reportLanguage,
        battery_usable_kwh: r.battery_usable_kwh,
        pv_kWh: 0, grid_kWh: 0, load_kWh: 0,
        battery_charge_kWh: 0, battery_discharge_kWh: 0,
        outage_count: 0, outage_minutes: 0,
        pv_yield_kwh_sc0: 0, pv_yield_kwh_sc1: 0,
        min_soc: null, max_soc: null,
        min_voltage: null, max_voltage: null,
        min_temperature: null, max_temperature: null,
        min_grid_freq: null, max_grid_freq: null,
        min_grid_v_l1: null, max_grid_v_l1: null,
        min_grid_v_l2: null, max_grid_v_l2: null,
        battery_reached_float: "NO", grid_data_available: "NO"
      };
    }
    const g = dateMap[dt];
    g.pv_kWh                += Number(r.pv_kWh || 0);
    g.grid_kWh              += Number(r.grid_kWh || 0);
    g.load_kWh              += Number(r.load_kWh || 0);
    g.battery_charge_kWh    += Number(r.battery_charge_kWh || 0);
    g.battery_discharge_kWh += Number(r.battery_discharge_kWh || 0);
    g.outage_count          += Number(r.outage_count || 0);
    g.outage_minutes        += Number(r.outage_minutes || 0);
    g.pv_yield_kwh_sc0      += Number(r.pv_yield_kwh_sc0 || 0);
    g.pv_yield_kwh_sc1      += Number(r.pv_yield_kwh_sc1 || 0);
    if (r.battery_reached_float === "YES") g.battery_reached_float = "YES";
    if (r.grid_data_available   === "YES") g.grid_data_available   = "YES";
    function upMin(key, val) { if (val !== "" && val != null) { const v = Number(val); g[key] = g[key] === null ? v : Math.min(g[key], v); } }
    function upMax(key, val) { if (val !== "" && val != null) { const v = Number(val); g[key] = g[key] === null ? v : Math.max(g[key], v); } }
    upMin("min_soc", r.min_soc);               upMax("max_soc", r.max_soc);
    upMin("min_voltage", r.min_voltage);        upMax("max_voltage", r.max_voltage);
    upMin("min_temperature", r.min_temperature);upMax("max_temperature", r.max_temperature);
    upMin("min_grid_freq", r.min_grid_freq);    upMax("max_grid_freq", r.max_grid_freq);
    upMin("min_grid_v_l1", r.min_grid_v_l1);   upMax("max_grid_v_l1", r.max_grid_v_l1);
    upMin("min_grid_v_l2", r.min_grid_v_l2);   upMax("max_grid_v_l2", r.max_grid_v_l2);
  });
  const dailyGrouped = Object.keys(dateMap).sort().map(function(dt) { return dateMap[dt]; });

  let totals = {
    pv: 0, grid: 0, load: 0, charge: 0, discharge: 0,
    outageCount: 0, outageMinutes: 0, pvYieldSc0: 0, pvYieldSc1: 0,
    daysFullCharge: 0, daysNoGridData: 0, daysSelfSufficient: 0
  };
  let minSoc = null, maxSoc = null, avgSocSum = 0, avgSocCount = 0;
  let minVoltage = null, maxVoltage = null, minTemp = null, maxTemp = null;
  let minFreq = null, maxFreq = null;
  let minVL1 = null, maxVL1 = null, minVL2 = null, maxVL2 = null;
  let bestDay = null, worstDay = null;

  dailyGrouped.forEach(function(r) {
    const pv = r.pv_kWh;
    totals.pv += pv; totals.grid += r.grid_kWh; totals.load += r.load_kWh;
    totals.charge += r.battery_charge_kWh; totals.discharge += r.battery_discharge_kWh;
    totals.outageCount += r.outage_count; totals.outageMinutes += r.outage_minutes;
    totals.pvYieldSc0 += r.pv_yield_kwh_sc0; totals.pvYieldSc1 += r.pv_yield_kwh_sc1;
    if (r.battery_reached_float === "YES") totals.daysFullCharge++;
    if (r.grid_data_available   !== "YES") totals.daysNoGridData++;
    if (r.grid_kWh === 0) totals.daysSelfSufficient++;
    if (r.min_soc != null) { minSoc = minSoc === null ? r.min_soc : Math.min(minSoc, r.min_soc); }
    if (r.max_soc != null) { maxSoc = maxSoc === null ? r.max_soc : Math.max(maxSoc, r.max_soc); }
    if (r.min_voltage     != null) { minVoltage = minVoltage === null ? r.min_voltage     : Math.min(minVoltage, r.min_voltage); }
    if (r.max_voltage     != null) { maxVoltage = maxVoltage === null ? r.max_voltage     : Math.max(maxVoltage, r.max_voltage); }
    if (r.min_temperature != null) { minTemp    = minTemp    === null ? r.min_temperature : Math.min(minTemp, r.min_temperature); }
    if (r.max_temperature != null) { maxTemp    = maxTemp    === null ? r.max_temperature : Math.max(maxTemp, r.max_temperature); }
    if (r.min_grid_freq   != null) { minFreq    = minFreq    === null ? r.min_grid_freq   : Math.min(minFreq, r.min_grid_freq); }
    if (r.max_grid_freq   != null) { maxFreq    = maxFreq    === null ? r.max_grid_freq   : Math.max(maxFreq, r.max_grid_freq); }
    if (r.min_grid_v_l1   != null) { minVL1     = minVL1     === null ? r.min_grid_v_l1   : Math.min(minVL1, r.min_grid_v_l1); }
    if (r.max_grid_v_l1   != null) { maxVL1     = maxVL1     === null ? r.max_grid_v_l1   : Math.max(maxVL1, r.max_grid_v_l1); }
    if (r.min_grid_v_l2   != null) { minVL2     = minVL2     === null ? r.min_grid_v_l2   : Math.min(minVL2, r.min_grid_v_l2); }
    if (r.max_grid_v_l2   != null) { maxVL2     = maxVL2     === null ? r.max_grid_v_l2   : Math.max(maxVL2, r.max_grid_v_l2); }
    if (bestDay  === null || pv > bestDay.pv)  bestDay  = { date: r.date, pv: pv };
    if (worstDay === null || pv < worstDay.pv) worstDay = { date: r.date, pv: pv };
  });

  let avgHealth = "";
  let healthStatus = "";
  let alarmEpisodesTotal = 0;
  if (healthRows.length > 0) {
    const healthByDate = {};
    healthRows.forEach(function(r) {
      const dt = r.date;
      if (!healthByDate[dt] || Number(r.health_score) > Number(healthByDate[dt].health_score)) healthByDate[dt] = r;
    });
    const healthGrouped = Object.keys(healthByDate).sort().map(function(dt) { return healthByDate[dt]; });
    let healthSum = 0;
    healthGrouped.forEach(function(r) { healthSum += Number(r.health_score||0); alarmEpisodesTotal += Number(r.alarms_count||0); });
    avgHealth    = Math.round(healthSum / healthGrouped.length);
    healthStatus = healthGrouped[healthGrouped.length - 1].status || "";
  }

  const avgSoc = avgSocCount > 0 ? Number((avgSocSum / avgSocCount).toFixed(1)) : "";
  const gridIndependencePct = totals.load > 0
    ? Number((100 - (totals.grid / totals.load) * 100).toFixed(1))
    : 100;
  const batteryUsableKwh = Number(dailyRows[0].battery_usable_kwh || 1);
  const batteryCycles = Number((totals.discharge / batteryUsableKwh).toFixed(2));

  let longestOutageMinutes = 0;
  try {
    const gridSheet = ss.getSheetByName("GridLost");
    if (gridSheet) {
      gridSheet.getDataRange().getValues().slice(1).forEach(function(row) {
        const rowSite = row[1], dur = Number(row[6]||0), ts = row[0];
        const rowDate = ts instanceof Date ? Utilities.formatDate(ts, Session.getScriptTimeZone(), "yyyy-MM-dd") : String(ts).slice(0,10);
        if (rowSite === site && rowDate >= startStr && rowDate <= endStr && dur > longestOutageMinutes) longestOutageMinutes = dur;
      });
    }
  } catch(e) {}

  // ── Weather from Open-Meteo (free, no API key) ──────────────────
  const siteLat = Number(dailyRows[0].latitude  || 9.9696);
  const siteLng = Number(dailyRows[0].longitude || -84.4052);
  let weather = null;
  try {
    const wUrl = "https://archive-api.open-meteo.com/v1/archive?latitude=" + siteLat.toFixed(4) +
      "&longitude=" + siteLng.toFixed(4) + "&start_date=" + startStr + "&end_date=" + endStr +
      "&daily=sunshine_duration,precipitation_sum,cloud_cover_mean,shortwave_radiation_sum&timezone=America%2FCosta_Rica";
    const wResp = UrlFetchApp.fetch(wUrl, { muteHttpExceptions: true });
    if (wResp.getResponseCode() === 200) {
      const wd = JSON.parse(wResp.getContentText()).daily || {};
      const sun   = wd.sunshine_duration       || [];   // seconds/day (display only)
      const rain  = wd.precipitation_sum       || [];   // mm/day
      const cloud = wd.cloud_cover_mean        || [];   // %
      const srad  = wd.shortwave_radiation_sum || [];   // Wh/m²/day — correct PV irradiance
      const nd = Math.max(sun.length, srad.length) || 1;
      // totalIrradiance: sum of daily kWh/m² across the week
      // Open-Meteo shortwave_radiation_sum is in MJ/m²/day. Convert to kWh/m²: ÷ 3.6
      const totalIrradianceKwh = srad.reduce(function(a,b){return a+(b||0);},0) / 3.6;
      weather = {
        avgSunshineHrs:       Number((sun.reduce(function(a,b){return a+(b||0);},0)/nd/3600).toFixed(1)),
        rainyDays:            rain.filter(function(p){return (p||0)>5;}).length,
        avgCloudPct:          Number((cloud.reduce(function(a,b){return a+(b||0);},0)/nd).toFixed(0)),
        totalIrradianceKwh:   Number(totalIrradianceKwh.toFixed(1)),
        dailySunshine:        sun.map(function(s){return Number(((s||0)/3600).toFixed(1));}),
        dailyCloud:           cloud.map(function(c){return Number((c||0).toFixed(0));}),
        dailyRadiation:       srad.map(function(w){return Number(((w||0)/1000).toFixed(2));})
      };
      Logger.log("Weather: " + JSON.stringify({sun:weather.avgSunshineHrs,rain:weather.rainyDays,cloud:weather.avgCloudPct,rad:weather.totalIrradianceKwh}));
    }
  } catch(we) { Logger.log("Weather fetch failed: " + we); }

  // ── Solar performance ratio ──────────────────────────────────────
  // expected = totalIrradiance (kWh/m²) × pvKwp × systemEfficiency (0.80)
  // When weather unavailable, fall back to CR average: 4.5 peak sun hrs/day × 0.80
  const pvKwp = Number(dailyRows[0].pv_kwp || dailyRows[0].pvKwp || 19.36);
  const SYSTEM_EFF = 0.80;
  const expectedPv = weather && weather.totalIrradianceKwh > 0
    ? Number((weather.totalIrradianceKwh * pvKwp * SYSTEM_EFF).toFixed(1))
    : Number((4.5 * dailyGrouped.length * pvKwp * SYSTEM_EFF).toFixed(1));
  const solarPerformancePct = expectedPv > 0 ? Number((totals.pv/expectedPv*100).toFixed(1)) : null;

  // ── Grid quality score (0-100) ───────────────────────────────────
  let gridQualityScore = 100;
  if (minFreq != null && maxFreq != null) {
    gridQualityScore -= Math.min(Math.round((Math.max(0,59.5-minFreq)+Math.max(0,maxFreq-60.5))*20),20);
  }
  if (minVL1 != null) { if (minVL1<108||maxVL1>132) gridQualityScore-=15; else if (minVL1<112||maxVL1>128) gridQualityScore-=8; }
  if (minVL2 != null) { if (minVL2<108||maxVL2>132) gridQualityScore-=15; else if (minVL2<112||maxVL2>128) gridQualityScore-=8; }
  if (totals.daysNoGridData > 0) gridQualityScore -= totals.daysNoGridData * 5;
  gridQualityScore = Math.max(0, Math.min(100, gridQualityScore));
  const gridQualityStatus = gridQualityScore>=90 ? (lang==="es"?"Estable":"Stable")
    : gridQualityScore>=70 ? (lang==="es"?"Fluctuaciones menores":"Minor fluctuations")
    : (lang==="es"?"Irregular":"Poor");
  const gridQualityColor = gridQualityScore>=90?"#1FAE6E":gridQualityScore>=70?"#D4860F":"#C94040";

  // ── Battery stress label ─────────────────────────────────────────
  const thr2 = CONFIG.defaultHealthThresholds;
  const battStressLabel = batteryCycles > thr2.batteryCyclesHigh
    ? (lang==="es"?"Alto estrés":"High stress")
    : batteryCycles > thr2.batteryCyclesMid ? (lang==="es"?"Uso activo":"Working hard")
    : (lang==="es"?"Normal":"Normal");
  const battStressColor = (batteryCycles > thr2.batteryCyclesMid) ? "#D4860F" : "#1FAE6E";

  // ── Generate AI narrative ────────────────────────────────────────
  const narrative = generateWeeklyNarrative({
    site: site, pv: totals.pv.toFixed(1), load: totals.load.toFixed(1),
    grid: totals.grid.toFixed(1), gridIndependencePct: gridIndependencePct,
    healthScore: avgHealth, healthStatus: healthStatus, minSoc: minSoc,
    batteryCycles: batteryCycles, daysFullCharge: totals.daysFullCharge,
    totalDays: dailyGrouped.length, outageCount: totals.outageCount,
    outageMinutes: totals.outageMinutes, longestOutageMinutes: longestOutageMinutes,
    batteryProtectedDuringOutage: (totals.outageCount > 0),
    alarmEpisodes: alarmEpisodesTotal, daysNoGridData: totals.daysNoGridData,
    bestDay: bestDay ? bestDay.pv.toFixed(1) : "n/a",
    worstDay: worstDay ? worstDay.pv.toFixed(1) : "n/a",
    weatherAvailable: weather !== null,
    avgSunshineHrs: weather ? weather.avgSunshineHrs : null,
    rainyDays: weather ? weather.rainyDays : null,
    avgCloudPct: weather ? weather.avgCloudPct : null,
    solarPerformancePct: solarPerformancePct,
    gridQualityScore: gridQualityScore,
    gridQualityStatus: gridQualityStatus
  }, lang);

  // ── Build HTML report ────────────────────────────────────────────
  const html = buildReportHtml({
    t: t, lang: lang, site: site, startStr: startStr, endStr: endStr,
    avgHealth: avgHealth, healthStatus: healthStatus, narrative: narrative,
    totals: totals, prevTotals: prevTotals,
    minSoc: minSoc, maxSoc: maxSoc, avgSoc: avgSoc,
    minVoltage: minVoltage, maxVoltage: maxVoltage, minTemp: minTemp, maxTemp: maxTemp,
    minFreq: minFreq, maxFreq: maxFreq, minVL1: minVL1, maxVL1: maxVL1, minVL2: minVL2, maxVL2: maxVL2,
    bestDay: bestDay, worstDay: worstDay, gridIndependencePct: gridIndependencePct, batteryCycles: batteryCycles,
    alarmEpisodesTotal: alarmEpisodesTotal,
    dailyRows: dailyRows, dailyGrouped: dailyGrouped, healthRows: healthRows,
    weather: weather,
    solarPerformancePct: solarPerformancePct, expectedPv: expectedPv, pvKwp: pvKwp,
    gridQualityScore: gridQualityScore, gridQualityStatus: gridQualityStatus, gridQualityColor: gridQualityColor,
    battStressLabel: battStressLabel, battStressColor: battStressColor,
    weekBuckets: weekBuckets
  });

  // ── Convert HTML to PDF ───────────────────────────────────────────
  const htmlBlob = Utilities.newBlob(html, "text/html", "report.html");
  const pdfBlob  = htmlBlob.getAs("application/pdf")
    .setName((lang === "es" ? "Reporte Semanal - " : "Weekly Report - ") + site + " - " + endStr + ".pdf");

  // ── Save to Drive ─────────────────────────────────────────────────
  let pdfFile;
  if (CONFIG.reportFolderId) {
    const rootFolder = DriveApp.getFolderById(CONFIG.reportFolderId);
    const reportsFolderName = "weekly-reports";
    const siteSlug = site.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

    let reportsRoot;
    const existingReports = rootFolder.getFoldersByName(reportsFolderName);
    reportsRoot = existingReports.hasNext() ? existingReports.next() : rootFolder.createFolder(reportsFolderName);

    let siteFolder;
    const existingSite = reportsRoot.getFoldersByName(siteSlug);
    siteFolder = existingSite.hasNext() ? existingSite.next() : reportsRoot.createFolder(siteSlug);

    pdfFile = siteFolder.createFile(pdfBlob);
  } else {
    pdfFile = DriveApp.createFile(pdfBlob);
  }

  // ── Send email with key stats inline + PDF attached ───────────────
  if (CONFIG.reportEmail) {
    const emailHtml = buildEmailHtml({
      t: t, lang: lang, site: site, startStr: startStr, endStr: endStr,
      avgHealth: avgHealth, healthStatus: healthStatus, totals: totals,
      gridIndependencePct: gridIndependencePct, batteryCycles: batteryCycles,
      narrative: narrative, days: dailyGrouped.length
    });

    MailApp.sendEmail({
      to: CONFIG.reportEmail,
      subject: (lang === "es" ? "Reporte Semanal - " : "Weekly Report - ") + site,
      htmlBody: emailHtml,
      attachments: [pdfBlob]
    });
  }

  return pdfFile.getUrl();
}

// ─────────────────────────────────────────────────────────────────
// HTML report — ALL backgrounds rendered as SVG (only thing PDF renders)
// ─────────────────────────────────────────────────────────────────
function buildReportHtml(d) {
  const t = d.t;
  const statusLabel = t.healthStatus[d.healthStatus] || d.healthStatus;
  const scoreColor = d.avgHealth >= 90 ? "#1FAE6E" : d.avgHealth >= 80 ? "#4A9FD4" : d.avgHealth >= 70 ? "#D4860F" : "#C94040";
  const badgeBg    = d.avgHealth >= 90 ? "#D9F2E6" : d.avgHealth >= 80 ? "#DCEEF8" : d.avgHealth >= 70 ? "#FDEFC5" : "#FAD9D9";
  const badgeText  = d.avgHealth >= 90 ? "#0F7D4A" : d.avgHealth >= 80 ? "#1A5F88" : d.avgHealth >= 70 ? "#9A6200" : "#8A1F1F";
  const outageKpiBg = d.totals.outageCount > 0 ? "#FEF7EC" : "#F7F9F8";

  // ── Donut SVG ─────────────────────────────────────────────────────
  const totalEnergy = d.totals.pv + d.totals.grid + d.totals.discharge;
  const solarPct = totalEnergy > 0 ? Math.round(d.totals.pv   / totalEnergy * 100) : 0;
  const gridPct  = totalEnergy > 0 ? Math.round(d.totals.grid / totalEnergy * 100) : 0;
  const battPct  = Math.max(0, 100 - solarPct - gridPct);
  const solarPctD = totalEnergy > 0 ? (d.totals.pv / totalEnergy * 100).toFixed(1) : "0.0";
  const battPctD  = totalEnergy > 0 ? (d.totals.discharge / totalEnergy * 100).toFixed(1) : "0.0";
  const gridPctD  = totalEnergy > 0 ? (d.totals.grid / totalEnergy * 100).toFixed(1) : "0.0";
  const C = 175.9;
  function seg(pct, prevSum) {
    const len = pct / 100 * C, off = (C/4) - (prevSum/100*C);
    return 'stroke-dasharray="' + len.toFixed(1) + ' ' + C.toFixed(1) + '" stroke-dashoffset="' + off.toFixed(1) + '"';
  }

  // Shared Solar/Consumption legend, right-aligned to end at `rightX`. Matches the SOC
  // chart's legend styling exactly: font-size 7, fill #aaa, 7x7 swatch at y=6, text at y=13.
  function twoBarLegend(rightX, consLabel, consColor) {
    const CW = 3.7; // approx char width at font-size 7
    const SWATCH = 7, TXTGAP = 3, ITEMGAP = 12;
    const solarW = 5 * CW, consW = consLabel.length * CW;
    const total = SWATCH + TXTGAP + solarW + ITEMGAP + SWATCH + TXTGAP + consW;
    let x = rightX - total, s = "";
    s += "<rect x='" + x.toFixed(1) + "' y='6' width='7' height='7' rx='1' fill='#1FAE6E'/>";
    s += "<text x='" + (x+SWATCH+TXTGAP).toFixed(1) + "' y='13' font-size='7' fill='#aaa'>Solar</text>";
    x += SWATCH + TXTGAP + solarW + ITEMGAP;
    s += "<rect x='" + x.toFixed(1) + "' y='6' width='7' height='7' rx='1' fill='" + consColor + "'/>";
    s += "<text x='" + (x+SWATCH+TXTGAP).toFixed(1) + "' y='13' font-size='7' fill='#aaa'>" + consLabel + "</text>";
    return s;
  }

  // ── Bar chart SVG ─────────────────────────────────────────────────
  // Title + description live INSIDE the SVG (like every other block) so they render
  // at the same scale/font as the other block descriptions, not as mismatched HTML.
  const BAR_H_MAX = 78, BAR_W = 10, BAR_GAP = 3, SVG_W = 520;
  const BAR_LPAD = 46; // room for "80 kWh"-style y-axis labels
  const barSubLines = wrapSvgLines(t.subDaily, Math.floor((SVG_W - 22) / 3.2));
  const BAR_HDR_H = 16 + barSubLines.length * 10; // title + wrapped description
  const chartTopY = BAR_HDR_H + 6;                // y of the top (max) gridline
  const baseYbar = chartTopY + BAR_H_MAX;
  const SVG_H = baseYbar + 18;                     // + day-label row
  const n = d.dailyGrouped.length, slotW = (SVG_W - BAR_LPAD) / Math.max(n, 1);
  const allVals = [];
  d.dailyGrouped.forEach(function(r) { allVals.push(Number(r.pv_kWh||0)); allVals.push(Number(r.load_kWh||0)); });
  const maxVal = Math.max.apply(null, allVals.length ? allVals : [1]) || 1;
  const yMax = Math.ceil(maxVal / 10) * 10 || 10;
  function barH(v) { return Math.max(1, Math.round((Number(v)||0) / yMax * BAR_H_MAX)); }
  const dayAbbr = d.lang === "es"
    ? ["Dom","Lun","Mar","Mi\u00e9","Jue","Vie","S\u00e1b"]
    : ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
  let svgRects = "<text x='11' y='12' font-size='8' font-weight='700' fill='#777'>" + t.sectionDaily.toUpperCase() + "</text>";
  barSubLines.forEach(function(line, li) {
    svgRects += "<text x='11' y='" + (12+(li+1)*10) + "' font-size='7' fill='#bbb'>" + line + "</text>";
  });
  svgRects += twoBarLegend(SVG_W - 20, d.lang==="es"?"Consumo":"Consumption", "#C8DDD5");
  [0, Math.round(yMax/2), yMax].forEach(function(val) {
    const gy = baseYbar - Math.round(val/yMax*BAR_H_MAX);
    svgRects += "<line x1='" + BAR_LPAD + "' y1='" + gy + "' x2='" + SVG_W + "' y2='" + gy + "' stroke='#EAEDEB' stroke-width='0.5'/>";
    svgRects += "<text x='" + (BAR_LPAD-3) + "' y='" + (gy+3) + "' text-anchor='end' font-size='7' fill='#bbb'>" + val + " kWh</text>";
  });
  d.dailyGrouped.forEach(function(r, i) {
    const cx = BAR_LPAD + slotW*i+slotW/2, pvH = barH(r.pv_kWh), loadH = barH(r.load_kWh);
    const pvX = cx-BAR_W-BAR_GAP/2, loadX = cx+BAR_GAP/2;
    svgRects +=
      "<rect x='" + pvX.toFixed(1) + "' y='" + (baseYbar-pvH).toFixed(1) + "' width='" + BAR_W + "' height='" + pvH + "' fill='#1FAE6E' rx='1'/>" +
      "<rect x='" + loadX.toFixed(1) + "' y='" + (baseYbar-loadH).toFixed(1) + "' width='" + BAR_W + "' height='" + loadH + "' fill='#C8DDD5' rx='1'/>" +
      "<text x='" + cx.toFixed(1) + "' y='" + (SVG_H-4) + "' text-anchor='middle' font-size='8' fill='#aaa'>" + dayAbbr[new Date(r.date+"T12:00:00").getDay()] + "</text>";
  });
  // No fixed height / preserveAspectRatio — like the SOC chart, this lets the SVG fill
  // the full container width (height derived from the viewBox) instead of letterboxing.
  const barSvg = "<svg width='100%' viewBox='0 0 " + SVG_W + " " + SVG_H + "' xmlns='http://www.w3.org/2000/svg'>" + svgRects + "</svg>";

  // ── KPI cards as one wide SVG ─────────────────────────────────────
  // Each card: rect background + text elements. No HTML backgrounds needed.
  const PW = 530, GAP = 8, CW = (PW - GAP*3) / 4, CH = 80, PAD = 11;
  // Build each KPI card manually for precise text placement
  // Using tspan for inline mixed-size text within one <text> element
  function kpiRect(x, bg) {
    return "<rect x='" + x + "' y='0' width='" + CW.toFixed(1) + "' height='" + CH + "' rx='8' fill='" + bg + "'/>";
  }
  function kpiLabel(x, label) {
    return "<text x='" + (x+PAD) + "' y='17' font-size='7' font-weight='600' fill='#999'>" + label + "</text>";
  }
  function kpiValue(x, val, unit, color) {
    return "<text x='" + (x+PAD) + "' y='43' font-size='21' font-weight='700' fill='" + color + "'>" + val +
           "<tspan font-size='11' font-weight='400' fill='#999'>" + unit + "</tspan></text>";
  }
  function kpiWow(x, pct, positiveIsGood) {
    if (pct === null) return "";
    const good = positiveIsGood ? pct >= 0 : pct <= 0;
    const col  = good ? "#1FAE6E" : "#D4860F";
    const sign = pct >= 0 ? "+" : "";
    return "<text x='" + (x+PAD) + "' y='57' font-size='8' fill='" + col + "'>" + sign + pct + "% " + t.wowTrendLabel + "</text>";
  }
  function kpiSub(x, txt, color) {
    return "<text x='" + (x+PAD) + "' y='70' font-size='8' fill='" + (color||"#aaa") + "'>" + txt + "</text>";
  }
  function kpiBadge(x, txt, bg, fg) {
    const bw = Math.min(txt.length * 6 + 14, CW - PAD*2);
    return "<rect x='" + (x+PAD) + "' y='58' width='" + bw.toFixed(0) + "' height='15' rx='7.5' fill='" + bg + "'/>" +
           "<text x='" + (x+PAD+7) + "' y='69' font-size='8.5' font-weight='600' fill='" + fg + "'>" + txt + "</text>";
  }

  const outageSubStr = d.totals.outageCount > 0 ? d.totals.outageMinutes + " " + t.minutes : (d.lang === "es" ? "Sin cortes" : "No outages");
  const outageSubColor = d.totals.outageCount > 0 ? "#D4860F" : "#1FAE6E";

  // Week-over-week delta helpers
  function wowPct(curr, prev) {
    if (!prev || prev === 0) return null;
    return Math.round((curr - prev) / prev * 100);
  }

  const pvPct  = d.prevTotals ? wowPct(d.totals.pv, d.prevTotals.pv) : null;
  const prevGI = d.prevTotals && d.prevTotals.load > 0
    ? (100 - (d.prevTotals.grid / d.prevTotals.load) * 100) : null;
  const giPct  = wowPct(d.gridIndependencePct, prevGI);
  const bestDaySub = "Best: " + (d.bestDay ? d.bestDay.pv.toFixed(1) + " " + t.kwh : "—");
  const giSub = d.totals.daysSelfSufficient + "/" + d.dailyGrouped.length + " " + t.days;

  const x2 = CW + GAP, x3 = (CW+GAP)*2, x4 = (CW+GAP)*3;

  let kpiContent =
    // Card 1: Health
    kpiRect(0, "#EEF9F4") +
    kpiLabel(0, t.healthScore.toUpperCase()) +
    kpiValue(0, String(d.avgHealth), "/100", scoreColor) +
    kpiBadge(0, statusLabel, badgeBg, badgeText) +
    // Card 2: Solar
    kpiRect(x2, "#F7F9F8") +
    kpiLabel(x2, t.pvGenerated.toUpperCase()) +
    kpiValue(x2, d.totals.pv.toFixed(1), " " + t.kwh, "#111") +
    kpiWow(x2, pvPct, true) +
    kpiSub(x2, bestDaySub) +
    // Card 3: Grid independence
    kpiRect(x3, "#F7F9F8") +
    kpiLabel(x3, t.gridIndependence.toUpperCase()) +
    kpiValue(x3, String(d.gridIndependencePct) + "%", "", "#1FAE6E") +
    kpiWow(x3, giPct, true) +
    kpiSub(x3, giSub) +
    // Card 4: Outages
    kpiRect(x4, outageKpiBg) +
    kpiLabel(x4, t.outages.toUpperCase()) +
    kpiValue(x4, String(d.totals.outageCount), "", d.totals.outageCount > 0 ? "#D4860F" : "#111") +
    kpiSub(x4, outageSubStr, outageSubColor);

  const kpiSvg = "<svg width='100%' viewBox='0 0 " + PW + " " + CH + "' xmlns='http://www.w3.org/2000/svg'>" + kpiContent + "</svg>";

  // ── Info blocks as SVG ────────────────────────────────────────────
  // Each block: bgcolor rect + title + rows of label/value pairs
  const IW = (PW - GAP) / 2, IPAD = 11, ROW_H = 20, TITLE_Y = 22;
  // Word-wrap width for font-size 6.5 subtitles. ~3.1px/char matches the real rendered
  // width of lowercase-heavy text, so lines fill the box before wrapping (3.4 wrapped early).
  const SUB_MAX_CHARS = Math.floor((IW - 2*IPAD) / 3.1);

  // Word-wraps text to fit maxChars per line (SVG <text> doesn't wrap on its own).
  function wrapSvgLines(text, maxChars) {
    if (!text) return [];
    const words = String(text).split(" ");
    const lines = [];
    let cur = "";
    words.forEach(function(w) {
      const t2 = cur ? cur + " " + w : w;
      if (t2.length > maxChars && cur) { lines.push(cur); cur = w; } else { cur = t2; }
    });
    if (cur) lines.push(cur);
    return lines;
  }

  // Y-offset (from block top) where the first row starts, given a wrapped subtitle.
  // Shared by infoBlockSvg and measureInfoBlock so height and layout never drift apart.
  function infoBlockFirstRowY(subtitle) {
    const subLines = subtitle ? wrapSvgLines(subtitle, SUB_MAX_CHARS) : [];
    return 14 + subLines.length * 9 + 8 + 12; // title + subtitle lines + sep gap + row gap
  }

  // Total block height needed for a given row/subtitle combo — single source of truth
  // for both the SVG renderer below and the callers that size sibling blocks.
  function measureInfoBlock(rows, subtitle) {
    return infoBlockFirstRowY(subtitle) + (rows.length - 1) * ROW_H + 16; // + bottom padding
  }

  function infoBlockSvg(x, y, bg, title, rows, totalH, subtitle) {
    const subLines = subtitle ? wrapSvgLines(subtitle, SUB_MAX_CHARS) : [];
    let out = "<rect x='" + x.toFixed(1) + "' y='" + y + "' width='" + IW.toFixed(1) + "' height='" + totalH + "' rx='8' fill='" + bg + "'/>";
    out += "<text x='" + (x+IPAD) + "' y='" + (y+14) + "' font-size='8' font-weight='700' fill='#777'>" + title.toUpperCase() + "</text>";
    subLines.forEach(function(line, li) {
      out += "<text x='" + (x+IPAD) + "' y='" + (y+14+(li+1)*9) + "' font-size='6.5' fill='#bbb'>" + line + "</text>";
    });
    const firstRowY = y + infoBlockFirstRowY(subtitle);
    out += "<line x1='" + (x+IPAD) + "' y1='" + (firstRowY-12) + "' x2='" + (x+IW-IPAD) + "' y2='" + (firstRowY-12) + "' stroke='#E8EDEA' stroke-width='0.5'/>";
    rows.forEach(function(row, i) {
      const ry = firstRowY + i * ROW_H;
      out += "<text x='" + (x+IPAD) + "' y='" + ry + "' font-size='9.5' fill='#999'>" + row.label + "</text>";
      out += "<text x='" + (x+IW-IPAD) + "' y='" + ry + "' font-size='9.5' font-weight='600' fill='" + (row.valueColor||"#222") + "' text-anchor='end'>" + row.value + "</text>";
      if (i < rows.length - 1) {
        out += "<line x1='" + (x+IPAD) + "' y1='" + (ry+5) + "' x2='" + (x+IW-IPAD) + "' y2='" + (ry+5) + "' stroke='#E8EDEA' stroke-width='0.5'/>";
      }
    });
    return out;
  }

  // Energy mix: left block with donut SVG embedded as image — use separate HTML table for this
  // Info blocks: battery, grid, events — pure SVG

  const battRows = [
    {label: t.daysFullCharge, value: d.totals.daysFullCharge + " / " + d.dailyGrouped.length + " " + t.days, valueColor: "#1FAE6E"},
    {label: t.lowestSoc, value: d.minSoc != null ? d.minSoc + "%" : "—"},
    {label: t.avgTemp, value: d.maxTemp != null ? d.maxTemp.toFixed(1) + " °C" : "—"},
    {label: t.batteryHealthLabel, value: d.battStressLabel + " (" + d.batteryCycles + " cyc)", valueColor: d.battStressColor},
    {label: t.voltageRange, value: d.minVoltage != null ? d.minVoltage.toFixed(1) + " – " + d.maxVoltage.toFixed(1) + " V" : "—"}
  ];
  const gridRows = [
    {label: t.avgFrequency, value: d.minFreq != null ? d.minFreq.toFixed(2) + " – " + d.maxFreq.toFixed(2) + " Hz" : "—"},
    {label: t.voltageRangeL1, value: d.minVL1 != null ? d.minVL1.toFixed(1) + " – " + d.maxVL1.toFixed(1) + " V" : "—"},
    {label: t.voltageRangeL2, value: d.minVL2 != null ? d.minVL2.toFixed(1) + " – " + d.maxVL2.toFixed(1) + " V" : "—"},
    {label: t.gridDataDays, value: (d.dailyGrouped.length - d.totals.daysNoGridData) + " / " + d.dailyGrouped.length},
    {label: t.gridQualityScore, value: d.gridQualityScore + "/100 — " + d.gridQualityStatus, valueColor: d.gridQualityColor}
  ];
  const outageRowVal = d.totals.outageCount === 0
    ? (d.lang === "es" ? "Sin cortes" : "No outages")
    : d.totals.outageCount + " (" + d.totals.outageMinutes + " min)";
  const eventsRows = [
    {label: t.outages, value: outageRowVal, valueColor: d.totals.outageCount > 0 ? "#D4860F" : "#222"},
    {label: t.alarmEpisodes, value: String(d.alarmEpisodesTotal)}
  ];

  const BATT_H   = measureInfoBlock(battRows, t.subBattery);
  const GRID_H   = measureInfoBlock(gridRows, t.subGrid);
  const EVENTS_H = measureInfoBlock(eventsRows, t.subEvents);
  const ROW2_H = Math.max(GRID_H, EVENTS_H);

  // Row 2 info SVG: grid + events
  const row2SvgContent =
    infoBlockSvg(0, 0, "#F7F9F8", t.sectionGrid, gridRows, GRID_H, t.subGrid) +
    infoBlockSvg(IW + GAP, 0, "#F7F9F8", t.sectionEvents, eventsRows, EVENTS_H, t.subEvents);
  const row2InfoSvg = "<svg width='100%' viewBox='0 0 " + PW + " " + ROW2_H + "' xmlns='http://www.w3.org/2000/svg'>" + row2SvgContent + "</svg>";

  // ── Row 1: energy mix + battery — single SVG for correct alignment ──
  // Donut at left, legend text beside it, battery block at right column.
  // All in one SVG so columns align perfectly.
  // Energy-mix subtitle can wrap to 2 lines; start the donut below it (with a gap) instead
  // of centering it in the whole block, so it never crowds the description.
  const emSubLines = wrapSvgLines(t.subEnergyMix, Math.floor((IW - 2*IPAD) / 3.4));
  const emHeadH = 16 + emSubLines.length * 9 + 12; // title + subtitle lines + gap before donut
  const ROW1_H = Math.max(BATT_H, emHeadH + 72 + 8);
  const DX = 8, DY = Math.max(emHeadH, (ROW1_H - 72) / 2); // below the header, centered if room
  const LX = DX + 80; // legend text x start
  const battX = IW + GAP;

  const energyMixSvgBlock =
    // Background for energy mix (light grey like other blocks)
    "<rect x='0' y='0' width='" + IW.toFixed(1) + "' height='" + ROW1_H + "' rx='8' fill='#F7F9F8'/>" +
    // Title
    "<text x='" + IPAD + "' y='16' font-size='8' font-weight='700' fill='#777'>" + t.energyMix.toUpperCase() + "</text>" +
    // This subtitle renders at font-size 7 (not 6.5), so it needs a wider px/char (~3.4)
    // than SUB_MAX_CHARS — reusing that here would let a line overflow the box.
    emSubLines.map(function(line, li) {
      return "<text x='" + IPAD + "' y='" + (16+(li+1)*9) + "' font-size='7' fill='#bbb'>" + line + "</text>";
    }).join("") +
    // Donut
    "<g transform='translate(" + DX + "," + DY.toFixed(0) + ")'>" +
      "<circle cx='36' cy='36' r='28' fill='none' stroke='#E8EDEA' stroke-width='11'/>" +
      "<circle cx='36' cy='36' r='28' fill='none' stroke='#1FAE6E' stroke-width='11' " + seg(solarPct,0) + " stroke-linecap='butt'/>" +
      "<circle cx='36' cy='36' r='28' fill='none' stroke='#4A9FD4' stroke-width='11' " + seg(battPct,solarPct) + " stroke-linecap='butt'/>" +
      "<circle cx='36' cy='36' r='28' fill='none' stroke='#C8DDD5' stroke-width='11' " + seg(gridPct,solarPct+battPct) + " stroke-linecap='butt'/>" +
      "<text x='36' y='39' text-anchor='middle' font-size='12' font-weight='700' fill='#111'>" + solarPctD + "%</text>" +
      "<text x='36' y='50' text-anchor='middle' font-size='8' fill='#999'>solar</text>" +
    "</g>" +
    // Legend rows
    "<circle cx='" + (LX+4) + "' cy='" + (DY+22) + "' r='4' fill='#1FAE6E'/>" +
    "<text x='" + (LX+12) + "' y='" + (DY+26) + "' font-size='9' fill='#555'>Solar</text>" +
    "<text x='" + (LX+55) + "' y='" + (DY+26) + "' font-size='9' font-weight='600' fill='#222'>" + solarPctD + "% · " + d.totals.pv.toFixed(1) + " " + t.kwh + "</text>" +
    "<circle cx='" + (LX+4) + "' cy='" + (DY+42) + "' r='4' fill='#4A9FD4'/>" +
    "<text x='" + (LX+12) + "' y='" + (DY+46) + "' font-size='9' fill='#555'>" + (d.lang==="es"?"Batería":"Battery") + "</text>" +
    "<text x='" + (LX+55) + "' y='" + (DY+46) + "' font-size='9' font-weight='600' fill='#222'>" + battPctD + "% · " + d.totals.discharge.toFixed(1) + " " + t.kwh + "</text>" +
    "<circle cx='" + (LX+4) + "' cy='" + (DY+62) + "' r='4' fill='#C8DDD5'/>" +
    "<text x='" + (LX+12) + "' y='" + (DY+66) + "' font-size='9' fill='#555'>" + (d.lang==="es"?"Red":"Grid") + "</text>" +
    "<text x='" + (LX+55) + "' y='" + (DY+66) + "' font-size='9' font-weight='600' fill='#222'>" + gridPctD + "% · " + d.totals.grid.toFixed(1) + " " + t.kwh + "</text>" +
    // Battery block at right
    infoBlockSvg(battX, 0, "#F7F9F8", t.sectionBattery, battRows, ROW1_H, t.subBattery);

  const row1Svg = "<svg width='100%' viewBox='0 0 " + PW + " " + ROW1_H + "' xmlns='http://www.w3.org/2000/svg'>" + energyMixSvgBlock + "</svg>";

  // Narrative
  const narrativeHtml = d.narrative.split("\n").filter(function(p){return p.trim().length>0;})
    .map(function(p){return "<p style='margin:0 0 7px 0;'>" + p + "</p>";}).join("");

  const css =
    "@page { margin: 28px 32px; size: A4; }" +
    "* { box-sizing: border-box; margin: 0; padding: 0; }" +
    "body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #111; font-size: 11px; line-height: 1.5; }" +
    ".hdr { width: 100%; border-bottom: 2px solid #1FAE6E; padding-bottom: 13px; margin-bottom: 18px; display: table; }" +
    ".hdr-l { display: table-cell; vertical-align: bottom; }" +
    ".hdr-r { display: table-cell; text-align: right; vertical-align: bottom; }" +
    ".brand { font-size: 9.5px; font-weight: 600; color: #1FAE6E; letter-spacing: 0.08em; text-transform: uppercase; }" +
    ".site  { font-size: 15px; font-weight: 600; color: #111; margin-top: 3px; }" +
    ".period { font-size: 10px; color: #999; margin-top: 2px; }" +
    ".rlabel { font-size: 10px; color: #999; }" +
    ".rlabel strong { display: block; font-size: 12px; color: #333; font-weight: 600; margin-bottom: 1px; }" +
    ".narr { border-left: 3px solid #1FAE6E; padding: 9px 13px; margin-bottom: 16px; font-size: 10.5px; color: #333; line-height: 1.65; font-style: italic; }" +
    ".slbl { font-size: 8.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.09em; color: #bbb; margin-bottom: 6px; margin-top: 14px; }" +
    ".leg { display: table; margin-top: 6px; margin-bottom: 14px; }" +
    ".li { display: table-cell; font-size: 9px; color: #888; padding-right: 14px; vertical-align: middle; }" +
    ".ld { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }" +

    ".ftr { margin-top: 18px; padding-top: 9px; border-top: 0.5px solid #E5EAE7; display: table; width: 100%; }" +
    ".fl { display: table-cell; font-size: 8.5px; color: #ccc; }" +
    ".fr { display: table-cell; font-size: 8.5px; color: #ccc; text-align: right; }";

  return "<!DOCTYPE html><html lang='" + d.lang + "'><head><meta charset='UTF-8'>" +
    "<style>" + css + "</style></head><body>" +

    "<div class='hdr'>" +
      "<div class='hdr-l'>" +
        "<div class='brand'>Pauly &amp; Co.</div>" +
        "<div class='site'>" + d.site + "</div>" +
        "<div class='period'>" + t.dateRange + ": " + d.startStr + " &#8212; " + d.endStr + "</div>" +
      "</div>" +
      "<div class='hdr-r'><div class='rlabel'><strong>" + t.reportTitle + "</strong>" +
        (d.lang === "es" ? "Weekly energy report" : "Reporte semanal de energ&#x00ED;a") +
      "</div></div>" +
    "</div>" +

    // KPI cards — full SVG, backgrounds guaranteed to render
    kpiSvg +

    // Narrative — border-left renders, background won't but that's acceptable
    "<div class='narr' style='margin-top:14px;'>" + narrativeHtml + "</div>" +

    // Legend now lives inside barSvg (top-right), matching the SOC chart.
    "<div style='margin-top:14px; margin-bottom:12px;'>" + barSvg + "</div>" +

    // Row 1: energy mix + battery — single SVG
    row1Svg +

    // Row 2: grid + events
    "<div style='margin-top:10px;'>" + row2InfoSvg + "</div>" +

    // ── PAGE 2 — Battery, Performance, Weather, Trends ─────────────
    "<div style='page-break-before:always; padding-top:20px;'>" +
      "<div style='border-bottom:2px solid #1FAE6E; padding-bottom:10px; margin-bottom:18px; display:table; width:100%;'>" +
        "<span style='display:table-cell; font-size:9.5px; font-weight:600; color:#1FAE6E; letter-spacing:0.08em; text-transform:uppercase;'>Pauly &amp; Co.</span>" +
        "<span style='display:table-cell; text-align:right; font-size:10px; color:#999;'>" + d.site + " &middot; " + d.startStr + " &#8212; " + d.endStr + "</span>" +
      "</div>" +

    // SOC timeline mini-chart
    (function() {
      const SH = 168, SW = PW, SPAD = 30, SPH = 112, SPY = 34;
      function sY(p) { return SPY + SPH - (p/100*SPH); }
      let sc = "<rect x='0' y='0' width='" + SW + "' height='" + SH + "' rx='8' fill='#F7F9F8'/>";
      sc += "<text x='" + IPAD + "' y='12' font-size='8' font-weight='700' fill='#777'>" + t.socTimeline.toUpperCase() + "</text>";sc += "<text x='" + IPAD + "' y='22' font-size='7' fill='#bbb'>" + t.subSocChart + "</text>";sc += "<rect x='" + (SW-SPAD-95) + "' y='6' width='7' height='7' rx='1' fill='#1FAE6E' fill-opacity='0.3'/>";sc += "<text x='" + (SW-SPAD-86) + "' y='13' font-size='7' fill='#aaa'>Max SOC (band)</text>";sc += "<circle cx='" + (SW-SPAD-22) + "' cy='10' r='3' fill='#1FAE6E'/>";sc += "<text x='" + (SW-SPAD-17) + "' y='13' font-size='7' fill='#aaa'>Min SOC</text>";
      [0,50,100].forEach(function(p) {
        const y2 = sY(p);
        sc += "<line x1='" + SPAD + "' y1='" + y2.toFixed(1) + "' x2='" + (SW-SPAD) + "' y2='" + y2.toFixed(1) + "' stroke='#E8EDEA' stroke-width='0.5'/>";
        sc += "<text x='" + (SPAD-3) + "' y='" + (y2+3).toFixed(1) + "' font-size='7' fill='#ccc' text-anchor='end'>" + p + "%</text>";
      });
      const nd3 = d.dailyGrouped.length;
      const sw3 = (SW-SPAD*2)/Math.max(nd3-1,1);
      // Build band only from days with valid data
      let bp = "", bpR = "", firstMax = true, firstMin = true;
      let ml = "";
      d.dailyGrouped.forEach(function(r, i) {
        const x3 = SPAD + i*sw3;
        if (r.max_soc != null) {
          bp += (firstMax?"M":"L") + x3.toFixed(1) + "," + sY(r.max_soc).toFixed(1) + " ";
          firstMax = false;
        }
        if (r.min_soc != null) {
          bpR = "L" + x3.toFixed(1) + "," + sY(r.min_soc).toFixed(1) + " " + bpR;
          ml += (firstMin?"M":"L") + x3.toFixed(1) + "," + sY(r.min_soc).toFixed(1) + " ";
          firstMin = false;
        }
      });
      if (bp && bpR) sc += "<path d='" + bp + bpR + "Z' fill='#1FAE6E' fill-opacity='0.12'/>";
      if (ml) sc += "<path d='" + ml + "' fill='none' stroke='#1FAE6E' stroke-width='1.5'/>";
      d.dailyGrouped.forEach(function(r, i) {
        const x3 = SPAD + i*sw3, mp = r.min_soc!=null?r.min_soc:0;
        const dy3 = sY(mp);
        sc += "<circle cx='" + x3.toFixed(1) + "' cy='" + dy3.toFixed(1) + "' r='2.5' fill='#1FAE6E'/>";
        sc += "<text x='" + x3.toFixed(1) + "' y='" + (SH-5) + "' text-anchor='middle' font-size='7.5' fill='#aaa'>" + dayAbbr[new Date(r.date+"T12:00:00").getDay()] + "</text>";
        if (mp < 40) sc += "<text x='" + (x3+4).toFixed(1) + "' y='" + (dy3-4).toFixed(1) + "' font-size='7' fill='#D4860F'>" + mp + "%</text>";
      });
      return "<div style='margin-top:10px;'><svg width='100%' viewBox='0 0 " + SW + " " + SH + "' xmlns='http://www.w3.org/2000/svg'>" + sc + "</svg></div>";
    })() +

    // Solar performance + weather blocks (side by side)
    (function() {
      const perfRows = [
        {label: t.solarActual,        value: d.totals.pv.toFixed(1) + " " + t.kwh},
        {label: t.solarExpected,      value: d.expectedPv!=null?d.expectedPv.toFixed(1)+" "+t.kwh:"—"},
        {label: t.solarPerformancePct, value: d.solarPerformancePct!=null?d.solarPerformancePct+"%":"—",
         valueColor: d.solarPerformancePct>=90?"#1FAE6E":d.solarPerformancePct>=70?"#D4860F":"#C94040"}
      ];
      const wRows = d.weather ? [
        {label: t.weatherSunshine,  value: d.weather.avgSunshineHrs + " hrs/day"},
        {label: t.weatherRainDays,  value: d.weather.rainyDays + " days (>5mm)"},
        {label: t.weatherCloudCover, value: d.weather.avgCloudPct + "%"}
      ] : [{label: t.weatherUnavailable, value: ""}];
      const PH3 = measureInfoBlock(perfRows, t.subSolarPerf);
      const WH3 = measureInfoBlock(wRows, t.subWeather);
      const R3H = Math.max(PH3, WH3);
      const r3c = infoBlockSvg(0, 0, "#F7F9F8", t.solarPerformance, perfRows, R3H, t.subSolarPerf) +
                  infoBlockSvg(IW+GAP, 0, d.weather?"#EEF9F4":"#F7F9F8", t.weatherTitle, wRows, R3H, t.subWeather);
      return "<div style='margin-top:10px;'><svg width='100%' viewBox='0 0 " + PW + " " + R3H + "' xmlns='http://www.w3.org/2000/svg'>" + r3c + "</svg></div>";
    })() +

    // 4-week solar trend — full width (mirrors the daily chart, which renders reliably)
    (function() {
      const FW = PW;               // full page width
      const F_LPAD = 46;           // y-axis label room ("850 kWh")
      const F_RPAD = IPAD;
      const BM4 = 60;              // max bar height
      const BW4 = 15, BAR4GAP = 3; // bar width + gap within a week's pair
      const sub4Lines = wrapSvgLines(t.sub4Week, Math.floor((FW - 22) / 3.2));
      const HDR4 = 16 + sub4Lines.length * 10;
      const chartTop4 = HDR4 + 14;         // y of top gridline — gap below the description
      const baseline4 = chartTop4 + BM4;
      const dateY = baseline4 + 16;
      const trendY = baseline4 + 30;       // arrow row, with a gap below the date labels
      const noteY = trendY + 16;           // caption explaining the arrows
      const BOXH = noteY + 6;
      const allW4 = d.weekBuckets.reduce(function(a,b){return a.concat([b.pv,b.load||0]);}, []);
      const maxW4 = Math.max.apply(null, allW4.filter(function(v){return v>0;})) || 1;
      const yMax4 = Math.ceil(maxW4/50)*50 || 100; // round to nearest 50 kWh
      const nW = d.weekBuckets.length;
      const slotW = (FW - F_LPAD - F_RPAD) / Math.max(nW, 1);
      function cxOf(i) { return F_LPAD + slotW*(i+0.5); }
      function bh4(v) { return Math.max(v>0?2:0, Math.round(v/yMax4*BM4)); }
      let fc = "<rect x='0' y='0' width='" + FW + "' height='" + BOXH + "' rx='8' fill='#F7F9F8'/>";
      fc += "<text x='11' y='12' font-size='8' font-weight='700' fill='#777'>" + t.fourWeekChart.toUpperCase() + "</text>";
      sub4Lines.forEach(function(line, li) {
        fc += "<text x='11' y='" + (12+(li+1)*10) + "' font-size='7' fill='#bbb'>" + line + "</text>";
      });
      // Legend, top-right — shared style with the SOC and daily charts
      fc += twoBarLegend(FW - 20, d.lang==="es"?"Consumo":"Consumption", "#E0E8E4");
      // Gridlines — units on every line
      [0, Math.round(yMax4/2), yMax4].forEach(function(val) {
        const gy4 = baseline4 - Math.round(val/yMax4*BM4);
        fc += "<line x1='" + F_LPAD + "' y1='" + gy4 + "' x2='" + (FW-F_RPAD) + "' y2='" + gy4 + "' stroke='#E8EDEA' stroke-width='0.5'/>";
        fc += "<text x='" + (F_LPAD-3) + "' y='" + (gy4+3) + "' text-anchor='end' font-size='7' fill='#bbb'>" + val + " kWh</text>";
      });
      d.weekBuckets.forEach(function(b, i) {
        const cx = cxOf(i);
        const pvBh = bh4(b.pv), pvBy = baseline4 - pvBh;
        const ldBh = bh4(b.load||0), ldBy = baseline4 - ldBh;
        const pvBx = cx - BW4 - BAR4GAP/2, ldBx = cx + BAR4GAP/2;
        const cur = (i === nW-1);
        fc += "<rect x='" + pvBx.toFixed(1) + "' y='" + pvBy + "' width='" + BW4 + "' height='" + pvBh + "' rx='2' fill='" + (cur?"#1FAE6E":"#C8DDD5") + "'/>";
        fc += "<rect x='" + ldBx.toFixed(1) + "' y='" + ldBy + "' width='" + BW4 + "' height='" + ldBh + "' rx='2' fill='#E0E8E4'/>";
        fc += "<text x='" + cx.toFixed(1) + "' y='" + dateY + "' text-anchor='middle' font-size='8' fill='#aaa'>" + b.label + "</text>";
        if (b.pv > 0) fc += "<text x='" + (pvBx+BW4/2).toFixed(1) + "' y='" + (pvBy-3) + "' text-anchor='middle' font-size='7.5' fill='" + (cur?"#1FAE6E":"#aaa") + "'>" + b.pv + "</text>";
        // %-change vs the previous week, anchored under THIS week's bar (the week it
        // describes) so it lines up with a specific bar instead of floating between two.
        if (i > 0 && d.weekBuckets[i-1].pv > 0 && b.pv > 0) {
          const pctChg = Math.round((b.pv - d.weekBuckets[i-1].pv) / d.weekBuckets[i-1].pv * 100);
          const up = pctChg >= 0;
          // Anchored under the SOLAR bar (not the week center) so it's clear the change
          // is about solar production only, not the consumption bar beside it.
          const scx = pvBx + BW4/2;
          // Neutral color — a week-to-week change in solar is weather, not good/bad. The
          // ▲/▼ glyph carries direction; color must not imply the customer did something wrong.
          fc += "<text x='" + scx.toFixed(1) + "' y='" + trendY + "' text-anchor='middle' font-size='7.5' fill='#777'>" + (up?"▲ ":"▼ ") + (up?"+":"") + pctChg + "%</text>";
        }
      });
      // Caption explaining what the ▲▼ percentages mean, so the customer doesn't have to guess.
      fc += "<text x='11' y='" + noteY + "' font-size='7' fill='#bbb'>" + t.trendNote + "</text>";
      return "<div style='margin-top:10px;'><svg width='100%' viewBox='0 0 " + FW + " " + BOXH + "' xmlns='http://www.w3.org/2000/svg'>" + fc + "</svg></div>";
    })() +

    // Estimated tariff savings — full-width placeholder below the 4-week trend, until the
    // Supabase-backed tariff calculation (dimensionador-fv) is wired in.
    (function() {
      const W = PW, PADX = 11;
      const subLines = wrapSvgLines(t.subSavings, Math.floor((W - 2*PADX) / 3.1));
      const sepY = 14 + subLines.length * 9 + 8;
      const rowY = sepY + 16;
      const H = rowY + 4;
      let s = "<rect x='0' y='0' width='" + W + "' height='" + H + "' rx='8' fill='#F7F9F8'/>";
      s += "<text x='" + PADX + "' y='14' font-size='8' font-weight='700' fill='#777'>" + t.tariffSavings.toUpperCase() + "</text>";
      subLines.forEach(function(line, li) {
        s += "<text x='" + PADX + "' y='" + (14+(li+1)*9) + "' font-size='6.5' fill='#bbb'>" + line + "</text>";
      });
      s += "<line x1='" + PADX + "' y1='" + sepY + "' x2='" + (W-PADX) + "' y2='" + sepY + "' stroke='#E8EDEA' stroke-width='0.5'/>";
      s += "<text x='" + PADX + "' y='" + rowY + "' font-size='9.5' fill='#999'>" + t.tariffComingSoon + "</text>";
      s += "<text x='" + (W-PADX) + "' y='" + rowY + "' text-anchor='end' font-size='9.5' font-weight='600' fill='#bbb'>&#8212; soon</text>";
      return "<div style='margin-top:10px;'><svg width='100%' viewBox='0 0 " + W + " " + H + "' xmlns='http://www.w3.org/2000/svg'>" + s + "</svg></div>";
    })() +

    "</div>" +   // close page-2 div

    "<div class='ftr'>" +
      "<span class='fl'>" + t.poweredBy + " &middot; proyectos@paulyco.com</span>" +
      "<span class='fr'>" + t.pageOf + " 1</span>" +
    "</div>" +

    "</body></html>";
}

// ─────────────────────────────────────────────────────────────────
// Email HTML — key stats inline, bilingual
// ─────────────────────────────────────────────────────────────────
function buildEmailHtml(d) {
  const t = d.t;
  const statusLabel = t.healthStatus[d.healthStatus] || d.healthStatus;
  const scoreColor = d.avgHealth >= 90 ? "#1FAE6E" : d.avgHealth >= 80 ? "#4A9FD4" : d.avgHealth >= 70 ? "#D4860F" : "#C94040";
  const badgeBg    = d.avgHealth >= 90 ? "#D9F2E6" : d.avgHealth >= 80 ? "#DCEEF8" : d.avgHealth >= 70 ? "#FDEFC5" : "#FAD9D9";
  const badgeText  = d.avgHealth >= 90 ? "#0F7D4A" : d.avgHealth >= 80 ? "#1A5F88" : d.avgHealth >= 70 ? "#9A6200" : "#8A1F1F";

  // Feel-good takeaway line: produced more than used, or how much of usage was covered.
  const surplus = d.totals.load > 0 ? Math.round((d.totals.pv - d.totals.load) / d.totals.load * 100) : null;
  let surplusLine = "";
  if (surplus !== null) {
    if (surplus >= 0) {
      surplusLine = d.lang === "es"
        ? "Produjo " + surplus + "% m&#225;s energ&#237;a de la que su hogar consumi&#243; esta semana."
        : "You produced " + surplus + "% more energy than your home used this week.";
    } else {
      const coverage = Math.round(d.totals.pv / d.totals.load * 100);
      surplusLine = d.lang === "es"
        ? "Sus paneles cubrieron el " + coverage + "% de lo que su hogar consumi&#243; esta semana."
        : "Your panels covered " + coverage + "% of what your home used this week.";
    }
  }
  // Plain-language highlight: 1-2 sentences from the weekly summary. Prefer sentences after
  // the first (battery/weather context) so it complements the surplus line above rather than
  // repeating it; fall back to the opening sentences for short narratives.
  let highlight = "";
  if (d.narrative) {
    const firstPara = d.narrative.split("\n").filter(function(p) { return p.trim(); })[0] || "";
    // Split on sentence terminators followed by whitespace (a sentinel avoids breaking on
    // decimals like "408.1", which a naive [.!?] split would mangle).
    const SENT = String.fromCharCode(1);
    const sentences = firstPara.replace(/([.!?])\s+/g, "$1" + SENT).split(SENT).filter(function(s) { return s.trim(); });
    highlight = (sentences.slice(1, 3).join(" ").trim() || sentences.slice(0, 2).join(" ").trim() || firstPara).trim();
  }
  const daysFull = (d.totals.daysFullCharge != null && d.days) ? (d.totals.daysFullCharge + " / " + d.days + " " + t.days) : "—";

  // Email-safe: table layout only, no data: URIs, no flexbox, no background-color on divs.
  // Logo: text-based fallback since Gmail strips data: URIs.
  return "<!DOCTYPE html><html><body style='font-family: Arial, sans-serif; color: #1A2B3C; max-width: 560px; margin: 0 auto; padding: 0;'>" +

    // Header — brand name as styled text (logo data: URIs stripped by Gmail)
    "<table width='100%' cellpadding='0' cellspacing='0' style='border-bottom: 3px solid #1FAE6E; padding-bottom: 12px; margin-bottom: 20px;'><tr>" +
      "<td style='font-size: 11px; font-weight: 700; color: #1FAE6E; letter-spacing: 0.08em; text-transform: uppercase;'>Pauly &amp; Co.</td>" +
    "</tr></table>" +

    "<p style='font-size: 14px; margin: 0 0 12px 0;'>" + t.emailIntro + " <strong>" + d.site + "</strong> (" + d.startStr + " &#8211; " + d.endStr + ").</p>" +

    // Feel-good takeaway headline
    (surplusLine ? "<p style='font-size: 15px; font-weight: 700; color: #1FAE6E; margin: 0 0 18px 0;'>" + surplusLine + "</p>" : "") +

    // Health score card — table layout, no flex, no background-color on div
    "<table width='100%' cellpadding='0' cellspacing='0' style='margin-bottom: 20px;'><tr>" +
      "<td bgcolor='#EEF9F4' style='padding: 16px 20px; border-radius: 10px;'>" +
        "<table width='100%' cellpadding='0' cellspacing='0'><tr>" +
          "<td style='vertical-align: middle;'>" +
            "<div style='font-size: 9px; color: #5A6B7C; text-transform: uppercase; font-weight: 600; letter-spacing: 0.05em; margin-bottom: 4px;'>" + t.healthScore + "</div>" +
            "<div style='font-size: 30px; font-weight: 700; color: " + scoreColor + "; line-height: 1;'>" + d.avgHealth + "<span style='font-size: 14px; font-weight: 400; color: #999;'>/100</span></div>" +
          "</td>" +
          "<td style='text-align: right; vertical-align: middle;'>" +
            "<span style='display: inline-block; font-size: 12px; font-weight: 600; color: " + badgeText + "; background: " + badgeBg + "; padding: 4px 12px; border-radius: 20px;'>" + statusLabel + "</span>" +
          "</td>" +
        "</tr></table>" +
      "</td>" +
    "</tr></table>" +

    // Plain-language highlight from the weekly summary — the "story" without opening the PDF
    (highlight ? "<table width='100%' cellpadding='0' cellspacing='0' style='margin-bottom: 20px;'><tr>" +
      "<td bgcolor='#F7FBF9' style='padding: 12px 16px; border-radius: 8px; border-left: 3px solid #1FAE6E;'>" +
        "<span style='font-size: 12px; color: #3A4B5C; font-style: italic; line-height: 1.55;'>" + highlight + "</span>" +
      "</td>" +
    "</tr></table>" : "") +

    // Key stats
    "<p style='font-size: 12px; font-weight: 600; color: #14253B; margin: 0 0 8px 0;'>" + t.emailKeyStats + "</p>" +
    "<table width='100%' cellpadding='0' cellspacing='0' style='font-size: 12px; border-collapse: collapse;'>" +
      "<tr><td style='padding: 5px 0; color: #5A6B7C; border-bottom: 1px solid #F0F3F5;'>" + t.pvGenerated + "</td><td style='text-align: right; font-weight: 600; border-bottom: 1px solid #F0F3F5;'>" + d.totals.pv.toFixed(1) + " " + t.kwh + "</td></tr>" +
      "<tr><td style='padding: 5px 0; color: #5A6B7C; border-bottom: 1px solid #F0F3F5;'>" + t.emailLblUsed + "</td><td style='text-align: right; font-weight: 600; border-bottom: 1px solid #F0F3F5;'>" + d.totals.load.toFixed(1) + " " + t.kwh + "</td></tr>" +
      "<tr><td style='padding: 5px 0; color: #5A6B7C; border-bottom: 1px solid #F0F3F5;'>" + t.emailLblOwnEnergy + "</td><td style='text-align: right; font-weight: 600; border-bottom: 1px solid #F0F3F5;'>" + d.gridIndependencePct + "%</td></tr>" +
      "<tr><td style='padding: 5px 0; color: #5A6B7C;'>" + t.emailLblBatteryFull + "</td><td style='text-align: right; font-weight: 600;'>" + daysFull + "</td></tr>" +
    "</table>" +

    // Estimated savings — placeholder until the Supabase-backed tariff calc is wired in
    "<table width='100%' cellpadding='0' cellspacing='0' style='margin-top: 16px;'><tr>" +
      "<td bgcolor='#F7F9F8' style='padding: 12px 16px; border-radius: 8px;'>" +
        "<table width='100%' cellpadding='0' cellspacing='0'><tr>" +
          "<td style='font-size: 12px; font-weight: 600; color: #5A6B7C;'>" + t.tariffSavings + "</td>" +
          "<td style='text-align: right; font-size: 12px; font-weight: 600; color: #B0B8BF;'>" + t.emailSavingsSoon + "</td>" +
        "</tr></table>" +
      "</td>" +
    "</tr></table>" +

    "<p style='font-size: 11px; color: #5A6B7C; margin-top: 20px;'>" + t.emailAttached + "</p>" +

    "<table width='100%' cellpadding='0' cellspacing='0' style='margin-top: 24px; border-top: 1px solid #E0E5EA;'><tr>" +
      "<td style='padding-top: 10px; font-size: 9px; color: #9AA5B0; text-align: center;'>" + t.poweredBy + "</td>" +
    "</tr></table>" +

    "</body></html>";
}

// ─────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────
function getRowsByDateRange(sheet, startDate, endDate) {
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return [];

  const headers = values[0];
  const rows = [];

  for (let i = 1; i < values.length; i++) {
    const obj = {};
    headers.forEach((h, index) => { obj[h] = values[i][index]; });

    const rawDate = obj.date;
    let date = "";

    if (rawDate instanceof Date) {
      date = formatDate(rawDate);
    } else {
      date = String(rawDate || "").slice(0, 10);
    }

    if (date >= startDate && date <= endDate) {
      obj.date = date;
      rows.push(obj);
    }
  }

  return rows;
}

function formatDate(date) {
  return Utilities.formatDate(
    date,
    Session.getScriptTimeZone(),
    "yyyy-MM-dd"
  );
}

function createWeeklyReportTrigger() {
  ScriptApp.newTrigger("weeklyReport")
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(7)
    .create();
}

// ─────────────────────────────────────────────────────────────────
// Save raw payload as JSON file to Drive (called on DailySummary success)
// ─────────────────────────────────────────────────────────────────
function saveDriveBackup(data) {
  try {
    const site = data.site || "unknown";
    const date = data.date || Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
    const isTest = data.event === "TEST_DAILY_SUMMARY";

    // Sanitize site name to a safe folder/file name
    const siteSlug = site.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/, "");

    // Timestamp suffix: HHmm in site local time (from payload date + current time)
    // Using script timezone as proxy — close enough for filename uniqueness
    const timeSuffix = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "HHmm");
    const typeTag    = isTest ? "_test" : "";

    // Incremental filename — unique per dump, never overwrites
    // Format: daily_YYYY-MM-DD_HHmm_<siteSlug>[_test].json
    const fileName = "daily_" + date + "_" + timeSuffix + "_" + siteSlug + typeTag + ".json";

    const content = JSON.stringify({
      site:              site,
      date:              date,
      timestamp_written: new Date().toISOString(),
      type:              isTest ? "TEST" : "CONFIRMED",
      source:            "google-apps-script",
      payload:           data
    }, null, 2);

    const blob = Utilities.newBlob(content, "application/json", fileName);

    let folder;
    if (CONFIG.reportFolderId) {
      const rootFolder = DriveApp.getFolderById(CONFIG.reportFolderId);

      // Create or reuse "daily-backups/<siteSlug>" subfolder
      const backupFolderName = "daily-backups";
      let backupRoot;
      const existingRoots = rootFolder.getFoldersByName(backupFolderName);
      backupRoot = existingRoots.hasNext()
        ? existingRoots.next()
        : rootFolder.createFolder(backupFolderName);

      let siteFolder;
      const existingSite = backupRoot.getFoldersByName(siteSlug);
      siteFolder = existingSite.hasNext()
        ? existingSite.next()
        : backupRoot.createFolder(siteSlug);

      folder = siteFolder;
    } else {
      folder = DriveApp.getRootFolder();
    }

    // No overwrite logic — every dump creates a new incremental file
    folder.createFile(blob);

    Logger.log("Drive backup saved: " + fileName);

  } catch (err) {
    // Non-fatal — log and continue
    Logger.log("Drive backup failed: " + err.toString());
  }
}