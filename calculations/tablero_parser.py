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

_PROMPT_TEXT_OFF_GRID = """
Extract electrical circuits/loads from this pasted text — likely copied from a
spreadsheet, Word table, or an existing panel-schedule design (Costa Rica).
The format is unpredictable: it may be tab-separated, space-aligned,
comma-separated, or a loose list of lines like "2x Aire acondicionado 1500W".

For each real circuit/load return ONLY:
- Descripción: short human-readable load name (Spanish, capitalize)
- Cantidad: quantity (1 unless the text explicitly groups identical loads)
- Potencia (kW): nameplate/design power in kW — convert from W if needed (divide by 1000)

Do NOT extract or use any "factor de demanda" / "demand factor" / "carga
simultánea estimada" / percentage columns even if present in the pasted
text — this tool computes its own demand factors separately, downstream.
Only the raw installed/nameplate ("potencia de diseño") power per circuit
matters here.

Rules:
- Skip header rows, TOTAL/subtotal rows, and circuit-number-only columns
- Skip rows with 0 W or blank descriptions
- Keep descriptions concise (e.g. "Tomacorrientes de cocina" not the full row text)
- If the same load type repeats across circuits with identical power, you may
  merge them into one row with Cantidad > 1, but only if merging doesn't lose
  meaningfully different circuits (when in doubt, keep separate rows)

Pasted text:
---
{text}
---

Return ONLY a JSON array with no markdown fences:
[
  {{"Descripción": "Tomacorriente para microondas", "Cantidad": 1, "Potencia (kW)": 0.8}},
  {{"Descripción": "Iluminación principal", "Cantidad": 1, "Potencia (kW)": 1.15}}
]
"""


def parse_tablero_text_off_grid(text: str) -> list[dict]:
    """
    Extract installed electrical loads from pasted plain text, for the
    Off-Grid/Hybrid wizard — name/quantity/nameplate power only, no hours,
    no imported demand factor (see module note above).

    Args:
        text: Raw pasted text — any delimiter/layout.

    Returns:
        List of load dicts: [{"Descripción", "Cantidad", "Potencia (kW)"}, ...]

    Raises:
        ValueError: If the text is empty or no loads are extracted.
        anthropic.APIError: On API errors.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Pega el texto de la tabla de cargas antes de extraer.")

    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": _PROMPT_TEXT_OFF_GRID.format(text=text)}],
    )

    out = response.content[0].text.strip()
    if out.startswith("```"):
        parts = out.split("```")
        out = parts[1].lstrip("json").strip() if len(parts) > 1 else out

    loads = json.loads(out)

    if not isinstance(loads, list) or not loads:
        raise ValueError("No se extrajeron cargas del texto pegado.")

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
        raise ValueError("No se encontraron cargas activas en el texto pegado.")

    return result
