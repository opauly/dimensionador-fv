"""Parse ICE / CNFL electricity bill PDFs using Claude API.

Sends the PDF as a base64 document to Claude and extracts structured
consumption history. Works with both ICE and CNFL formats regardless
of layout differences across years.
"""
from __future__ import annotations
import base64
import json
import os

_MODEL = "claude-haiku-4-5-20251001"

MONTH_NAMES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

_EXTRACT_PROMPT = """
You are extracting structured data from a Costa Rican electricity bill (ICE or CNFL).

Return ONLY a JSON object with this exact shape:
{
  "distributor": "<CNFL|ICE|JASEC|ESPH|COOPELESCA|COOPEGUANACASTE|COOPESANTOS|COOPEALFARORUIZ>",
  "nise": "<customer account number>",
  "history": [
    {"month": <1-12>, "year": <4-digit year>, "kwh": <integer>, "bill_crc": <integer or null>}
  ]
}

Rules:
- Include ALL months shown in the consumption history table ("HISTORIAL DE CONSUMO" or similar).
- month is 1-12 (1=Enero, 12=Diciembre).
- Include 0 kWh months — they indicate new service, not missing data.
- bill_crc: set to the TOTAL POR PAGAR amount (as an integer, no decimals) only for the
  most recent month. Set null for all other months.
- nise is the account number labeled "NISE" or "NIS" on the bill.
- If multiple meters are present, extract data for the first/primary meter only.
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


def parse_bill_pdf(pdf_bytes: bytes) -> dict:
    """
    Extract consumption history from a PDF electricity bill.

    Returns:
        {
            "distributor": str,
            "nise": str,
            "history": [{"month": int, "year": int, "kwh": int, "bill_crc": int|None}]
        }
    """
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": _EXTRACT_PROMPT},
                ],
            }
        ],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text

    data = json.loads(text)

    if "history" not in data or not data["history"]:
        raise ValueError("No se encontró historial de consumo en la factura.")

    return data


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
