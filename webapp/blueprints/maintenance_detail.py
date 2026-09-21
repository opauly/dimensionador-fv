from __future__ import annotations
"""Property detail — port of pages/07_maintenance.py:_detail_section() onto
Flask/Jinja2/htmx (Phase 21 Step 2).

`detail_ctx(pid)` is this module's one load-bearing function, same discipline
as `maintenance_common.property_rows()`: the full GET /propiedad/<pid> page
and every write route on this page (visita, override, sitio) build their
render from it. Nothing here recomputes a property's status/next-due-date —
that stays exclusively `maintenance_common.property_rows()`'s job (this page
doesn't need it: the property's own row on Resumen already shows that, this
page shows the property's *sites*, *client* and *visit history*, none of
which `property_rows()` carries).

Credentials are the one exception to "everything reads from detail_ctx()":
per PLAN_PHASE21_MAINTENANCE_JINJA.md §0.4 Q3 / §1.6, they are fetched and
saved on demand (a site's plaintext WiFi/portal credentials are not embedded
in `detail_ctx()`'s output at all), so their GET/POST routes render their own
small `_credentials.html` fragment directly from `get_credentials()`/
`save_credentials()` rather than from `detail_ctx()`.
"""
from datetime import date

from flask import abort, redirect, render_template, request, url_for


def _site_ctx(s: dict) -> dict:
    """Port of _detail_section()'s per-site expander body (item 22): schema
    badge, the counts line joined by ' · ' with Streamlit's exact number
    formats, Comisionado, every monitoring URL, and the "Sin datos
    adicionales." fallback when all three are absent."""
    schema_badge = "Victron Monitor" if s["schema_name"] == "vrm" else "Monitoreo propio"
    counts = " · ".join(filter(None, [
        f"{s['panel_count']:.0f} paneles" if s.get("panel_count") else None,
        f"{s['inverter_count']:.0f} inversores" if s.get("inverter_count") else None,
        f"{s['battery_count']:.0f} baterías" if s.get("battery_count") else None,
        f"{s['pv_kwp']:.2f} kWp" if s.get("pv_kwp") else None,
    ]))
    monitoring_urls = s.get("monitoring_urls") or []
    return {
        "site_id": s["site_id"],
        "schema_name": s["schema_name"],
        "display_name": s.get("display_name") or s["site_id"],
        "schema_badge": schema_badge,
        "counts": counts,
        "commissioned_at": s.get("commissioned_at"),
        "monitoring_urls": monitoring_urls,
        "has_extra": bool(counts or s.get("commissioned_at") or monitoring_urls),
    }


def _visit_ctx(v: dict) -> dict:
    """Port of the Historial de visitas row logic verbatim (item 27): the
    grouped-visit branch via get_visit_group() when visit_group_id is set,
    else the row's own amount, else '—'; then technician · notes or '—'."""
    from database.site_properties_db import get_visit_group

    if v.get("visit_group_id"):
        group = get_visit_group(v["visit_group_id"])
        if group:
            g_amount = f"${group['amount_usd']:.2f}" if group.get("amount_usd") else "—"
            amount_label = f"{g_amount} (visita agrupada, {group['property_count']} propiedades)"
        else:
            amount_label = "—"
    else:
        amount_label = f"${v['amount_usd']:.2f}" if v.get("amount_usd") else "—"

    detail = " · ".join(filter(None, [v.get("technician"), v.get("notes")])) or "—"
    return {"visit_date": v["visit_date"], "amount_label": amount_label, "detail": detail}


def _client_sort_key_factory(this_client_id, client_name_by_id):
    """Port of _detail_section()'s _client_sort_key() verbatim (item 24):
    this property's client first, "Sin cliente" last, everyone else
    alphabetically by client name in between."""
    def _key(cid):
        if cid == this_client_id and cid:
            return (0, "")
        if not cid:
            return (2, "")
        return (1, client_name_by_id.get(cid, ""))
    return _key


def _linker_groups(property_id: str, this_client_id, linked_sites: list[dict]) -> list[dict]:
    """Port of the "Agregar o quitar sitios de esta propiedad" grouping/sort
    (item 24). Reads `list_all_sites_for_maintenance()` — the only source of
    every site in the register — so Lori Pickett's 3 excluded monitoring.sites
    rows (item 28) stay excluded here too, for free."""
    from database.clients_db import list_all_clients
    from database.site_properties_db import list_all_sites_for_maintenance

    client_name_by_id = {c["id"]: c["name"] for c in list_all_clients()}
    all_sites = list_all_sites_for_maintenance()
    linked_keys = {(s["site_id"], s["schema_name"]) for s in linked_sites}

    sites_by_client: dict[str, list[dict]] = {}
    for s in all_sites:
        sites_by_client.setdefault(s.get("client_id") or "", []).append(s)

    sort_key = _client_sort_key_factory(this_client_id, client_name_by_id)

    groups = []
    for cid in sorted(sites_by_client, key=sort_key):
        client_sites = sorted(sites_by_client[cid], key=lambda s: s.get("display_name") or s["site_id"])
        client_label = client_name_by_id.get(cid, "Sin cliente")
        site_rows = []
        for s in client_sites:
            key = (s["site_id"], s["schema_name"])
            is_linked_here = key in linked_keys
            linked_elsewhere = bool(s.get("property_id")) and not is_linked_here
            label = s.get("display_name") or s["site_id"]
            if linked_elsewhere:
                label += " (vinculado a otra propiedad — se movería aquí)"
            site_rows.append({
                "site_id": s["site_id"], "schema_name": s["schema_name"],
                "label": label, "checked": is_linked_here,
            })
        groups.append({"client_label": client_label, "sites": site_rows})
    return groups


