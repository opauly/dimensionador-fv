"""Equipment catalog CRUD (Paneles/Inversores/Baterías/Controladores/Monitoreo)
— a generic engine since all five share the same shape: brand+model
identity, a cost+IVA block, notes, and duplicate detection on brand+model.
Field lists and payload-building stay per-type (bespoke, not derived) so
the exact "0 means None" semantics from pages/05_admin.py's Streamlit
forms are preserved faithfully rather than guessed at generically.
"""
from __future__ import annotations

from flask import abort, redirect, render_template, request, url_for

IVA_OPTIONS = [(0.0, "0% (exento)"), (0.13, "13%")]


def _usd(v):
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "—"


def _pct(v):
    return f"{v * 100:.0f}%" if isinstance(v, (int, float)) else "—"


PANEL_COLS = [("wp", "Wp", None), ("voc", "Voc", None), ("vmp", "Vmp", None),
              ("isc", "Isc", None), ("cost_usd", "Costo", _usd), ("cost_iva_rate", "IVA", _pct)]
INVERTER_COLS = [("kw", "kW", None), ("type", "Tipo", None), ("phase", "Fase", None),
                  ("mppt_channels", "MPPT", None), ("cost_usd", "Costo", _usd), ("cost_iva_rate", "IVA", _pct)]
BATTERY_COLS = [("chemistry", "Química", None), ("capacity_kwh", "kWh", None), ("voltage_v", "V", None),
                ("cycles", "Ciclos", None), ("cost_usd", "Costo", _usd), ("cost_iva_rate", "IVA", _pct)]
CC_COLS = [("type", "Tipo", None), ("vin_max", "Vin máx", None), ("imax_out", "Imax salida", None),
           ("cost_usd", "Costo", _usd), ("cost_iva_rate", "IVA", _pct)]
MONITORING_COLS = [("compatible_with", "Compatible con", None),
                    ("cost_usd", "Costo", _usd), ("cost_iva_rate", "IVA", _pct)]


