"""Parse electrical panel schedule (tablero) images or PDFs using Claude vision/document API.

Extracts circuit descriptions and VA/W values, then estimates typical hours/day
and days/month per load type based on Costa Rican usage patterns.
"""
from __future__ import annotations
import base64
import json
import os

_MODEL = "claude-haiku-4-5-20251001"

_PROMPT = """
Analyze this electrical panel schedule (tablero eléctrico) from Costa Rica.

Extract all active electrical circuits. For each circuit return:
- Descripción: short human-readable load name (Spanish, capitalize)
- W: power in Watts (use VA value directly — assume VA ≈ W for resistive loads; for motors multiply VA × 0.85)
- Und: quantity (1 per circuit unless identical loads share a circuit breaker)
- h/día: estimated daily usage hours in Costa Rica
- días/mes: estimated usage days per month

Usage estimates by load type (use these as defaults):
  Refrigerador / heladera          → 24 h/día, 30 días
  Iluminación / luminaria / luz    → 6 h/día, 30 días
  Microondas                       → 0.5 h/día, 30 días
  Aire acondicionado / A/C / minisplit → 8 h/día, 20 días
  Lavadora                         → 1 h/día, 8 días
  Secadora                         → 1 h/día, 8 días
  Calentador de agua / ducha       → 2 h/día, 30 días
  Horno de cocina / estufa         → 1 h/día, 20 días
  Extractor de grasa / ventilador  → 1.5 h/día, 25 días
  Tomacorriente cocina             → 2 h/día, 30 días
  Tomacorriente sala/cuartos       → 3 h/día, 30 días
  Tomacorrientes generales         → 3 h/día, 30 días
  Calentador de agua (eléctrico)   → 2 h/día, 30 días
  Bomba de agua / piscina          → 4 h/día, 30 días
  Portón eléctrico                 → 0.1 h/día, 30 días
  TV / entretenimiento             → 5 h/día, 30 días
  Computadora / oficina            → 8 h/día, 22 días
  Triturador de alimentos          → 0.1 h/día, 30 días
  Jacuzzi / spa                    → 1 h/día, 12 días
  Supresor de picos / UPS          → 0 h/día (skip)

Rules:
- Skip "Prevista" (provisional/future) circuits — they are not installed yet
- Skip breakers with 0 VA or blank descriptions
- For 240V dual-phase breakers that appear as paired rows (same CKT), use the total VA shown
  (the table may already show the combined value in the VA column)
- Merge identical load types in the same area into a single row with Und > 1 if it makes sense
- Keep the description concise and descriptive (e.g. "Tomacorrientes Cuartos" not the full CKT text)

Return ONLY a JSON array with no markdown fences:
[
  {"Descripción": "Refrigerador", "W": 500, "Und": 1, "h/día": 24, "días/mes": 30},
  {"Descripción": "Iluminación general", "W": 300, "Und": 1, "h/día": 6, "días/mes": 30}
]
"""


def parse_tablero(file_bytes: bytes, media_type: str) -> list[dict]:
    """
    Extract installed electrical loads from a tablero image or PDF.

    Args:
        file_bytes: Raw bytes of the image (JPEG/PNG) or PDF.
        media_type: MIME type — "image/jpeg", "image/png", or "application/pdf".

    Returns:
        List of load dicts: [{"Descripción", "W", "Und", "h/día", "días/mes"}, ...]

    Raises:
        ValueError: If no loads are extracted.
        anthropic.APIError: On API errors.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    b64 = base64.standard_b64encode(file_bytes).decode("utf-8")

    if media_type == "application/pdf":
        file_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
        }
    else:
        file_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }

    response = client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    file_block,
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text

    loads = json.loads(text)

    if not isinstance(loads, list) or not loads:
        raise ValueError("No se extrajeron cargas del tablero.")

    # Sanitize and ensure correct types
    result = []
    for row in loads:
        w = float(row.get("W") or 0)
        if w <= 0:
            continue
        result.append({
            "Descripción": str(row.get("Descripción", "Carga")),
            "W":           round(w),
            "Und":         int(row.get("Und") or 1),
            "h/día":       float(row.get("h/día") or 0),
            "días/mes":    int(row.get("días/mes") or 0),
        })

    if not result:
        raise ValueError("No se encontraron cargas activas en el tablero.")

    return result


# ── Off-Grid variant (Phase 5) ───────────────────────────────────────────────
#
# Deliberately does NOT ask the AI for h/día or días/mes — that's exactly the
# naive "nameplate × assumed hours" pattern the load-profile taxonomy
# (tools/off-grid-wizard-load-profile-approach.md) was built to replace.
# This only extracts what a tablero photo can actually tell you (name, count,
# nameplate power); calculations/load_profile_off_grid.py's classify-then-
# estimate pipeline handles the energy math deterministically afterward.

_PROMPT_OFF_GRID = """
Analyze this electrical panel schedule (tablero eléctrico) from Costa Rica.

