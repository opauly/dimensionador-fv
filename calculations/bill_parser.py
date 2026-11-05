"""Parse ICE / CNFL electricity bill PDFs using Claude API.

Sends the PDF as a base64 document to Claude and extracts structured
consumption history. Works with both ICE and CNFL formats regardless
of layout differences across years.
"""
from __future__ import annotations
import base64
import json
import os

# Extraction needs real judgment about what each column means, so it gets a
# stronger model than the cheap seasonal-estimate call below. Override with
# BILL_PARSER_MODEL if needed.
_MODEL = "claude-haiku-4-5-20251001"
_EXTRACT_MODEL = os.environ.get("BILL_PARSER_MODEL", "claude-sonnet-5-5")

MONTH_NAMES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

_EXTRACT_PROMPT = """
You are extracting structured data from a Costa Rican electricity bill. The document may be a PDF
or a photo/screenshot, from any distributor (ICE, CNFL, JASEC, ESPH, a cooperative...), in any
layout, old or new. Read it the way an experienced energy auditor would: work out what each
column really means before copying numbers.

Return ONLY a JSON object with this exact shape:
{
  "distributor": "<CNFL|ICE|JASEC|ESPH|COOPELESCA|COOPEGUANACASTE|COOPESANTOS|COOPEALFARORUIZ|other name>",
  "nise": "<customer account / contract number>",
  "net_metering": <true if the customer has solar self-generation (autogeneración / medición neta /
                   "energía depositada" / "producida" columns), else false>,
  "history": [
    {"month": <1-12>, "year": <4-digit year>,
     "grid_kwh": <kWh drawn from the utility grid that month>,
     "produced_kwh": <kWh produced by the customer's PV, or null if not shown>,
     "exported_kwh": <kWh injected/deposited into the grid, or null if not shown>,
     "bill_crc": <integer or null>}
  ],
  "notes": ["<max 3 short items, ONLY things that affect the kWh numbers: unreadable/uncertain values,
             estimated (not real) readings, multiple meters, bi-monthly periods, a period that looks
             like an outlier. No remarks about charges, taxes, fees or layout.>"]
}

Rules:
- Include EVERY month you can read: the consumption-history table ("HISTORIAL / HISTORICO DE
  CONSUMO" or similar) AND the current billing period itself (its readings: previous vs current,
  usually labelled "Consumo" / "Retirado de la red"). Label the current period by its billing
  period ("PERIODO AL COBRO", e.g. 9-2026 → month 9, year 2026) and use the same convention as the
  history table. If the period is bi-monthly, split nothing; list it under its label and mention it in notes.
- month is 1-12 (1=Enero, 12=Diciembre).
- grid_kwh is the energy the customer took FROM the grid ("consumo", "retirada", "retirado de la red").
  Do NOT subtract anything and do NOT add production: report the raw columns exactly as printed;
  the code computes total consumption afterwards.
- For self-generation bills set produced_kwh ("producida/producido", "generación") and exported_kwh
  ("depositada/depositado/entregada", "energía inyectada"). If a bill has no such columns, set both
  null and net_metering false.
- Include 0 kWh months — they indicate new service, not missing data.
- bill_crc: the TOTAL POR PAGAR (integer colones, no decimals), ONLY for the current billing period;
  null for every other month.
- If multiple meters are present, extract data for the first/primary meter only and say so in notes.
- If a table is cropped, blurry or you are unsure of a value, still give your best reading and say
  which month/value is uncertain in notes. Never invent months that are not on the document.
- Return ONLY the JSON object, no markdown, no explanation.
"""

_ESTIMATE_PROMPT = """\
You are estimating missing monthly electricity consumption (kWh) for a Costa Rican electricity account.

Known monthly consumption (month number → kWh):
{known_text}

Location: {location}
Missing months to estimate (month numbers): {missing_text}

Costa Rica seasonal context:
- Dry season Dec–Apr: typically warmer, higher AC use → higher consumption
- Rainy season May–Oct: cooler, often lower consumption
- Transition Nov: variable

Instructions:
- Estimate kWh for each missing month using the seasonal trend visible in the known data.
- If the known data spans only part of a year, extrapolate based on Costa Rica's typical season ratio.
- Round each estimate to the nearest 10 kWh.
- Return ONLY a JSON object mapping month number (string) → estimated kWh (integer).
  Example: {{"5": 840, "6": 810, "7": 790, "8": 800, "9": 820, "10": 850}}
"""


