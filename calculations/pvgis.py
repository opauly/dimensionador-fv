from __future__ import annotations
"""PVGIS REST API v5.2 integration with Supabase cache. Phase 2."""
import requests
from config import PVGIS_API_BASE


def fetch_irradiance(lat: float, lon: float) -> dict:
    """
    Call PVGIS and return monthly kWh/kWp values.

    Caches result in Supabase by lat/lon to avoid repeat calls for the same site.
    Returns dict with keys: monthly_kwh_kwp (list[12]), yearly_kwh_kwp (float),
    optimal_angle (float), location_name (str).
    """
    raise NotImplementedError("Phase 2")


def get_cached_irradiance(lat: float, lon: float) -> dict | None:
    """Return cached PVGIS data for this lat/lon, or None if not cached."""
    raise NotImplementedError("Phase 2")
