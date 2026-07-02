"""
Fetch CRC/USD exchange rate and cache it in Supabase app_settings.
TTL: 1 hour. Falls back to last cached value if API is unavailable.
"""
import os
import json
from datetime import datetime, timezone, timedelta

import requests

from config import EXCHANGE_RATE_CACHE_TTL, EXCHANGE_RATE_API_BASE


def _cache_key() -> str:
    return "exchange_rate_cache"


def get_exchange_rate() -> float:
    """Return CRC per 1 USD. Fetches fresh if cache is stale; falls back to cache on error."""
    from database.supabase_client import get_client

    db = get_client()
    row = db.table("app_settings").select("value").eq("key", _cache_key()).single().execute()
    cache = row.data["value"] if row.data else {}

    cached_at = cache.get("cached_at")
    cached_rate = cache.get("rate")

    if cached_at and cached_rate:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached_at)).total_seconds()
        if age < EXCHANGE_RATE_CACHE_TTL:
            return float(cached_rate)

    try:
        api_key = os.environ.get("EXCHANGE_RATE_API_KEY", "")
        if api_key:
            url = f"{EXCHANGE_RATE_API_BASE}/{api_key}/latest/USD"
        else:
            url = "https://open.er-api.com/v6/latest/USD"

        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        rate = float(data["rates"]["CRC"])

        db.table("app_settings").update(
            {
                "value": json.dumps({"rate": rate, "cached_at": datetime.now(timezone.utc).isoformat()}),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("key", _cache_key()).execute()

        return rate

    except Exception:
        if cached_rate:
            return float(cached_rate)
        return 520.0  # hard fallback if no cache and API unavailable
