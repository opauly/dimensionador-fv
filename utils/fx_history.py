"""CRC-per-USD exchange rate for a given date (Finanzas, PLAN_PHASE25_FINANZAS.md).

Every rate used is stored in `fin_fx_rates`, so each date is looked up once
and the table slowly becomes our own history.

Order of lookup for a date:
  1. `fin_fx_rates` row for that exact date.
  2. Hacienda's "today" endpoint, when the date is today (Costa Rica time).
  3. Hacienda's historical endpoint (often down — 503 as of 2026-11-23).
  4. The nearest stored rate (earlier first, then later) — marked estimated.
  5. The app's general current rate (utils.currency) — marked estimated.

Rates are BCCR "venta" (sell), as published by Hacienda.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import requests

_HACIENDA_TODAY = "https://api.hacienda.go.cr/indicadores/tc/dolar"
_HACIENDA_HIST = "https://api.hacienda.go.cr/indicadores/tc/dolar/historico"
_CR_TZ = timezone(timedelta(hours=-6))


def today_cr() -> date:
    return datetime.now(_CR_TZ).date()


def _as_date(d) -> date:
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


def _store(d: date, rate: float, source: str) -> None:
    from database.supabase_client import get_client

    get_client().table("fin_fx_rates").upsert(
        {"rate_date": d.isoformat(), "crc_per_usd": round(rate, 4), "source": source}
    ).execute()


def save_manual_rate(d, rate: float) -> None:
    _store(_as_date(d), float(rate), "manual")


def _fetch_today() -> float | None:
    try:
        r = requests.get(_HACIENDA_TODAY, timeout=8)
        r.raise_for_status()
        return float(r.json()["venta"]["valor"])
    except Exception:
        return None


def _fetch_historical(d: date) -> float | None:
    try:
        r = requests.get(_HACIENDA_HIST, params={"d": d.isoformat(), "h": d.isoformat()}, timeout=8)
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else data.get("data") or []
        for row in rows:
            value = row.get("venta") or row.get("valor")
            if value:
                return float(value)
    except Exception:
        pass
    return None


def get_rate(d) -> tuple[float, bool]:
    """Return (crc_per_usd, estimated). `estimated` is True when no rate for
    that exact date was available and a nearby one was used instead."""
    from database.supabase_client import get_client

    d = _as_date(d)
    db = get_client()
    iso = d.isoformat()

    row = db.table("fin_fx_rates").select("crc_per_usd").eq("rate_date", iso).limit(1).execute().data
    if row:
        return float(row[0]["crc_per_usd"]), False

    rate = _fetch_today() if d == today_cr() else _fetch_historical(d)
    if rate:
        _store(d, rate, "hacienda")
        return rate, False

    before = (db.table("fin_fx_rates").select("crc_per_usd").lte("rate_date", iso)
              .order("rate_date", desc=True).limit(1).execute().data)
    if before:
        return float(before[0]["crc_per_usd"]), True
    after = (db.table("fin_fx_rates").select("crc_per_usd").gte("rate_date", iso)
             .order("rate_date").limit(1).execute().data)
    if after:
        return float(after[0]["crc_per_usd"]), True

    from utils.currency import get_exchange_rate

    return float(get_exchange_rate()), True
