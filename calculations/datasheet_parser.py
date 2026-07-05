"""Parse solar equipment datasheets (PDF) using Claude AI to extract technical specs.

Handles multi-model datasheets (e.g. Fronius Primo 3.8–15kW) by returning all
variants found. Caller selects which one to save.
"""
from __future__ import annotations
import base64
import json
import os

_MODEL = "claude-haiku-4-5-20251001"

_PANEL_PROMPT = """
Extract technical specifications from this solar panel datasheet.

If the datasheet covers multiple power classes (e.g. a series from 400W to 505W),
return ALL variants as separate objects.

Return ONLY a JSON array — no markdown, no explanation:
[
  {
    "brand": "JA Solar",
    "model": "JAM66D45-490LB",
    "wp": 490,
    "voc": 51.20,
    "vmp": 43.10,
    "isc": 12.80,
    "imp": 12.14,
    "temp_coeff_pmax": -0.35,
    "width_m": 1.134,
    "height_m": 2.278,
    "warranty_product_yr": 12,
    "warranty_power_yr": 30
  }
]

Field rules:
- wp: rated power at STC in Watts (integer)
- voc, vmp: open-circuit and max-power-point voltages in V (2 decimal places)
- isc, imp: short-circuit and max-power-point currents in A (2 decimal places)
- temp_coeff_pmax: temperature coefficient of Pmax in %/°C (negative, e.g. -0.35)
- width_m, height_m: physical dimensions in METERS (convert mm → m: 1134 mm = 1.134 m)
  Use the shorter dimension as width and the longer as height.
- warranty_product_yr: product/workmanship warranty in years
- warranty_power_yr: linear power output performance warranty in years
- Use null for any field you cannot find with confidence
"""

_INVERTER_PROMPT = """
Extract technical specifications from this grid-tie solar inverter datasheet.

If the datasheet covers multiple power variants (e.g. 3.8 kW, 5 kW, 7.6 kW, 10 kW, 15 kW),
return ALL variants as separate objects.

Return ONLY a JSON array — no markdown, no explanation:
[
  {
    "brand": "Fronius",
    "model": "Primo 10.0-1",
    "kw": 10.0,
    "type": "string_inverter",
    "vmax": 1000,
    "vmin_mppt": 200,
    "vmax_mppt": 800,
    "imax_mppt": 27.0,
    "mppt_channels": 2,
    "phase": "single",
    "output_v": 240,
    "warranty_yr": 5
  }
]

Field rules:
- kw: rated nominal AC output power in kW (float)
- type: exactly one of "string_inverter", "microinverter", "hybrid"
- vmax: maximum DC input / system voltage (V, integer)
- vmin_mppt, vmax_mppt: MPPT tracking voltage range (V)
- imax_mppt: maximum DC input current per MPPT tracker (A)
- mppt_channels: number of independent MPPT trackers (integer)
- phase: "single" or "three"
- output_v: nominal AC output voltage (V, integer)
- warranty_yr: standard product warranty in years (integer)
- Use null for any field you cannot find with confidence
- For multi-MPPT inverters, imax_mppt is the per-tracker value (not total)
"""


def parse_panel_datasheet(pdf_bytes: bytes) -> list[dict]:
    """
    Extract panel specs from a PDF datasheet.

    Returns a list of model dicts (one per power class found in the datasheet).
    Raises ValueError if no models extracted.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
                },
                {"type": "text", "text": _PANEL_PROMPT},
            ],
        }],
    )
    return _parse_list_response(response, "paneles")


def parse_inverter_datasheet(pdf_bytes: bytes) -> list[dict]:
    """
    Extract inverter specs from a PDF datasheet.

    Returns a list of model dicts (one per kW variant found in the datasheet).
    Raises ValueError if no models extracted.
    """
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    response = client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
                },
                {"type": "text", "text": _INVERTER_PROMPT},
            ],
        }],
    )
    return _parse_list_response(response, "inversores")


def _parse_list_response(response, label: str) -> list[dict]:
    text = response.content[0].text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise ValueError(f"No se extrajeron {label} del datasheet.")
    return data
