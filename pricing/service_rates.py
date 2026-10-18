"""Per-Wp service pricing shared by the Costos steps and the Admin screens.

A service default can carry `cost_per_wp` ($ per quoted Wp). When it does, the
wizard pre-fills that line as `cost_per_wp x quoted kWp x 1000`, so mounting,
labor and electrical materials scale with the system instead of being a flat
number that is wrong for every project but one. With no rate (or no panels
chosen yet) the flat `unit_cost_usd` applies, exactly as before.
"""
from __future__ import annotations


def kwp_from_blob(blob: dict) -> float:
    """Quoted array size in kWp from the draft's chosen panel x count (0.0 if unset)."""
    eq = (blob or {}).get("equipment") or {}
    panel = eq.get("panel") or {}
    try:
        return float(eq.get("panel_count") or 0) * float(panel.get("wp") or 0) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def service_unit_cost(svc: dict, kwp: float) -> float:
    """Pre-fill cost for one service default."""
    rate = svc.get("cost_per_wp")
    if rate not in (None, "") and kwp and kwp > 0:
        return round(float(rate) * kwp * 1000.0, 2)
    return round(float(svc.get("unit_cost_usd") or 0), 2)


STALE_DAYS = 120


def price_note(updated_at, source) -> tuple[str, bool]:
    """('Actualizado 2026-08-18 · HCG proforma 180-2026', stale?) — the small
    grey note under a price in the Costos step. `stale` once the price is older
    than STALE_DAYS (supplier prices move; the note turns amber)."""
    from datetime import date

    if not updated_at:
        return "Sin fecha de actualización", False
    day = str(updated_at)[:10]
    text = f"Actualizado {day}" + (f" · {source}" if source else "")
    try:
        age = (date.today() - date.fromisoformat(day)).days
    except ValueError:
        return text, False
    return text, age > STALE_DAYS
