"""Extract equipment specs from manufacturer datasheets (PDF). Phase 4."""


def parse_panel_datasheet(pdf_bytes: bytes) -> dict:
    """
    Returns dict ready to upsert into panels table:
        brand, model, wp, voc, vmp, isc, imp, temp_coeff_pmax,
        width_m, height_m, weight_kg, warranty_product_yr, warranty_power_yr
    """
    raise NotImplementedError("Phase 4")


def parse_inverter_datasheet(pdf_bytes: bytes) -> dict:
    """
    Returns dict ready to upsert into inverters table:
        brand, model, kw, type, vmax, vmin_mppt, vmax_mppt, imax_mppt,
        mppt_channels, phase, output_v, warranty_yr
    """
    raise NotImplementedError("Phase 4")


def parse_battery_datasheet(pdf_bytes: bytes) -> dict:
    """
    Returns dict ready to upsert into batteries table:
        brand, model, chemistry, capacity_kwh, capacity_ah, voltage_v,
        dod_pct, cycles, warranty_yr
    """
    raise NotImplementedError("Phase 4")
