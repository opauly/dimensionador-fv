from __future__ import annotations
"""
Estimated savings for one VRM-API site's recent window — Fleet Dashboard
Phase 2.5 (2026-08-31). A thin wrapper, not a second implementation: the
actual tariff math (real ARESEP blended rate for `country == 'CR'`, a
configured flat `savings_rate`/`savings_currency` for anywhere else, `None`
with no basis for either) lives entirely in `victron/savings.py`'s own
`compute_weekly_savings()` — the exact function the PDF report already
calls. This module's only job is fetching the right window of already-
stored `energy_daily` rows (via `database/vrm_report_db.py`'s existing
`get_site()`/`get_energy_daily()` — not a new query shape) and handing
their summed load/grid kWh to that one function, so a future tariff-
formula change never has to happen in two places.
"""
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database import vrm_report_db as db
from victron import savings as savings_mod
from victron.vrm_series import DEFAULT_TZ_NAME

RANGE_DAYS = {"today": 1, "week": 7, "month": 30}


def _num(v: object, default: float = 0.0) -> float:
    return float(v) if v is not None else default


def _site_today(site: dict) -> date:
    """"Today" in the SITE's own configured timezone, not the server's —
    same fallback `victron/vrm_shape.py` already uses for the same
    reason (a brand-new/unconfigured site shouldn't crash this)."""
    tz_name = site.get("timezone") or DEFAULT_TZ_NAME
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(DEFAULT_TZ_NAME)
    return datetime.now(dt_timezone.utc).astimezone(zone).date()


def fetch_site_savings(site_id: str, *, range_key: str, schema: str = "vrm") -> dict | None:
    """`{"amount": float, "currency": str, "basis_count": int | None,
    "days_with_data": int}`, or `None` when the site doesn't exist or
    `compute_weekly_savings()` itself has no basis to compute one (no CR
    tariff data, or no flat rate configured for a non-CR site) — relayed
    from that function's own contract, never re-decided here."""
    if range_key not in RANGE_DAYS:
        raise ValueError(f"unknown range_key: {range_key!r}")

    site = db.get_site(site_id, schema)
    if site is None:
        return None

    end = _site_today(site)
    start = end - timedelta(days=RANGE_DAYS[range_key] - 1)
    rows = db.get_energy_daily(site_id, start, end, schema)

    totals = {
        "load": sum(_num(r.get("load_kwh")) for r in rows),
        "grid": sum(_num(r.get("grid_kwh")) for r in rows),
    }
    result = savings_mod.compute_weekly_savings(totals, site, len(rows))
    if result is None:
        return None
    return {
        "amount": result["amount"],
        "currency": result["currency"],
        "basis_count": result.get("basisCount"),
        "days_with_data": len(rows),
    }
