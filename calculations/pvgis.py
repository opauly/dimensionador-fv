from __future__ import annotations
"""PVGIS REST API v5.2 integration with Supabase cache. Phase 2."""
import json
from datetime import datetime, timezone

import requests

from config import PVGIS_API_BASE


def _cache_key(lat: float, lon: float) -> str:
    return f"pvgis_{lat:.3f}_{lon:.3f}"


def get_cached_irradiance(lat: float, lon: float) -> dict | None:
    """Return cached PVGIS data for this lat/lon, or None if not cached."""
    from database.supabase_client import get_client

    key = _cache_key(lat, lon)
    try:
        result = (
            get_client()
            .table("app_settings")
            .select("value")
            .eq("key", key)
            .single()
            .execute()
        )
        if result.data:
            v = result.data["value"]
            return v if isinstance(v, dict) else json.loads(v)
    except Exception:
        pass
    return None


def _store_cache(lat: float, lon: float, data: dict) -> None:
    from database.supabase_client import get_client

    key = _cache_key(lat, lon)
    payload = {
        "key": key,
        "value": json.dumps(data),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        get_client().table("app_settings").upsert(payload, on_conflict="key").execute()
    except Exception:
        pass


def fetch_irradiance(lat: float, lon: float) -> dict:
    """
    Call PVGIS and return monthly kWh/kWp values.

    Caches result in Supabase by lat/lon to avoid repeat calls for the same site.
    Returns dict with keys: monthly_kwh_kwp (list[12]), yearly_kwh_kwp (float),
    optimal_angle (float), location_name (str).
    """
    cached = get_cached_irradiance(lat, lon)
    if cached:
        return cached

    url = f"{PVGIS_API_BASE}/PVcalc"
    params = {
        "lat": lat,
        "lon": lon,
        "peakpower": 1,
        "loss": 14,
        "outputformat": "json",
        "pvcalculation": 1,
        "mountingplace": "free",
        "pvtechchoice": "crystSi",
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    raw = resp.json()

    monthly = raw["outputs"]["monthly"]["fixed"]
    totals = raw["outputs"]["totals"]["fixed"]
    inputs_meta = raw.get("inputs", {})

    result = {
        "monthly_kwh_kwp": [m["E_m"] for m in monthly],
        "yearly_kwh_kwp": totals["E_y"],
        "optimal_angle": inputs_meta.get("mounting_system", {}).get("fixed", {}).get("slope", {}).get("value", 10),
        "location_name": f"{lat:.3f}, {lon:.3f}",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    _store_cache(lat, lon, result)
    return result


def geocode_cr(city: str, province: str) -> tuple[float, float] | None:
    """
    Geocode a Costa Rican city + province using a lookup table first,
    falling back to Nominatim.
    Returns (lat, lon) or None if not found.
    """
    key = f"{city.lower().strip()}, {province.lower().strip()}"
    match = _CR_LOOKUP.get(key) or _CR_LOOKUP.get(city.lower().strip())
    if match:
        return match

    try:
        q = f"{city}, {province}, Costa Rica"
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 1},
            headers={"User-Agent": "PaulyCoSolarTool/1.0"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        pass
    return None


# Lookup table for most-common Pauly&Co service areas
_CR_LOOKUP: dict[str, tuple[float, float]] = {
    "san josé": (9.9281, -84.0907),
    "san jose": (9.9281, -84.0907),
    "atenas": (9.9845, -84.3762),
    "grecia": (10.0694, -84.3175),
    "alajuela": (10.0162, -84.2125),
    "heredia": (9.9996, -84.1200),
    "liberia": (10.6340, -85.4360),
    "santa cruz": (10.2648, -85.5869),
    "nicoya": (10.1481, -85.4521),
    "puntarenas": (9.9766, -84.8333),
    "quepos": (9.4316, -84.1632),
    "cartago": (9.8643, -83.9196),
    "limón": (9.9919, -83.0359),
    "limon": (9.9919, -83.0359),
    "pérez zeledón": (9.3651, -83.6548),
    "perez zeledon": (9.3651, -83.6548),
    "san isidro": (9.3651, -83.6548),
    "golfito": (8.6519, -83.1832),
    "nosara": (9.9792, -85.6534),
    "tamarindo": (10.2998, -85.8373),
    "monteverde": (10.3097, -84.8291),
    "la fortuna": (10.4681, -84.6434),
    "fortuna": (10.4681, -84.6434),
    "turrialba": (9.9003, -83.6815),
    "paraíso": (9.8354, -83.8657),
    "paraiso": (9.8354, -83.8657),
    "naranjo": (10.1019, -84.3919),
    "palmares": (10.0604, -84.4338),
    "orotina": (9.9053, -84.5263),
    "san mateo": (9.9419, -84.5073),
    "esparza": (9.9931, -84.6659),
    "jacó": (9.6262, -84.6328),
    "jaco": (9.6262, -84.6328),
    "uvita": (9.1596, -83.7352),
    "dominical": (9.2528, -83.8578),
    "la palma": (8.3919, -83.1553),
    "guápiles": (10.2167, -83.7833),
    "guapiles": (10.2167, -83.7833),
    "sarapiquí": (10.4500, -84.0167),
    "sarapiqui": (10.4500, -84.0167),
}
