from __future__ import annotations
"""Configurar propiedades tab — port of pages/07_maintenance.py:_setup_section()
onto Flask/Jinja2/htmx (Phase 21 Step 3).

This tab's own table (item 16) deliberately does NOT read maintenance_common
.property_rows() — Streamlit's _setup_section() calls list_properties()
directly, not _compute_property_rows(), because this table shows no status
column at all (Propiedad / Cliente / Sitios only). Using list_properties()
here matches Streamlit exactly and isn't a violation of the "one source of
truth" rule, which is about status/next-due-date/visited-flag, none of which
this tab renders.

The merge picker is keyed by property `id`, not `name`, per PLAN §0.4 Q5 — a
disclosed, deliberate bug fix over Streamlit's own name-keyed picker (two
properties auto-created by migration 047 from same-named sites collide there).

Reactive merge selection (item 17) is threaded through the DOM without
nesting a second <form> inside the properties table: the merge-related
inputs (selected_id checkboxes, the confirm-anyway gate checkbox, the
keep-name select) all carry a plain HTML `form="merge-form"` attribute
pointing at one empty <form id="merge-form"> declared once in _setup.html,
so a native submit collects them regardless of where they sit in the DOM —
this leaves the per-row "Eliminar" controls free to use their own ordinary
<form> without ever nesting forms (invalid HTML). The live warning/keep-name
panel refresh (GET .../fusionar/panel) reads the same inputs via
`hx-include="[form='merge-form']"`.
"""
from flask import abort, redirect, render_template, request, url_for


def _client_label(client_id, client_name_by_id) -> str:
    if client_id is None:
        return "—"
    return client_name_by_id.get(client_id, "?")


def _load() -> tuple[list[dict], list[dict], dict]:
    from database.clients_db import list_all_clients
    from database.site_properties_db import list_all_sites_for_maintenance, list_properties

    all_sites = list_all_sites_for_maintenance()
    properties = list_properties()
    client_name_by_id = {c["id"]: c["name"] for c in list_all_clients()}
    return all_sites, properties, client_name_by_id


def _merge_panel_ctx(properties: list[dict], client_name_by_id: dict, selected_ids: list[str],
                      confirm_diff_client: bool, keep_id: str | None) -> dict:
    """Port of _setup_section()'s reactive merge block (item 17)."""
    selected_ids = [sid for sid in selected_ids if sid]
    selected_props = [p for p in properties if p["id"] in selected_ids]
    count = len(selected_props)

    if count < 2:
        return {"count": count, "show_panel": False}

    client_ids = {p.get("client_id") for p in selected_props if p.get("client_id")}
    differs = len(client_ids) > 1
    names = None
    if differs:
        names = ", ".join(
            f"{p['name']} ({client_name_by_id.get(p.get('client_id')) or 'sin cliente'})"
            for p in selected_props
        )

    confirmed_anyway = confirm_diff_client if differs else True

    valid_ids = {p["id"] for p in selected_props}
    if keep_id not in valid_ids:
        keep_id = selected_props[0]["id"]
    keep_label = next(p["name"] for p in selected_props if p["id"] == keep_id)

    return {
        "count": count, "show_panel": True, "selected_props": selected_props,
        "differs": differs, "names": names, "confirm_checked": confirm_diff_client,
        "confirmed_anyway": confirmed_anyway, "keep_id": keep_id, "keep_label": keep_label,
    }


def render_merge_panel(selected_ids: list[str], confirm_diff_client: bool, keep_id: str | None) -> str:
    from database.clients_db import list_all_clients
    from database.site_properties_db import list_properties

    properties = list_properties()
    client_name_by_id = {c["id"]: c["name"] for c in list_all_clients()}
    ctx = _merge_panel_ctx(properties, client_name_by_id, selected_ids, confirm_diff_client, keep_id)
    return render_template("maintenance/_merge_panel.html", **ctx)


def render_setup_panel(
    *, new_name: str = "", new_interval: int = 365, form_error: str | None = None,
    created: str | None = None, seeded: str | None = None, merged: str | None = None,
    keep: str | None = None, error: str | None = None,
    selected_ids: list[str] | None = None, confirm_diff_client: bool = False, keep_id: str | None = None,
) -> str:
    try:
        all_sites, properties, client_name_by_id = _load()
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))

    unlinked = [s for s in all_sites if not s.get("property_id")]

    prop_rows = [
        {
            "id": p["id"], "name": p["name"], "location": p.get("location") or "",
            "client_label": _client_label(p.get("client_id"), client_name_by_id),
            "site_count": p["site_count"],
        }
        for p in properties
    ]

    merge_ctx = _merge_panel_ctx(properties, client_name_by_id, selected_ids or [], confirm_diff_client, keep_id)

    return render_template(
        "maintenance/_setup.html",
        unlinked_count=len(unlinked),
        prop_rows=prop_rows,
        new_name=new_name, new_interval=new_interval, form_error=form_error,
        created=created, seeded=seeded, merged=merged, keep=keep, error=error,
        **merge_ctx,
    )


