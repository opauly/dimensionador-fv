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
Extract technical specifications from this solar inverter datasheet (grid-tie or hybrid).

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
    "ac_output_current_a": 41.7,
    "ac_input_current_max_a": null,
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
- ac_output_current_a: rated CONTINUOUS AC output current in Amps (float) — usually listed
  directly on the datasheet (e.g. "Max continuous AC current" / "Corriente CA nominal");
  do not derive it yourself from kw/output_v, use the printed spec. Null if not stated.
- ac_input_current_max_a: for HYBRID inverters only — the maximum AC INPUT / passthrough
  current in Amps (e.g. Victron's "Max input current" for the AC-in/charger/UPS relay,
  sometimes shown per the model's own amp rating like "...50" in "48/5000/70-50"). This is
  a separate spec from ac_output_current_a — it protects the grid/generator-facing input,
  not the inverter's own output. Null for grid-tie string inverters and microinverters
  (they have no AC input), and null for hybrid units where this isn't stated.
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


_BATTERY_PROMPT = """
Extract technical specifications from this battery datasheet.

If the datasheet covers multiple capacity/voltage variants, return ALL as separate objects.

Return ONLY a JSON array — no markdown, no explanation:
[
  {
    "brand": "Pylontech",
    "model": "US5000C",
    "chemistry": "LiFePO4",
    "capacity_kwh": 4.8,
    "capacity_ah": 100,
    "voltage_v": 48,
    "dod_pct": 90,
    "cycles": 6000,
    "warranty_yr": 10
  }
]

Field rules:
- chemistry: battery chemistry as stated, e.g. "LiFePO4", "Li-ion", "Lead-acid", "AGM"
- capacity_kwh: usable or nominal energy capacity in kWh (float) — use whichever the
  datasheet states as the primary spec; if both usable and nominal are given, prefer usable
- capacity_ah: capacity in Ah at nominal voltage (float)
- voltage_v: nominal voltage in V (float)
- dod_pct: the datasheet's own rated/recommended maximum depth of discharge in %
  (integer, e.g. 90 for 90%) — use the printed spec, do not assume a generic value
- cycles: rated cycle life at the datasheet's stated DoD (integer)
- warranty_yr: product warranty in years (integer)
- Use null for any field you cannot find with confidence
"""


def parse_battery_datasheet(pdf_bytes: bytes) -> list[dict]:
    """
    Extract battery specs from a PDF datasheet.

    Returns a list of model dicts (one per capacity/voltage variant found).
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
                {"type": "text", "text": _BATTERY_PROMPT},
            ],
        }],
    )
    return _parse_list_response(response, "baterías")


_CHARGE_CONTROLLER_PROMPT = """
Extract technical specifications from this solar charge controller datasheet.

If the datasheet covers multiple current/voltage variants (e.g. 100A, 150A, 200A), return
ALL as separate objects.

Return ONLY a JSON array — no markdown, no explanation:
[
  {
    "brand": "Victron Energy",
    "model": "SmartSolar MPPT 250/100",
    "type": "MPPT",
    "vin_max": 250,
    "vout": 48,
    "imax_in": 25,
    "imax_out": 100
  }
]

Field rules:
- type: exactly "MPPT" or "PWM"
- vin_max: maximum PV input voltage (open-circuit, Voc) in V
- vout: nominal battery/output voltage in V (e.g. 12, 24, 48) — if the unit supports
  multiple battery voltages, use the highest supported
- imax_in: maximum PV input/short-circuit current in A, only if explicitly stated —
  leave null rather than estimating it from vin_max/imax_out
- imax_out: maximum battery charge current in A — for many controllers (e.g. Victron)
  this is the second number in the model name, "250/100" = 100A
- Use null for any field you cannot find with confidence
"""


def parse_charge_controller_datasheet(pdf_bytes: bytes) -> list[dict]:
    """
    Extract charge controller specs from a PDF datasheet.

    Returns a list of model dicts (one per current/voltage variant found).
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
                {"type": "text", "text": _CHARGE_CONTROLLER_PROMPT},
            ],
        }],
    )
    return _parse_list_response(response, "controladores de carga")


_MONITORING_PROMPT = """
Extract product information from this monitoring/communication device datasheet
(e.g. Victron Cerbo GX, Ekrano GX, or a similar system-monitoring gateway).

If the datasheet covers multiple variants (e.g. "GX" vs "GX Touch"), return ALL as
separate objects.

Return ONLY a JSON array — no markdown, no explanation:
[
  {
    "brand": "Victron Energy",
    "model": "Cerbo GX",
    "compatible_with": "Victron MultiPlus/Quattro inverters, MPPT charge controllers, Pylontech batteries via CAN-bus, VRM Portal"
  }
]

Field rules:
- compatible_with: short free-text summary of what this device connects to or works
  with (inverters/chargers, communication protocols, compatible battery brands, cloud
  monitoring platforms) — as described in the datasheet, not inferred
- Use null for any field you cannot find with confidence
"""


def parse_monitoring_datasheet(pdf_bytes: bytes) -> list[dict]:
    """
    Extract monitoring device info from a PDF datasheet.

    Returns a list of model dicts (one per variant found).
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
                {"type": "text", "text": _MONITORING_PROMPT},
            ],
        }],
    )
    return _parse_list_response(response, "equipos de monitoreo")
