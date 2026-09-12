"""Clients CRUD + site linker (pages/05_admin.py's _clients_section /
_client_form / _client_delete_control / _client_sites_linker)."""
from __future__ import annotations

from flask import redirect, render_template, request, url_for


def _combined_sites(client_id):
    from database.monitoring_sites_db import list_monitoring_sites
    from database.vrm_sites_db import list_vrm_sites_for_linking

    combined = [
        {"site_id": s["site_id"], "display_name": s.get("display_name") or s["site_id"],
         "brand": s.get("brand") or "Victron Energy", "linked": s.get("client_id") == client_id,
         "kind": "monitoring"}
        for s in list_monitoring_sites()
    ] + [
        {"site_id": s["site_id"], "display_name": s.get("display_name") or s["site_id"],
         "brand": "Victron Energy", "linked": s.get("public_client_id") == client_id,
         "kind": "vrm"}
        for s in list_vrm_sites_for_linking()
    ]
    combined.sort(key=lambda s: s["display_name"])
    return combined


def render_clients_panel(request):
    from database.clients_db import list_all_clients

    add = request.args.get("add") == "1"
    edit_id = request.args.get("edit")
    rows = list_all_clients()
    existing = next((r for r in rows if r["id"] == edit_id), None) if edit_id else None
    form_mode = "add" if add else ("edit" if existing else None)
    return _render(rows, form_mode, existing, error=None)


def _render(rows, form_mode, existing, error):
    sites = _combined_sites(existing["id"]) if (form_mode == "edit" and existing) else None
    return render_template(
        "admin/_clients_panel.html", rows=rows, form_mode=form_mode,
        existing=existing or {}, error=error, sites=sites,
    )


def register(bp):
    @bp.route("/clientes/save", methods=["POST"])
    def clients_save():
        from database.clients_db import list_all_clients, update_client, upsert_client

        form = request.form
        edit_id = form.get("id") or None
        name = form.get("name", "").strip()
        empresa = form.get("empresa", "").strip()
        phone = form.get("phone", "").strip()
        email = form.get("email", "").strip()
        notes = form.get("notes", "").strip()

        if not name:
            existing = {**form.to_dict(), "id": edit_id}
            return _render(list_all_clients(), "edit" if edit_id else "add", existing,
                           error="El nombre es obligatorio.")

        if edit_id:
            update_client(client_id=edit_id, name=name, empresa=empresa, phone=phone, email=email, notes=notes)
        else:
            upsert_client(name=name, empresa=empresa, phone=phone, email=email, notes=notes)
        return redirect(url_for("admin.sub_view", section="clientes", sub="clientes"))

    @bp.route("/clientes/<client_id>/delete", methods=["POST"])
    def clients_delete(client_id):
        from database.clients_db import list_all_clients
        from database.supabase_client import get_client

        try:
            get_client().table("clients").delete().eq("id", client_id).execute()
        except Exception as exc:
            rows = list_all_clients()
            existing = next((r for r in rows if r["id"] == client_id), None)
            return _render(rows, "edit", existing,
                           error=f"No se pudo eliminar (¿tiene propuestas asociadas?): {exc}")
        return redirect(url_for("admin.sub_view", section="clientes", sub="clientes"))

    @bp.route("/clientes/<client_id>/link-site", methods=["POST"])
    def clients_link_site(client_id):
        from database.monitoring_sites_db import set_site_client
        from database.vrm_sites_db import set_site_public_client

        form = request.form
        site_id = form.get("site_id")
        kind = form.get("kind")
        linked = form.get("linked") == "1"
        new_client_id = client_id if linked else None
        if kind == "vrm":
            set_site_public_client(site_id, new_client_id)
        else:
            set_site_client(site_id, new_client_id)

        from database.clients_db import list_all_clients
        rows = list_all_clients()
        existing = next((r for r in rows if r["id"] == client_id), None)
        return _render(rows, "edit", existing, error=None)