def register(bp):
    @bp.route("/propiedades", methods=["POST"])
    def propiedades_crear():
        from database.site_properties_db import create_property

        form = request.form
        name = (form.get("name") or "").strip()
        try:
            interval = int(float(form.get("interval") or 365))
        except (TypeError, ValueError):
            interval = 365

        if not name:
            return render_setup_panel(form_error="El nombre es obligatorio.", new_name=name, new_interval=interval)

        try:
            create_property(name=name, interval_days=interval)
        except Exception as exc:
            return render_setup_panel(
                form_error=f"Error al crear propiedad: {exc}", new_name=name, new_interval=interval,
            )

        return redirect(url_for("maintenance.configurar", created=name), code=303)

    @bp.route("/propiedades/sembrar", methods=["POST"])
    def propiedades_sembrar():
        from database.site_properties_db import seed_properties_from_unlinked_sites

        try:
            created_count = seed_properties_from_unlinked_sites()
        except Exception as exc:
            return render_setup_panel(form_error=f"Error al crear propiedades: {exc}")

        return redirect(url_for("maintenance.configurar", seeded=created_count), code=303)

    @bp.route("/propiedades/fusionar/panel")
    def propiedades_fusionar_panel():
        selected_ids = request.args.getlist("selected_id")
        confirm_diff_client = request.args.get("confirm_diff_client") == "1"
        keep_id = request.args.get("keep_id")
        return render_merge_panel(selected_ids, confirm_diff_client, keep_id)

    @bp.route("/propiedades/fusionar", methods=["POST"])
    def propiedades_fusionar():
        from database.clients_db import list_all_clients
        from database.site_properties_db import list_properties, merge_properties

        form = request.form
        selected_ids = [sid for sid in form.getlist("selected_id") if sid]
        confirm_diff_client = form.get("confirm_diff_client") == "1"
        keep_id = form.get("keep_id")

        properties = list_properties()
        client_name_by_id = {c["id"]: c["name"] for c in list_all_clients()}
        selected_props = [p for p in properties if p["id"] in selected_ids]

        if len(selected_props) < 2:
            return render_setup_panel(
                form_error="Marca al menos 2 propiedades arriba para fusionarlas.",
                selected_ids=selected_ids, confirm_diff_client=confirm_diff_client, keep_id=keep_id,
            )

        client_ids = {p.get("client_id") for p in selected_props if p.get("client_id")}
        if len(client_ids) > 1 and not confirm_diff_client:
            # Defensive server-side re-check mirroring the disabled button — a
            # client that bypassed the disabled attribute lands back here, not
            # on a merge.
            return render_setup_panel(
                selected_ids=selected_ids, confirm_diff_client=confirm_diff_client, keep_id=keep_id,
            )

        valid_ids = {p["id"] for p in selected_props}
        if keep_id not in valid_ids:
            keep_id = selected_props[0]["id"]
        keep_label = next(p["name"] for p in selected_props if p["id"] == keep_id)
        other_ids = [pid for pid in selected_ids if pid != keep_id]

        try:
            for other_id in other_ids:
                merge_properties(other_id, keep_id)
        except Exception as exc:
            return render_setup_panel(form_error=f"Error al fusionar: {exc}")

        return redirect(url_for("maintenance.configurar", merged=len(other_ids), keep=keep_label), code=303)

    @bp.route("/propiedades/<pid>/eliminar")
    def propiedades_eliminar_confirmar(pid):
        from database.site_properties_db import get_property

        prop = get_property(pid)
        if prop is None:
            abort(404)
        confirm = request.args.get("cancel") != "1"
        return render_template("maintenance/_delete_confirm.html", pid=pid, name=prop["name"], confirm=confirm, error=None)

    @bp.route("/propiedades/<pid>/eliminar", methods=["POST"])
    def propiedades_eliminar(pid):
        from database.site_properties_db import delete_property, get_property

        try:
            delete_property(pid)
        except Exception as exc:
            prop = get_property(pid)
            name = prop["name"] if prop else pid
            return render_template(
                "maintenance/_delete_confirm.html", pid=pid, name=name, confirm=True,
                error=f"Error al eliminar: {exc}",
            )

        return redirect(url_for("maintenance.configurar"), code=303)