def _document_block(data: bytes) -> dict:
    """Claude content block for a PDF or an image, sniffed from magic bytes
    (customers send PDFs, WhatsApp photos, screenshots...)."""
    b64 = base64.standard_b64encode(data).decode("utf-8")
    if data[:4] == b"%PDF":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        media = "image/png"
    elif data[:3] == b"\xff\xd8\xff":
        media = "image/jpeg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        media = "image/webp"
    else:
        raise ValueError("Formato de archivo no soportado (usa PDF, JPG, PNG o WEBP).")
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}}


def _num(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _normalize_row(row: dict, notes: list[str]) -> dict | None:
    """Turn the raw per-column reading into one row with TOTAL consumption.

    Arithmetic is done here, not by the model:
      total = grid + produced - exported   (self-generation / net-metering bills)
      total = grid                          (plain bills)
    """
    try:
        month, year = int(row["month"]), int(row["year"])
    except (KeyError, TypeError, ValueError):
        return None
    if not 1 <= month <= 12:
        return None

    grid = _num(row.get("grid_kwh"))
    if grid is None:  # tolerate a model answering with the old "kwh" shape
        grid = _num(row.get("kwh"))
    if grid is None:
        return None
    produced = _num(row.get("produced_kwh"))
    exported = _num(row.get("exported_kwh"))

    out = {"month": month, "year": year}
    if produced is not None:
        exported = exported or 0.0
        if exported > produced:
            notes.append(f"{month}/{year}: la energía depositada ({exported:.0f}) supera la producida ({produced:.0f}); revisar.")
            exported = produced
        out.update(kwh=round(grid + produced - exported), grid_kwh=round(grid),
                   produced_kwh=round(produced), exported_kwh=round(exported),
                   # The printed bill is the NET-METERED bill, not what the customer
                   # would pay without solar -> let the tariff price the real consumption.
                   bill_crc=None)
    else:
        out.update(kwh=round(grid), bill_crc=row.get("bill_crc"))
    return out


def merge_history(rows: list[dict]) -> list[dict]:
    """One row per (year, month) across several bills; later input wins but
    never loses a bill_crc or PV columns it already had."""
    merged: dict[tuple[int, int], dict] = {}
    for r in rows:
        k = (r["year"], r["month"])
        prev = merged.get(k, {})
        merged[k] = {**prev, **{kk: vv for kk, vv in r.items() if vv is not None}}
    return [merged[k] for k in sorted(merged)]


def parse_bill_pdf(file_bytes: bytes) -> dict:
    """
    Extract consumption history from an electricity bill (PDF or image).

    Returns:
        {
            "distributor": str,
            "nise": str,
            "net_metering": bool,
            "notes": [str],
            "history": [{"month": int, "year": int, "kwh": int,   # TOTAL consumption
                         "bill_crc": int|None,
                         # only on self-generation bills:
                         "grid_kwh": int, "produced_kwh": int, "exported_kwh": int}]
        }
    """
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    response = client.messages.create(
        model=_EXTRACT_MODEL,
        max_tokens=16000,  # thinking tokens count against this
        messages=[
            {
                "role": "user",
                "content": [_document_block(file_bytes), {"type": "text", "text": _EXTRACT_PROMPT}],
            }
        ],
    )

    # Newer models may emit a thinking block first; take the first text block.
    text = next(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text

    data = json.loads(text)

    notes = [str(n) for n in (data.get("notes") or [])]
    history = [r for r in (_normalize_row(h, notes) for h in data.get("history") or []) if r]
    if not history:
        raise ValueError("No se encontró historial de consumo en la factura.")

    net = bool(data.get("net_metering")) or any("produced_kwh" in h for h in history)
    if net:
        notes.insert(0, "Factura con autogeneración: el consumo mostrado es retirado + producido − depositado.")
    return {
        "distributor": data.get("distributor", ""),
        "nise": data.get("nise", ""),
        "net_metering": net,
        "notes": notes,
        "history": merge_history(history),
    }


def _estimate_missing_kwh(
    known: dict[int, float],
    missing_months: list[int],
    location: str = "Costa Rica",
) -> dict[int, float]:
    """
    Ask Claude to estimate kWh for months not in the known history.

    Returns {month_number: estimated_kwh} for the missing months only.
    Falls back to simple averaging on any error.
    """
    import anthropic

    avg = round(sum(known.values()) / len(known)) if known else 0

    if not missing_months:
        return {}

    known_text = "\n".join(
        f"  Month {m} ({MONTH_NAMES_ES[m - 1]}): {int(kwh)} kWh"
        for m, kwh in sorted(known.items())
    )
    missing_text = ", ".join(
        f"{m} ({MONTH_NAMES_ES[m - 1]})" for m in sorted(missing_months)
    )

    prompt = _ESTIMATE_PROMPT.format(
        known_text=known_text,
        location=location,
        missing_text=missing_text,
    )

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model=_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
        raw = json.loads(text)
        return {int(k): float(v) for k, v in raw.items() if int(k) in missing_months}
    except Exception:
        return {m: float(avg) for m in missing_months}


def build_12_month_grid(
    history: list[dict],
    reference_year: int | None = None,
    location: str = "Costa Rica",
    tariff_info: dict | None = None,
) -> list[dict]:
    """
    Build a full 12-month Jan–Dec consumption grid from bill history.

    Known months (kwh > 0) are placed directly. Missing months are estimated
    by Claude using Costa Rica's seasonal patterns. If tariff_info is provided,
    Factura (₡) is computed for all months via the tariff tiers.

    Returns:
        List of 12 dicts: [{"month": "Enero", "kwh": float, "bill_crc": float}, ...]
    """
    if not history:
        return [{"month": m, "kwh": 0.0, "bill_crc": 0.0} for m in MONTH_NAMES_ES]

    if reference_year is None:
        reference_year = max(h["year"] for h in history)

    # Index known non-zero months. For months that appear in both years, prefer the newer one.
    known: dict[int, dict] = {}
    for h in history:
        if float(h.get("kwh") or 0) > 0 and (h["year"] == reference_year or h["year"] == reference_year - 1):
            m = h["month"]
            if m not in known or h["year"] > known[m].get("_year", 0):
                known[m] = {
                    "kwh": float(h["kwh"]),
                    "bill_crc": float(h.get("bill_crc") or 0),
                    "_year": h["year"],
                }

    missing = [m for m in range(1, 13) if m not in known]

    # AI estimation for missing months
    if missing and known:
        estimated_kwh = _estimate_missing_kwh(
            {m: v["kwh"] for m, v in known.items()},
            missing,
            location=location,
        )
    else:
        # All 12 months known, or no known months at all
        avg = round(sum(v["kwh"] for v in known.values()) / len(known), 1) if known else 0.0
        estimated_kwh = {m: avg for m in missing}

    # Compute Factura for missing months (or all months if tariff provided)
    if tariff_info:
        from calculations.tariff_calculator import estimate_bill_crc
        for m, v in known.items():
            if v["bill_crc"] == 0:
                v["bill_crc"] = estimate_bill_crc(v["kwh"], tariff_info)

    grid = []
    for i, name in enumerate(MONTH_NAMES_ES):
        m = i + 1
        if m in known:
            kwh = known[m]["kwh"]
            bill = known[m]["bill_crc"]
        else:
            kwh = estimated_kwh.get(m, 0.0)
            bill = estimate_bill_crc(kwh, tariff_info) if tariff_info and kwh > 0 else 0.0
        grid.append({"month": name, "kwh": round(kwh, 1), "bill_crc": round(bill)})

    return grid