Extract all active electrical circuits. For each circuit return ONLY:
- Descripción: short human-readable load name (Spanish, capitalize)
- Cantidad: quantity (1 per circuit unless identical loads share a breaker)
- Potencia (kW): nameplate power in kW (use VA value directly, divide by 1000 —
  assume VA ≈ W for resistive loads; for motors multiply VA × 0.85 before dividing)

Do NOT estimate usage hours, duty cycle, or days per month — that is
deliberately out of scope for this extraction.

Rules:
- Skip "Prevista" (provisional/future) circuits — they are not installed yet
- Skip breakers with 0 VA or blank descriptions
- For 240V dual-phase breakers that appear as paired rows (same CKT), use the
  total VA shown (the table may already show the combined value in the VA column)
- Merge identical load types in the same area into a single row with Cantidad > 1
  if it makes sense
- Keep the description concise and descriptive (e.g. "Tomacorrientes Cuartos"
  not the full CKT text)

Return ONLY a JSON array with no markdown fences:
[
  {"Descripción": "Refrigerador", "Cantidad": 1, "Potencia (kW)": 0.5},
  {"Descripción": "Iluminación general", "Cantidad": 1, "Potencia (kW)": 0.3}
]
"""


def parse_tablero_off_grid(file_bytes: bytes, media_type: str) -> list[dict]:
    """
    Extract installed electrical loads from a tablero image or PDF, for the
    Off-Grid/Hybrid wizard — name/quantity/nameplate power only, no hours.

    Args:
        file_bytes: Raw bytes of the image (JPEG/PNG) or PDF.
        media_type: MIME type — "image/jpeg", "image/png", or "application/pdf".

    Returns:
        List of load dicts: [{"Descripción", "Cantidad", "Potencia (kW)"}, ...]

    Raises:
        ValueError: If no loads are extracted.
        anthropic.APIError: On API errors.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    b64 = base64.standard_b64encode(file_bytes).decode("utf-8")

    if media_type == "application/pdf":
        file_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
        }
    else:
        file_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        }

    response = client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    file_block,
                    {"type": "text", "text": _PROMPT_OFF_GRID},
                ],
            }
        ],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text

    loads = json.loads(text)

    if not isinstance(loads, list) or not loads:
        raise ValueError("No se extrajeron cargas del tablero.")

    result = []
    for row in loads:
        kw = float(row.get("Potencia (kW)") or 0)
        if kw <= 0:
            continue
        result.append({
            "Descripción":   str(row.get("Descripción", "Carga")),
            "Cantidad":      int(row.get("Cantidad") or 1),
            "Potencia (kW)": round(kw, 2),
        })

    if not result:
        raise ValueError("No se encontraron cargas activas en el tablero.")

    return result


# ── Off-Grid text-paste variant ──────────────────────────────────────────────
# Same output shape and "no hours, no demand factor" scope as
# parse_tablero_off_grid() above, but for text pasted directly into the
# wizard (e.g. copied from a circuit-schedule spreadsheet or an existing
# electrical design) instead of an uploaded image/PDF. AI rather than plain
# text-splitting because pasted-table formatting is unpredictable — tab-
# separated from Excel, space-aligned from a PDF-to-text conversion, commas,
# or a loose list of lines — the same reasoning that justifies vision
# extraction for photographed tableros applies here to inconsistent text
# layout. Deliberately drops any "factor de demanda"/"carga simultánea"
# column present in the source: this tool computes its own demand factors
# downstream (calculations/load_profile_off_grid.py compute_demand_load()),
# per taxonomy category — importing someone else's ad-hoc per-circuit factor
# alongside that would silently mix two different demand models.

_SMART_TEXT_MODEL = os.environ.get("LOADS_PARSER_MODEL", "claude-sonnet-5-5")

