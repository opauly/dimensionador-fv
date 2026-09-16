"""Site registration + overview (pages/05_admin.py's _sites_section /
_new_site_form). Always requires a client from the start, same as Streamlit."""
from __future__ import annotations

from flask import redirect, render_template, request, url_for


def _overview_rows():
    from database.clients_db import list_all_clients
    from database.monitoring_sites_db import list_monitoring_sites
    from database.vrm_sites_db import list_vrm_sites_for_linking

    clients_by_id = {c["id"]: c["name"] for c in list_all_clients()}
    rows = []
    for s in list_monitoring_sites():
        rows.append({
            "site_id": s["site_id"], "display_name": s.get("display_name") or s["site_id"],
            "brand": s.get("brand") or "Victron Energy",
            "client_name": clients_by_id.get(s.get("client_id")),
            "active": s.get("active", True),
        })
    for s in list_vrm_sites_for_linking():
        rows.append({
            "site_id": s["site_id"], "display_name": s.get("display_name") or s["site_id"],
            "brand": "Victron Energy", "client_name": clients_by_id.get(s.get("public_client_id")),
            "active": s.get("active", True),
        })
    rows.sort(key=lambda r: r["display_name"])
    return rows


def render_sites_panel(request):
    from database.clients_db import list_all_clients
    import config

    add = request.args.get("add") == "1"
    if add:
        return render_template(
            "admin/_sites_panel.html", mode="add", clients=list_all_clients(),
            countries=sorted(config.COUNTRIES.items(), key=lambda kv: kv[1]),
            system_types=config.SYSTEM_TYPES, system_type_labels=config.SYSTEM_TYPE_LABELS,
            currencies=config.SUPPORTED_FLAT_CURRENCIES, error=None,
        )

    rows = _overview_rows()
    active_rows = [r for r in rows if r["active"]]
    unlinked = sum(1 for r in active_rows if not r["client_name"])
    kpis = [
        ("Total sitios", len(active_rows)),
        ("Victron", sum(1 for r in active_rows if r["brand"] == "Victron Energy")),
        ("Sin cliente vinculado", unlinked),
    ]
    return render_template("admin/_sites_panel.html", mode="list", rows=active_rows, kpis=kpis, unlinked=unlinked)


def register(bp):
    @bp.route("/sitios/save", methods=["POST"])
    def sites_save():
        from database.clients_db import list_all_clients
        from database.site_registration_db import register_new_site
        import config

        form = request.form
        is_victron = form.get("is_victron") == "on"
        client_id = form.get("client_id")
        display_name = form.get("display_name", "").strip()
        brand = form.get("brand", "").strip()

        def _fail(msg):
            return render_template(
                "admin/_sites_panel.html", mode="add", clients=list_all_clients(),
                countries=sorted(config.COUNTRIES.items(), key=lambda kv: kv[1]),
                system_types=config.SYSTEM_TYPES, system_type_labels=config.SYSTEM_TYPE_LABELS,
                currencies=config.SUPPORTED_FLAT_CURRENCIES, error=msg,
            )

        if not display_name:
            return _fail("El nombre del sitio es obligatorio.")
        if not is_victron and not brand:
            return _fail("La marca del equipo es obligatoria.")
        if not client_id:
            return _fail("Selecciona un cliente.")

        def _f(key, default=None):
            raw = (form.get(key) or "").strip()
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        commissioned_at = form.get("commissioned_at") or None
        common = dict(
            location=form.get("location") or None,
            latitude=_f("latitude"), longitude=_f("longitude"),
            country=(form.get("country") or "CR").strip().upper() or "CR",
            timezone=form.get("timezone", "").strip() or "America/Costa_Rica",
            system_type=form.get("system_type"),
            pv_kwp=_f("pv_kwp"), owner=form.get("owner") or None,
            commissioned_at=commissioned_at,
            report_language=form.get("report_language", "es"),
            active=form.get("active") == "on",
            battery_nominal_kwh=_f("battery_nominal_kwh"),
            battery_dod_pct=_f("battery_dod_pct"),
        )

        try:
            if is_victron:
                savings_rate = _f("savings_rate")
                site = register_new_site(
                    client_id, display_name, is_victron=True,
                    exports_to_grid=form.get("exports_to_grid") == "on",
                    notes=form.get("notes") or None,
                    savings_rate=savings_rate or None,
                    savings_currency=form.get("savings_currency") if savings_rate else None,
                    **common,
                )
            else:
                urls_raw = form.get("monitoring_urls", "")
                urls = [u.strip() for u in urls_raw.splitlines() if u.strip()] or None
                site = register_new_site(
                    client_id, display_name, is_victron=False, brand=brand,
                    panel_count=int(_f("panel_count", 0) or 0) or None,
                    inverter_count=int(_f("inverter_count", 0) or 0) or None,
                    battery_count=int(_f("battery_count", 0) or 0) or None,
                    monitoring_urls=urls, **common,
                )
        except Exception as exc:
            return _fail(f"Error al registrar el sitio: {exc}")

        return redirect(url_for("admin.index", section="sitios"))
