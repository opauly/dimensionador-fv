"""Step 3 — Sitio e irradiancia. Port of wizard/common.py:step3_site().

Per PLAN §1.3, `build_context(blob)` is the one function every route
rendering any part of this step calls — the full-page GET, the `Siguiente`/
`Atrás` persist-and-redirect POSTs, and the `pvgis` action fragment alike.
"""
from __future__ import annotations

from webapp.wizard_steps.common import DEFAULT_SYSTEM_TYPE, to_float

BLOCKED_NOTE = "Es necesario obtener los datos de irradiancia para continuar."


def needs_daily_series(system_type: str) -> bool:
    """Off-Grid/Hybrid need the real daily-resolution PVGIS series for the
    Step 6 battery-SoC simulation; Grid Zero has no battery-reliability
    concept, so it deliberately skips the extra PVGIS call
    (wizard/common.py L297-298)."""
    return system_type in ("off_grid", "hybrid")


def build_context(blob: dict) -> dict:
    blob = blob or {}
    site = blob.get("site") or {}
    client = blob.get("client") or {}
    meta = blob.get("meta") or {}

    default_location = client.get("location") or ""
    city = site.get("city") or ""
    province = site.get("province") or ""
    if not city and default_location and "," in default_location:
        parts = [p.strip() for p in default_location.split(",", 1)]
        city = parts[0]
        province = parts[1] if len(parts) > 1 else ""

    pvgis_data = site.get("pvgis_data")
    lat = site.get("lat")
    lon = site.get("lon")
    system_type = meta.get("system_type") or DEFAULT_SYSTEM_TYPE

    monthly = (pvgis_data or {}).get("monthly_kwh_kwp") or []
    yearly = (pvgis_data or {}).get("yearly_kwh_kwp")
    avg_monthly = round(sum(monthly) / 12, 1) if monthly else None

    chart_html = None
    if monthly and len(monthly) == 12:
        from webapp.figures import fig_to_fragment, irradiance_monthly_fig

        chart_html = fig_to_fragment(irradiance_monthly_fig(monthly))

    return {
        "city": city,
        "province": province,
        # Manual-override inputs default to whatever lat/lon is already
        # resolved — same as Streamlit's `value=float(current.get("lat", 0.0))`.
        "lat_manual": lat or 0.0,
        "lon_manual": lon or 0.0,
        "pvgis_data": pvgis_data,
        "avg_monthly": avg_monthly,
        "yearly": yearly,
        "chart_html": chart_html,
        "can_continue": bool(pvgis_data) and lat is not None,
        "system_type": system_type,
        "blocked_note": BLOCKED_NOTE,
    }


def save_step(form) -> dict:
    """`Siguiente`/`Atrás`'s persisted fields — only city/province, since
    lat/lon/pvgis_data/pvgis_daily are already persisted by the `pvgis`
    action the moment a fetch succeeds (PLAN §1.1: every mutation is a
    save — no "unsaved until Next" tier here, unlike Streamlit's widget
    state)."""
    return {
        "city": (form.get("city") or "").strip(),
        "province": (form.get("province") or "").strip(),
    }


def run_pvgis(blob: dict, form) -> tuple[dict, str | None]:
    """The `pvgis` action's core logic — verbatim port of step3_site()'s
    "Obtener irradiancia solar" button handler, including which fields get
    reset to None on a failed geocode vs. which are left untouched on a
    failed PVGIS fetch. Returns (values-to-patch-into-site, error-or-None)."""
    from calculations.pvgis import fetch_daily_series, fetch_irradiance, geocode_cr

    site = (blob or {}).get("site") or {}
    meta = (blob or {}).get("meta") or {}
    system_type = meta.get("system_type") or DEFAULT_SYSTEM_TYPE

    city = (form.get("city") or "").strip()
    province = (form.get("province") or "").strip()
    lat_manual = to_float(form.get("lat_manual"), 0.0)
    lon_manual = to_float(form.get("lon_manual"), 0.0)

    pvgis_data = site.get("pvgis_data")
    pvgis_daily = site.get("pvgis_daily")
    lat = site.get("lat")
    lon = site.get("lon")
    error = None

    if lat_manual != 0.0 and lon_manual != 0.0:
        lat, lon = lat_manual, lon_manual
    else:
        coords = geocode_cr(city, province)
        if coords:
            lat, lon = coords
        else:
            error = (
                f"No se encontraron coordenadas para '{city}, {province} Costa Rica'. "
                "Ingresa lat/lon manualmente."
            )
            lat, lon = None, None

    if lat and lon:
        try:
            pvgis_data = fetch_irradiance(lat, lon)
            if needs_daily_series(system_type):
                pvgis_daily = fetch_daily_series(lat, lon)
        except Exception as exc:
            error = f"Error PVGIS: {exc}"

    values = {
        "city": city, "province": province, "lat": lat, "lon": lon,
        "pvgis_data": pvgis_data, "pvgis_daily": pvgis_daily,
    }
    return values, error