def _f(form, key, default=None):
    """Parse a form field as float; None/blank -> default."""
    raw = (form.get(key) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _fo(form, key):
    """Parse as float, but 0/blank collapses to None (matches `x or None`)."""
    v = _f(form, key, 0)
    return v or None


def _i(form, key, default=0):
    v = _f(form, key, default)
    return int(v) if v is not None else default


# ── per-type field specs (for rendering the form) + payload builders ──────────

def _panel_fields(src):
    return [
        {"key": "brand", "label": "Marca *", "type": "text", "value": src.get("brand", "")},
        {"key": "model", "label": "Modelo *", "type": "text", "value": src.get("model", "")},
        {"key": "wp", "label": "Potencia (Wp) *", "type": "number", "step": "5", "value": src.get("wp", "")},
        {"key": "voc", "label": "Voc (V)", "type": "number", "step": "0.01", "value": src.get("voc", "")},
        {"key": "vmp", "label": "Vmp (V)", "type": "number", "step": "0.01", "value": src.get("vmp", "")},
        {"key": "isc", "label": "Isc (A)", "type": "number", "step": "0.01", "value": src.get("isc", "")},
        {"key": "imp", "label": "Imp (A)", "type": "number", "step": "0.01", "value": src.get("imp", "")},
        {"key": "temp_coeff_pmax", "label": "Coef. temp. Pmax (%/°C)", "type": "number", "step": "0.001",
         "value": src.get("temp_coeff_pmax", -0.35)},
        {"key": "width_m", "label": "Ancho (m)", "type": "number", "step": "0.0001", "value": src.get("width_m", "")},
        {"key": "height_m", "label": "Alto (m)", "type": "number", "step": "0.0001", "value": src.get("height_m", "")},
        {"key": "warranty_product_yr", "label": "Garantía producto (años)", "type": "number", "step": "1",
         "value": src.get("warranty_product_yr", 12)},
        {"key": "warranty_power_yr", "label": "Garantía potencia (años)", "type": "number", "step": "1",
         "value": src.get("warranty_power_yr", 25)},
    ]


def _panel_payload(form):
    return {
        "brand": form.get("brand", "").strip(), "model": form.get("model", "").strip(),
        "wp": int(_f(form, "wp", 0)), "voc": _fo(form, "voc"), "vmp": _fo(form, "vmp"),
        "isc": _fo(form, "isc"), "imp": _fo(form, "imp"),
        "temp_coeff_pmax": _fo(form, "temp_coeff_pmax"),
        "width_m": _fo(form, "width_m"), "height_m": _fo(form, "height_m"),
        "warranty_product_yr": _i(form, "warranty_product_yr", 12),
        "warranty_power_yr": _i(form, "warranty_power_yr", 25),
    }


def _panel_validate(form):
    if not form.get("brand", "").strip() or not form.get("model", "").strip() or _f(form, "wp", 0) <= 0:
        return "Marca, modelo y potencia son obligatorios."
    return None


def _inverter_fields(src):
    return [
        {"key": "brand", "label": "Marca *", "type": "text", "value": src.get("brand", "")},
        {"key": "model", "label": "Modelo *", "type": "text", "value": src.get("model", "")},
        {"key": "kw", "label": "Potencia (kW) *", "type": "number", "step": "0.1", "value": src.get("kw", "")},
        {"key": "type", "label": "Tipo", "type": "select", "value": src.get("type", "string_inverter"),
         "options": [("string_inverter", "Inversor de string"), ("microinverter", "Microinversor"), ("hybrid", "Híbrido")]},
        {"key": "phase", "label": "Fase", "type": "select", "value": src.get("phase", "single"),
         "options": [("single", "Monofásico"), ("three", "Trifásico")]},
        {"key": "vmax", "label": "V máx entrada DC (V)", "type": "number", "step": "10", "value": src.get("vmax", "")},
        {"key": "vmin_mppt", "label": "Vmin MPPT (V)", "type": "number", "step": "1", "value": src.get("vmin_mppt", "")},
        {"key": "vmax_mppt", "label": "Vmax MPPT (V)", "type": "number", "step": "1", "value": src.get("vmax_mppt", "")},
        {"key": "imax_mppt", "label": "Imax por MPPT (A)", "type": "number", "step": "0.1", "value": src.get("imax_mppt", "")},
        {"key": "mppt_channels", "label": "Canales MPPT", "type": "number", "step": "1", "value": src.get("mppt_channels", 1)},
        {"key": "output_v", "label": "Tensión salida AC (V)", "type": "number", "step": "1", "value": src.get("output_v", 240)},
        {"key": "ac_output_current_a", "label": "Corriente AC salida continua (A)", "type": "number", "step": "1",
         "value": src.get("ac_output_current_a", "")},
        {"key": "ac_input_current_max_a", "label": "Corriente AC entrada máx. (A)", "type": "number", "step": "1",
         "value": src.get("ac_input_current_max_a", ""),
         "help": "Solo inversores híbridos (passthrough). Dejar en 0 si no aplica."},
        {"key": "warranty_yr", "label": "Garantía (años)", "type": "number", "step": "1", "value": src.get("warranty_yr", 5)},
    ]


def _inverter_payload(form):
    return {
        "brand": form.get("brand", "").strip(), "model": form.get("model", "").strip(),
        "kw": _f(form, "kw", 0), "type": form.get("type", "string_inverter"), "phase": form.get("phase", "single"),
        "vmax": _fo(form, "vmax"), "vmin_mppt": _fo(form, "vmin_mppt"), "vmax_mppt": _fo(form, "vmax_mppt"),
        "imax_mppt": _fo(form, "imax_mppt"), "mppt_channels": _i(form, "mppt_channels", 1),
        "output_v": _fo(form, "output_v"), "ac_output_current_a": _fo(form, "ac_output_current_a"),
        "ac_input_current_max_a": _fo(form, "ac_input_current_max_a"), "warranty_yr": _i(form, "warranty_yr", 5),
    }


def _inverter_validate(form):
    if not form.get("brand", "").strip() or not form.get("model", "").strip() or _f(form, "kw", 0) <= 0:
        return "Marca, modelo y potencia son obligatorios."
    return None


def _battery_fields(src):
    return [
        {"key": "brand", "label": "Marca *", "type": "text", "value": src.get("brand", "")},
        {"key": "model", "label": "Modelo *", "type": "text", "value": src.get("model", "")},
        {"key": "chemistry", "label": "Química", "type": "text", "value": src.get("chemistry", "LiFePO4")},
        {"key": "capacity_kwh", "label": "Capacidad (kWh) *", "type": "number", "step": "0.01", "value": src.get("capacity_kwh", "")},
        {"key": "capacity_ah", "label": "Capacidad (Ah)", "type": "number", "step": "0.1", "value": src.get("capacity_ah", "")},
        {"key": "voltage_v", "label": "Voltaje (V) *", "type": "number", "step": "1", "value": src.get("voltage_v", 48)},
        {"key": "dod_pct", "label": "Descarga máxima DoD (%)", "type": "number", "step": "1", "value": src.get("dod_pct", 80)},
        {"key": "cycles", "label": "Ciclos", "type": "number", "step": "100", "value": src.get("cycles", "")},
        {"key": "warranty_yr", "label": "Garantía (años)", "type": "number", "step": "1", "value": src.get("warranty_yr", 10)},
    ]


def _battery_payload(form):
    return {
        "brand": form.get("brand", "").strip(), "model": form.get("model", "").strip(),
        "chemistry": form.get("chemistry", "").strip() or "LiFePO4",
        "capacity_kwh": _f(form, "capacity_kwh", 0), "capacity_ah": _fo(form, "capacity_ah"),
        "voltage_v": _f(form, "voltage_v", 48), "dod_pct": _i(form, "dod_pct", 80),
        "cycles": _fo(form, "cycles"), "warranty_yr": _i(form, "warranty_yr", 10),
    }


def _battery_validate(form):
    if (not form.get("brand", "").strip() or not form.get("model", "").strip()
            or _f(form, "capacity_kwh", 0) <= 0 or _f(form, "voltage_v", 0) <= 0):
        return "Marca, modelo, capacidad y voltaje son obligatorios."
    return None


def _cc_fields(src):
    return [
        {"key": "brand", "label": "Marca *", "type": "text", "value": src.get("brand", "")},
        {"key": "model", "label": "Modelo *", "type": "text", "value": src.get("model", "")},
        {"key": "type", "label": "Tipo *", "type": "select", "value": src.get("type", "MPPT"),
         "options": [("MPPT", "MPPT"), ("PWM", "PWM")]},
        {"key": "vin_max", "label": "Vin máx (V) *", "type": "number", "step": "1", "value": src.get("vin_max", "")},
        {"key": "vout", "label": "Vout (V)", "type": "number", "step": "1", "value": src.get("vout", "")},
        {"key": "imax_in", "label": "Imax entrada (A) *", "type": "number", "step": "0.1", "value": src.get("imax_in", "")},
        {"key": "imax_out", "label": "Imax salida (A)", "type": "number", "step": "0.1", "value": src.get("imax_out", "")},
    ]


def _cc_payload(form):
    return {
        "brand": form.get("brand", "").strip(), "model": form.get("model", "").strip(),
        "type": form.get("type", "MPPT"), "vin_max": _f(form, "vin_max", 0), "vout": _fo(form, "vout"),
        "imax_in": _f(form, "imax_in", 0), "imax_out": _fo(form, "imax_out"),
    }


def _cc_validate(form):
    if (not form.get("brand", "").strip() or not form.get("model", "").strip()
            or _f(form, "vin_max", 0) <= 0 or _f(form, "imax_in", 0) <= 0):
        return "Marca, modelo, Vin máx e Imax entrada son obligatorios."
    return None


def _monitoring_fields(src):
    return [
        {"key": "brand", "label": "Marca *", "type": "text", "value": src.get("brand", "")},
        {"key": "model", "label": "Modelo *", "type": "text", "value": src.get("model", "")},
        {"key": "compatible_with", "label": "Compatible con", "type": "text", "value": src.get("compatible_with", ""),
         "help": "Ej.: Victron Cerbo GX, Victron Ekrano GX"},
    ]


def _monitoring_payload(form):
    return {
        "brand": form.get("brand", "").strip(), "model": form.get("model", "").strip(),
        "compatible_with": form.get("compatible_with", "").strip() or None,
    }


def _monitoring_validate(form):
    if not form.get("brand", "").strip() or not form.get("model", "").strip():
        return "Marca y modelo son obligatorios."
    return None


def _specs():
    """Built lazily (not at import time) so the equipment_db imports stay local,
    matching the rest of this app's lazy-import convention."""
    from database.equipment_db import (
        delete_battery, delete_charge_controller, delete_inverter,
        delete_monitoring_device, delete_panel, list_batteries,
        list_charge_controllers, list_inverters, list_monitoring_devices,
        list_panels, upsert_battery, upsert_charge_controller, upsert_inverter,
        upsert_monitoring_device, upsert_panel,
    )
    return {
        "paneles": dict(list_fn=list_panels, upsert_fn=upsert_panel, delete_fn=delete_panel,
                         kind_label="panel", fields_fn=_panel_fields, payload_fn=_panel_payload,
                         validate_fn=_panel_validate, display_cols=PANEL_COLS),
        "inversores": dict(list_fn=list_inverters, upsert_fn=upsert_inverter, delete_fn=delete_inverter,
                            kind_label="inversor", fields_fn=_inverter_fields, payload_fn=_inverter_payload,
                            validate_fn=_inverter_validate, display_cols=INVERTER_COLS),
        "baterias": dict(list_fn=list_batteries, upsert_fn=upsert_battery, delete_fn=delete_battery,
                          kind_label="batería", fields_fn=_battery_fields, payload_fn=_battery_payload,
                          validate_fn=_battery_validate, display_cols=BATTERY_COLS),
        "controladores": dict(list_fn=list_charge_controllers, upsert_fn=upsert_charge_controller,
                               delete_fn=delete_charge_controller, kind_label="controlador de carga",
                               fields_fn=_cc_fields, payload_fn=_cc_payload, validate_fn=_cc_validate,
                               display_cols=CC_COLS),
        "monitoreo": dict(list_fn=list_monitoring_devices, upsert_fn=upsert_monitoring_device,
                           delete_fn=delete_monitoring_device, kind_label="equipo de monitoreo",
                           fields_fn=_monitoring_fields, payload_fn=_monitoring_payload,
                           validate_fn=_monitoring_validate, display_cols=MONITORING_COLS),
    }


def _find_duplicate(items, brand, model, exclude_id=None):
    b, m = (brand or "").strip().lower(), (model or "").strip().lower()
    if not b or not m:
        return None
    for it in items:
        if exclude_id and it.get("id") == exclude_id:
            continue
        if (it.get("brand") or "").strip().lower() == b and (it.get("model") or "").strip().lower() == m:
            return it
    return None


def render_equipos_panel(sub, request):
    spec = _specs()[sub]
    add = request.args.get("add") == "1"
    edit_id = request.args.get("edit")

    items = spec["list_fn"]()
    existing = next((it for it in items if it["id"] == edit_id), None) if edit_id else None

    form_mode = None
    if add:
        form_mode = "add"
    elif existing:
        form_mode = "edit"

    return _render(spec, sub, items, form_mode, existing, error=None, dup=None)


def _display_rows(spec, items):
    rows = []
    for it in items:
        row = {"id": it["id"], "brand": it.get("brand"), "model": it.get("model")}
        for key, label, fmt in spec["display_cols"]:
            v = it.get(key)
            row[key] = fmt(v) if fmt else v
        rows.append(row)
    return rows


def _render(spec, sub, items, form_mode, existing, error, dup, pending_form=None):
    return render_template(
        "admin/_equip_panel.html", sub=sub, kind_label=spec["kind_label"],
        items=_display_rows(spec, items), form_mode=form_mode, existing=existing or {},
        fields=spec["fields_fn"](existing or {}), iva_options=IVA_OPTIONS,
        display_cols=[{"key": k, "label": l} for k, l, _ in spec["display_cols"]],
        cost_usd=(existing or {}).get("cost_usd", ""), cost_iva_rate=(existing or {}).get("cost_iva_rate") or 0.0,
        notes=(existing or {}).get("notes", "") or "", error=error, dup=dup, pending_form=pending_form,
    )


def register(bp):
    @bp.route("/equipos/<sub>/save", methods=["POST"])
    def equipos_save(sub):
        specs = _specs()
        if sub not in specs:
            abort(404)
        spec = specs[sub]
        form = request.form
        edit_id = form.get("id") or None

        error = spec["validate_fn"](form)
        if error:
            existing = {**form.to_dict(), "id": edit_id, "cost_usd": form.get("cost_usd"),
                        "cost_iva_rate": float(form.get("cost_iva_rate") or 0.0)}
            return _render(spec, sub, spec["list_fn"](), "edit" if edit_id else "add", existing,
                           error=error, dup=None)

        payload = spec["payload_fn"](form)
        payload["cost_usd"] = _fo(form, "cost_usd")
        payload["cost_iva_rate"] = float(form.get("cost_iva_rate") or 0.0)
        payload["notes"] = form.get("notes", "").strip() or None
        if edit_id:
            payload["id"] = edit_id

        confirm_overwrite = form.get("confirm_overwrite") == "1"
        dup = _find_duplicate(spec["list_fn"](), payload["brand"], payload["model"], exclude_id=edit_id)
        if dup and not confirm_overwrite:
            return _render(spec, sub, spec["list_fn"](), "dup_confirm", payload,
                           error=None, dup=dup, pending_form=form)
        if dup and confirm_overwrite:
            payload["id"] = dup["id"]

        spec["upsert_fn"](payload)
        return redirect(url_for("admin.sub_view", section="equipos", sub=sub))

    @bp.route("/equipos/<sub>/<item_id>/delete", methods=["POST"])
    def equipos_delete(sub, item_id):
        specs = _specs()
        if sub not in specs:
            abort(404)
        specs[sub]["delete_fn"](item_id)
        return redirect(url_for("admin.sub_view", section="equipos", sub=sub))