_PROMPT_TEXT_OFF_GRID = """
You are helping a Costa Rican solar installer (Pauly & Co) turn whatever a customer sent into
an electrical LOAD LIST for sizing a battery system. The pasted text can be ANYTHING:
a spreadsheet/Word table, a panel schedule, a loose list ("2x Aire 1500W"), or a whole WhatsApp /
email conversation with timestamps, greetings, the installer's own replies and the customer's
changing requirements. Work like an experienced energy auditor, not like a table splitter.

Return ONLY a JSON object (no markdown fences):
{{
  "loads": [
    {{"Descripción": "<short Spanish name>", "Cantidad": <int>, "Potencia (kW)": <number>,
      "estimated": <true if YOU supplied the power, false if the text states it or it is a catalog value
                    printed in the text>,
      "usage": "<usage the customer stated, short, e.g. 'hasta 2 h día + 2 h noche', '2 ciclos/semana de 1 h'; '' if none>",
      "duty_hours_day": <number or null — see 'Hours' below>}}
  ],
  "notes": ["<short Spanish bullets, max ~10, see below>"]
}}

How to read the text:
- CONVERSATIONS: the CUSTOMER's latest statements win over earlier ones. Lines from the installer
  are context/agreements (e.g. "hot water will be a separate system", "we recommend gas cooking"),
  not customer loads. Ignore greetings, timestamps, names, questions about warranties/prices.
- EXPLICIT EXCLUSIONS ("no tendría aire acondicionado, microondas…") → do NOT list those loads.
- LOADS COVERED BY ANOTHER SYSTEM: if the conversation agrees a load goes on a separate system
  (e.g. solar water heating / gas), do NOT put it in the list; say so in notes.
- Equipment the customer will keep outside the system (e.g. "my EcoFlow stays separate") is NOT a load.
- Named products with a model number (e.g. an oven "BOV900BSS 1,800 W"): use the stated power; if power
  is not stated use the known nameplate of that model.
- Loads with NO power given: estimate a realistic NAMEPLATE power for a Costa Rica residence
  (120/240 V) and set "estimated": true. Examples of typical values — induction cooktop 4 zones
  ≈ 7.2 kW, electric dryer ≈ 5.0 kW, washing machine ≈ 0.5 kW, large fridge/freezer ≈ 0.2 kW,
  LED light ≈ 0.01 kW, laptop ≈ 0.07 kW, Starlink ≈ 0.075 kW, electric piano ≈ 0.05 kW,
  blender ≈ 0.6 kW, immersion mixer ≈ 0.3 kW, handheld vacuum charger ≈ 0.1 kW,
  garden-tool charger ≈ 0.3 kW, spring/well water pump ≈ 0.75 kW (hp-class; say "bomba de agua"),
  electric water heater ≈ 3.5 kW (only if it must be included). Be conservative (round UP).
  DOUBLE-CHECK UNITS: "Potencia (kW)" is kilowatts, so 75 W is 0.075 (a common slip is 0.0075 or 7.5).
  For motors/pumps/compressors mention the start-up (surge) current in notes (≈ 3-6 × running power).
- GROUPS: "25 luces LED" → one row, Cantidad 25, 0.01 kW each. Two devices used together stay separate rows.
- If the customer states hours/frequency, put it in "usage" and compute "duty_hours_day" — never invent usage.
- Hours ("duty_hours_day"): AVERAGE DAILY hours at FULL nameplate power, i.e. kWh/day = kW × Cantidad × duty_hours_day.
  Convert what was said: day + night hours are added; weekly use is divided by 7 (2 cycles/week × 1 h → 0.29);
  for loads that do NOT draw full nameplate power the whole time they are "on", convert to equivalent
  full-power hours with a realistic, slightly conservative duty factor (induction cooktop ≈ 0.5, oven/air-fryer
  ≈ 0.6, electric dryer ≈ 0.8, washing machine ≈ 0.5, laptop ≈ 0.6). Laptops/phones/chargers: same idea.
  Mention the factor in "usage" so the engineer can audit it (e.g. 'hasta 4 h/día × factor 0.5').
  Use null (NOT 24 h) for compressor/thermostat/motor-cycling loads without explicit hours (refrigerator,
  freezer, pump) — the sizing has its own estimators for those — and null when the customer gave no usage.
  A 24-hour constant electronic load (Starlink, router) → 24.
- Pure tables: keep the old rules — skip headers/totals/zero-power rows, ignore any "factor de
  demanda"/simultaneity columns (this tool computes its own downstream), merge identical rows only
  when nothing meaningful is lost.

"notes" must be useful to the engineer, in Spanish, short:
  • which loads you EXCLUDED and why (customer said no / separate system),
  • which powers you ESTIMATED (so they can be confirmed),
  • key requirements that are not loads but matter for sizing (days of autonomy requested, e.g.
    "autonomía 2, 3 y 4 días sin generación solar"; grid availability; must-run loads on cloudy days;
    location; system type: off-grid / hybrid; separate systems requested),
  • conflicts or missing data (e.g. "bomba de agua: potencia por definir").
Do not add notes about prices, warranties or pleasantries. Do NOT repeat in notes the list of estimated
powers or each load's stated usage — the code adds those itself; keep notes to exclusions, requirements,
surge/peak-power remarks, conflicts and missing data.

Pasted text:
---
{text}
---
"""