def detail_ctx(property_id: str) -> dict | None:
    """Everything maintenance/detail.html (and every write route's re-render)
    needs. Returns None when the property doesn't exist (-> 404), mirroring
    get_property_bundle()'s own {"property": None, ...} shape."""
    from database.clients_db import get_client_by_id
    from database.site_properties_db import get_property_bundle, list_properties

    bundle = get_property_bundle(property_id)
    prop = bundle["property"]
    if not prop:
        return None

    client = None
    client_id = prop.get("client_id")
    if client_id:
        try:
            client = get_client_by_id(client_id)
        except Exception:
            client = None

    siblings = [p for p in list_properties(client_id) if p["id"] != property_id] if client_id else []

    return {
        "prop": prop,
        "client": client,
        "sites": [_site_ctx(s) for s in bundle["sites"]],
        "visits": [_visit_ctx(v) for v in bundle["visits"]],
        "siblings": siblings,
        "linker_groups": _linker_groups(property_id, client_id, bundle["sites"]),
        "today": date.today().isoformat(),
    }


def _parse_amount(raw: str | None) -> float:
    """Same behaviour as Streamlit's st.number_input(value=0.0, min_value=0.0):
    blank/invalid -> 0.0, which `amount or None` (item 25/26) then turns into
    NULL rather than a stored zero."""
    try:
        return float(raw) if raw not in (None, "") else 0.0
    except ValueError:
        return 0.0


def register(bp):
    @bp.route("/propiedad/<pid>")
    def propiedad(pid):
        try:
            ctx = detail_ctx(pid)
        except Exception as exc:
            return render_template("maintenance/detail.html", pid=pid, error=str(exc))
        if ctx is None:
            abort(404)
        return render_template("maintenance/detail.html", pid=pid, error=None, action_error=None, **ctx)

    @bp.route("/propiedad/<pid>/visita", methods=["POST"])
    def propiedad_visita(pid):
        from database.site_properties_db import add_bundled_visit, add_visit

        ctx = detail_ctx(pid)
        if ctx is None:
            abort(404)

        form = request.form
        visit_date = form.get("visit_date") or date.today().isoformat()
        amount = _parse_amount(form.get("amount"))
        technician = form.get("technician", "")
        notes = form.get("notes", "")
        extra_ids = [v for v in form.getlist("sibling_id") if v]

        try:
            if extra_ids:
                add_bundled_visit(
                    ctx["prop"].get("client_id"), [pid, *extra_ids], visit_date,
                    amount_usd=amount or None, technician=technician, notes=notes,
                )
            else:
                add_visit(pid, visit_date, amount_usd=amount or None, technician=technician, notes=notes)
        except Exception as exc:
            ctx = detail_ctx(pid)
            return render_template(
                "maintenance/detail.html", pid=pid, error=None,
                action_error=f"Error al registrar visita: {exc}", **ctx,
            )

        return redirect(url_for("maintenance.propiedad", pid=pid), code=303)

    @bp.route("/propiedad/<pid>/override", methods=["POST"])
    def propiedad_override(pid):
        from database.site_properties_db import set_due_override

        try:
            set_due_override(pid, None)
        except Exception as exc:
            ctx = detail_ctx(pid)
            if ctx is None:
                abort(404)
            return render_template(
                "maintenance/detail.html", pid=pid, error=None, action_error=f"Error: {exc}", **ctx,
            )

        return redirect(url_for("maintenance.propiedad", pid=pid), code=303)

    @bp.route("/propiedad/<pid>/sitio", methods=["POST"])
    def propiedad_sitio(pid):
        from database.site_properties_db import link_site_to_property

        form = request.form
        site_id = form.get("site_id")
        schema_name = form.get("schema_name")
        linked = form.get("linked") == "1"

        error = None
        try:
            link_site_to_property(site_id, schema_name, pid if linked else None)
        except Exception as exc:
            error = f"Error al vincular: {exc}" if linked else f"Error al desvincular: {exc}"

        ctx = detail_ctx(pid)
        if ctx is None:
            abort(404)
        return render_template(
            "maintenance/_site_linker.html", pid=pid, linker_groups=ctx["linker_groups"], error=error,
        )

    @bp.route("/propiedad/<pid>/credenciales")
    def propiedad_credenciales(pid):
        from database.site_properties_db import get_credentials

        site_id = request.args.get("site_id")
        schema_name = request.args.get("schema_name")
        cred = get_credentials(site_id, schema_name) or {}
        return render_template(
            "maintenance/_credentials.html", pid=pid, site_id=site_id, schema_name=schema_name,
            credentials=cred.get("credentials") or "", notes=cred.get("notes") or "", error=None,
        )

    @bp.route("/propiedad/<pid>/credenciales", methods=["POST"])
    def propiedad_credenciales_guardar(pid):
        from database.site_properties_db import save_credentials

        form = request.form
        site_id = form.get("site_id")
        schema_name = form.get("schema_name")
        credentials = form.get("credentials", "")
        notes = form.get("notes", "")

        error = None
        try:
            save_credentials(site_id, schema_name, credentials, notes)
        except Exception as exc:
            error = f"Error al guardar: {exc}"

        return render_template(
            "maintenance/_credentials.html", pid=pid, site_id=site_id, schema_name=schema_name,
            credentials=credentials, notes=notes, error=error,
        )
