"""ARESEP tariff updater (pages/05_admin.py's _tariff_updater / _build_changes
and friends) — upload the Cuadro E-8 .xlsx, diff against the DB, let the
admin confirm T-CO's hand-corrected-vs-ARESEP-raw conflicts, then apply.

Stateless across the two POSTs (upload -> confirm -> apply): the parsed
diff travels back to the browser as a JSON blob in a hidden field rather
than server-side session state, so it round-trips through whatever the
admin actually confirmed instead of re-parsing a re-uploaded file.
"""
from __future__ import annotations

import json

from flask import redirect, render_template, request, url_for

TARIFF_META = {
    "T-RE": {"name": "Tarifa Residencial", "sector": "residential", "iva_threshold_kwh": 280},
    "T-CO": {"name": "Comercios y Servicios", "sector": "commercial", "iva_threshold_kwh": 0},
}


def _fmt_crc(v):
    return f"₡{v:,.2f}" if isinstance(v, (int, float)) else "—"


def _fmt_rate(v):
    return f"₡{v:.4f}/kWh" if isinstance(v, (int, float)) else "—"


def _fmt_demand(rate, threshold):
    if not rate:
        return "—"
    return f"₡{rate:,.2f}/kW  (>  {threshold} kW)" if threshold else f"₡{rate:,.2f}/kW"


def _tier_label(t):
    hi = t.get("to_kwh")
    return f"{t['from_kwh']}–{hi} kWh" if hi else f"{t['from_kwh']} kWh en adelante"


def _tiers_changed(cur, new):
    if len(cur) != len(new):
        return True
    return any(
        abs(ct.get("rate_crc", 0) - nt["rate_crc"]) > 0.001
        or ct.get("from_kwh") != nt["from_kwh"] or ct.get("to_kwh") != nt["to_kwh"]
        for ct, nt in zip(cur, new)
    )


def _energy_changed(cur, new_data):
    new_access = new_data["access_charge_crc"]
    cur_access = cur.get("access_charge_crc") or 0.0
    return abs(new_access - cur_access) > 0.01 or _tiers_changed(cur.get("tiers", []), new_data.get("tiers", []))


def _demand_changed(cur, new_data):
    new_demand = new_data.get("demand_rate_crc", 0.0)
    cur_demand = cur.get("demand_rate_crc") or 0.0
    new_thresh = new_data.get("demand_threshold_kw", 0)
    cur_thresh = cur.get("demand_threshold_kw") or 0
    return abs(new_demand - cur_demand) > 0.01 or new_thresh != cur_thresh


def _build_changes(parsed, current_db):
    changes = []
    for abbrev, tariffs in parsed.items():
        for code, new_data in tariffs.items():
            cur = current_db.get(abbrev, {}).get(code)
            if cur is None:
                changes.append({
                    "abbrev": abbrev, "code": code, "tariff_type_id": None,
                    "has_change": True, "is_new": True,
                    "energy_changed": True, "demand_changed": True,
                    "new": new_data, "cur": {},
                })
                continue
            energy_changed = _energy_changed(cur, new_data)
            demand_changed = _demand_changed(cur, new_data)
            changes.append({
                "abbrev": abbrev, "code": code, "tariff_type_id": cur["id"],
                "has_change": energy_changed or demand_changed, "is_new": False,
                "energy_changed": energy_changed, "demand_changed": demand_changed,
                "new": new_data, "cur": cur,
            })
    return changes


def render_aresep_actualizar():
    return render_template("admin/_aresep_actualizar.html", stage="upload", error=None)


def register(bp):
    @bp.route("/aresep/actualizar/upload", methods=["POST"])
    def aresep_upload():
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return render_template("admin/_aresep_actualizar.html", stage="upload",
                                    error="Selecciona el archivo Cuadro E-8 (.xlsx).")
        try:
            from aresep.tariff_parser import parse_vigentes
            parsed = parse_vigentes(uploaded)
        except Exception as exc:
            return render_template("admin/_aresep_actualizar.html", stage="upload",
                                    error=f"Error al leer el archivo: {exc}")
        if not parsed:
            return render_template("admin/_aresep_actualizar.html", stage="upload",
                                    error="No se encontraron tarifas en el archivo. Verifica que sea el Cuadro E-8 correcto.")

        from database.tariffs_db import get_tariff_info

        current_db = {}
        for abbrev, tariffs in parsed.items():
            current_db[abbrev] = {}
            for code in tariffs:
                try:
                    info = get_tariff_info(abbrev, code)
                    if info:
                        current_db[abbrev][code] = info
                except Exception:
                    pass

        changes = _build_changes(parsed, current_db)
        if not any(c["has_change"] for c in changes):
            return render_template("admin/_aresep_actualizar.html", stage="upload",
                                    error=None,
                                    info="Los valores del archivo coinciden con la base de datos. No hay cambios que aplicar.")

        by_dist = {}
        for c in changes:
            by_dist.setdefault(c["abbrev"], []).append(c)

        return render_template(
            "admin/_aresep_actualizar.html", stage="confirm", error=None,
            by_dist=by_dist, changes_json=json.dumps(changes),
            fmt_crc=_fmt_crc, fmt_rate=_fmt_rate, fmt_demand=_fmt_demand, tier_label=_tier_label,
        )

    @bp.route("/aresep/actualizar/apply", methods=["POST"])
    def aresep_apply():
        from database.tariffs_db import replace_tariff_tiers, upsert_tariff_type_row

        changes = json.loads(request.form.get("changes_json", "[]"))
        form = request.form

        to_update = []
        for c in changes:
            key = f"{c['abbrev']}::{c['code']}"
            if not c["has_change"]:
                continue
            if c["is_new"] or c["demand_changed"]:
                to_update.append(c)
                continue
            # T-CO energy changes need the admin's explicit opt-in (see
            # _energy_changed's docstring: the DB value may be a deliberate
            # hand-correction, not staleness) — everything else (T-RE, or
            # T-CO's demand-only changes) applies without a checkbox.
            if c["code"] == "T-CO" and c["energy_changed"]:
                if form.get(f"confirm_{key}") == "on":
                    to_update.append(c)
            elif c["has_change"]:
                to_update.append(c)

        errors = []
        updated = 0
        for c in to_update:
            try:
                meta = TARIFF_META[c["code"]]
                new_data, cur_data = c["new"], c["cur"]
                use_new_energy = c["is_new"] or (
                    form.get(f"confirm_{c['abbrev']}::{c['code']}") == "on"
                    if c["code"] == "T-CO" and c["energy_changed"] else True
                )
                access_charge = new_data["access_charge_crc"] if use_new_energy else (cur_data.get("access_charge_crc") or 0.0)
                tiers = new_data.get("tiers", []) if use_new_energy else cur_data.get("tiers", [])
                tt_id = upsert_tariff_type_row(
                    distributor_abbrev=c["abbrev"], code=c["code"], name=meta["name"], sector=meta["sector"],
                    access_charge_crc=access_charge, demand_rate_crc=new_data.get("demand_rate_crc", 0.0),
                    demand_threshold_kw=new_data.get("demand_threshold_kw", 0), iva_threshold_kwh=meta["iva_threshold_kwh"],
                )
                replace_tariff_tiers(tt_id, tiers)
                updated += 1
            except Exception as exc:
                errors.append(f"{c['abbrev']} {c['code']}: {exc}")

        return render_template("admin/_aresep_actualizar.html", stage="done", updated=updated, errors=errors)