def _first_text(response) -> str:
    """First text block (newer models may emit a thinking block first)."""
    return next(b.text for b in response.content if getattr(b, "type", "") == "text").strip()


def _json_from(out: str):
    if out.startswith("```"):
        parts = out.split("```")
        out = parts[1].lstrip("json").strip() if len(parts) > 1 else out
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        a, b = out.find("{"), out.rfind("}")  # tolerate stray prose around the JSON
        if a >= 0 and b > a:
            return json.loads(out[a:b + 1])
        raise


# Typical per-unit nameplate (kW) of common household loads: (min, max, typical).
# Guard against unit slips (W vs kW) in AI-ESTIMATED powers only — a stated power is never touched.
_PLAUSIBLE_KW = [
    ("starlink", 0.02, 0.15, 0.075), ("refriger", 0.08, 0.6, 0.2), ("nevera", 0.08, 0.6, 0.2),
    ("congelador", 0.08, 0.6, 0.2), ("laptop", 0.03, 0.15, 0.07), ("macbook", 0.03, 0.15, 0.07),
    ("led", 0.002, 0.03, 0.01), ("luz", 0.002, 0.03, 0.01), ("luces", 0.002, 0.03, 0.01),
    ("lavadora", 0.2, 2.5, 0.5), ("secadora", 2.0, 6.5, 5.0), ("inducc", 1.5, 11.0, 7.2),
    ("horno", 0.8, 3.5, 1.8), ("licuadora", 0.2, 1.5, 0.6), ("bomba", 0.25, 3.0, 0.75),
    ("piano", 0.02, 0.3, 0.05),
]


def _plausible_power(name: str, kw: float, estimated: bool, notes: list[str]) -> float:
    if not estimated:
        return kw
    low = name.lower()
    for key, lo, hi, typical in _PLAUSIBLE_KW:
        if key in low:
            if not lo <= kw <= hi:
                notes.append(f"{name}: la potencia estimada ({kw:g} kW) era poco plausible; se corrigió a {typical:g} kW (confirmar).")
                return typical
            break
    return kw


def _hours(v):
    try:
        h = float(v)
    except (TypeError, ValueError):
        return None
    return round(h, 2) if 0 < h <= 24 else None


def parse_loads_text(text: str) -> dict:
    """Smart extraction of loads from ANY pasted text (table, loose list or a
    whole customer chat) for the Off-Grid/Hybrid wizard.

    Returns {"loads": [{"Descripción", "Cantidad", "Potencia (kW)", "estimated", "usage", "Horas/día"}],
             "notes": [str]}. `notes` carries exclusions, estimated powers and
    sizing-relevant requirements (autonomy days, separate systems...).
    Raises ValueError when the text is empty or no loads are found."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Pega el texto de la tabla de cargas antes de extraer.")

    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=_SMART_TEXT_MODEL,
        max_tokens=16000,  # thinking tokens count against this
        messages=[{"role": "user", "content": _PROMPT_TEXT_OFF_GRID.format(text=text)}],
    )
    data = _json_from(_first_text(response))
    if isinstance(data, list):  # tolerate the legacy bare-array answer
        data = {"loads": data, "notes": []}

    result = []
    guard_notes: list[str] = []
    for row in data.get("loads") or []:
        try:
            kw = float(row.get("Potencia (kW)") or 0)
        except (TypeError, ValueError):
            continue
        if kw <= 0:
            continue
        desc = str(row.get("Descripción", "Carga"))
        kw = _plausible_power(desc, kw, bool(row.get("estimated")), guard_notes)
        result.append({
            "Descripción":   desc,
            "Cantidad":      int(row.get("Cantidad") or 1),
            "Potencia (kW)": round(kw, 3 if kw < 0.1 else 2),
            "estimated":     bool(row.get("estimated")),
            "usage":         str(row.get("usage") or ""),
            "Horas/día":     _hours(row.get("duty_hours_day")),
        })
    if not result:
        raise ValueError("No se encontraron cargas activas en el texto pegado.")

    notes = [str(n) for n in (data.get("notes") or [])] + guard_notes
    for r in result:
        if r["usage"]:
            notes.append(f"{r['Descripción']}: {r['usage']}")
    estimated = [r["Descripción"] for r in result if r["estimated"]]
    if estimated:
        notes.insert(0, "Potencia ESTIMADA por la IA (confirmar): " + ", ".join(estimated) + ".")
    return {"loads": result, "notes": notes}


def parse_tablero_text_off_grid(text: str) -> list[dict]:
    """Back-compat wrapper: rows only (Descripción / Cantidad / Potencia (kW))."""
    return [
        {k: r[k] for k in ("Descripción", "Cantidad", "Potencia (kW)")}
        for r in parse_loads_text(text)["loads"]
    ]
