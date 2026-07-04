"""
Load-based monthly kWh estimation from installed electrical loads.

Scenarios (demand_factor, peak_hours):
    Conservative: 40% / 6h
    Optimal:      55% / 8h
    Maximum:      75% / 10h
"""
from __future__ import annotations

_SCENARIOS = [
    {"name": "Conservador", "demand_factor": 0.40, "peak_hours": 6},
    {"name": "Óptimo",      "demand_factor": 0.55, "peak_hours": 8},
    {"name": "Máximo",      "demand_factor": 0.75, "peak_hours": 10},
]

DEFAULT_LOADS = [
    {"Descripción": "Refrigerador",       "W": 150,  "Und": 1, "h/día": 24, "días/mes": 30},
    {"Descripción": "Iluminación general","W": 200,  "Und": 1, "h/día": 6,  "días/mes": 30},
    {"Descripción": "TV + entretenimiento","W": 150,  "Und": 1, "h/día": 5,  "días/mes": 30},
    {"Descripción": "Aire acondicionado", "W": 1200, "Und": 1, "h/día": 8,  "días/mes": 20},
    {"Descripción": "Lavadora",           "W": 500,  "Und": 1, "h/día": 1,  "días/mes": 8},
]


def kwh_from_loads(loads: list[dict]) -> float:
    """
    Sum monthly kWh from a list of load records.

    Each record must have keys: W (watts), Und (units), h/día (hours/day), días/mes (days/month).
    Returns total kWh/month.
    """
    total = 0.0
    for row in loads:
        w = float(row.get("W") or 0)
        qty = float(row.get("Und") or 1)
        h = float(row.get("h/día") or 0)
        d = float(row.get("días/mes") or 0)
        total += w * qty * h * d / 1000
    return round(total, 1)


_SEASONAL_PROMPT = """\
You are estimating monthly electricity consumption for a property in Costa Rica based on its installed electrical loads.

Installed loads:
{loads_table}

Location: {location}
Nominal monthly consumption (all loads at rated hours/days): {nominal_kwh:.0f} kWh

Estimate actual consumption for each calendar month, accounting for:
- Costa Rica dry season (December–April): hotter → more AC/fan hours, higher consumption
- Rainy season (May–October): cooler → less AC, lower consumption
- Which loads are seasonal (AC, fans, pool pump) vs. constant (fridge, lighting, router)
- The Horas/día and Días/mes in the table represent typical usage — adjust them per season
- Round each month to the nearest 10 kWh

Return ONLY a JSON array of 12 integers:
[January, February, March, April, May, June, July, August, September, October, November, December]
"""


def estimate_loads_12_months_ai(
    loads: list[dict],
    location: str = "Costa Rica",
) -> list[float]:
    """
    Ask Claude to estimate monthly kWh for all 12 months based on installed loads and seasonality.

    Args:
        loads: List of dicts with keys Descripción, W, Und, h/día, días/mes.
        location: City/province for seasonal context.

    Returns:
        List of 12 floats [Jan, Feb, ..., Dec]. Falls back to flat estimate on error.
    """
    import json, os, anthropic

    nominal = kwh_from_loads(loads)

    rows = []
    for row in loads:
        desc = row.get("Descripción", "Carga")
        w    = float(row.get("W") or 0)
        qty  = int(row.get("Und") or 1)
        h    = float(row.get("h/día") or 0)
        d    = int(row.get("días/mes") or 0)
        kwh  = round(w * qty * h * d / 1000, 1)
        rows.append(f"  - {desc}: {int(w*qty)}W, {h}h/día, {d}días/mes → {kwh} kWh/mes")
    loads_table = "\n".join(rows) if rows else "  (ninguna)"

    prompt = _SEASONAL_PROMPT.format(
        loads_table=loads_table,
        location=location,
        nominal_kwh=nominal,
    )

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
        values = json.loads(text)
        if isinstance(values, list) and len(values) == 12:
            return [float(v) for v in values]
    except Exception:
        pass

    return [nominal] * 12  # flat fallback


def estimate_from_tablero(total_kva: float, demand_factor: float | None = None) -> list[dict]:
    """
    Estimate monthly kWh from a tablero's total installed capacity (kVA).

    Args:
        total_kva: Total installed capacity from tablero in kVA.
        demand_factor: Override; if None, returns all 3 scenarios.

    Returns list of scenario dicts with:
        name, demand_factor, peak_hours, daily_kwh, monthly_kwh, label
    """
    total_kw = total_kva * 0.9  # assume PF=0.9

    scenarios = (
        [s for s in _SCENARIOS if s["demand_factor"] == demand_factor]
        if demand_factor is not None
        else _SCENARIOS
    )

    results = []
    for s in scenarios:
        daily_kwh = total_kw * s["demand_factor"] * s["peak_hours"]
        monthly_kwh = round(daily_kwh * 30, 1)
        results.append({
            **s,
            "daily_kwh": round(daily_kwh, 1),
            "monthly_kwh": monthly_kwh,
            "label": f"{s['name']}: {monthly_kwh:,.0f} kWh/mes",
        })

    return results
