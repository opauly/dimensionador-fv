"""Service defaults CRUD (pages/05_admin.py's _services_section/_service_form)."""
from __future__ import annotations

from flask import redirect, render_template, request, url_for

SYSTEM_TYPE_LABELS = [("grid_zero", "Grid Zero"), ("off_grid", "Off-Grid"), ("hybrid", "Híbrido")]
IVA_OPTIONS = [(0.0, "0%"), (0.13, "13%")]


def _bool(form, key):
    return form.get(key) == "on"


def _payload_from_form(form):
    chosen = [key for key, _ in SYSTEM_TYPE_LABELS if _bool(form, f"stype_{key}")]
    system_types = None if len(chosen) == len(SYSTEM_TYPE_LABELS) else (chosen or None)
    return {
        "item": form.get("item", "").strip(),
        "item_en": form.get("item_en", "").strip(),
        "unit_cost_usd": float(form.get("unit_cost_usd") or 0),
        "iva_pct": float(form.get("iva_pct") or 0),
        "enabled": _bool(form, "enabled"),
        "specs": form.get("specs", "").strip(),
        "specs_en": form.get("specs_en", "").strip(),
        "sort_order": int(float(form.get("sort_order") or 0)),
        "system_types": system_types,
        # Phase 23: whether this line gets marked up by the quote's overall
        # margin (PLAN_PHASE23_PROFIT_DISTRIBUTION.md §1.1/§1.2) — off only
        # for Permiso de Interconexión today.
        "markup_eligible": _bool(form, "markup_eligible"),
    }, chosen


def render_services_panel(request):
    from database.equipment_db import list_service_defaults

    add = request.args.get("add") == "1"
    edit_id = request.args.get("edit")
    rows = list_service_defaults()
    existing = next((r for r in rows if r["id"] == edit_id), None) if edit_id else None
    form_mode = "add" if add else ("edit" if existing else None)
    return _render(rows, form_mode, existing, error=None)


def _render(rows, form_mode, existing, error):
    src = existing or {}
    src_types = src.get("system_types")
    checked = {key: (src_types is None or key in (src_types or [])) for key, _ in SYSTEM_TYPE_LABELS}
    return render_template(
        "admin/_services_panel.html", rows=rows, form_mode=form_mode, existing=src,
        system_types=SYSTEM_TYPE_LABELS, checked=checked, iva_options=IVA_OPTIONS, error=error,
    )


def register(bp):
    @bp.route("/servicios/save", methods=["POST"])
    def services_save():
        from database.equipment_db import list_service_defaults, upsert_service_default

        form = request.form
        edit_id = form.get("id") or None
        payload, chosen = _payload_from_form(form)

        if not payload["item"]:
            return _render(list_service_defaults(), "edit" if edit_id else "add",
                            {**payload, "id": edit_id}, error="El nombre es obligatorio.")
        if not chosen:
            return _render(list_service_defaults(), "edit" if edit_id else "add",
                            {**payload, "id": edit_id},
                            error="Selecciona al menos un tipo de sistema — para quitar el servicio de "
                                  "todas las propuestas nuevas, usa 'Habilitado' en vez de esto.")

        if edit_id:
            payload["id"] = edit_id
        upsert_service_default(payload)
        return redirect(url_for("admin.index", section="servicios"))

    @bp.route("/servicios/<item_id>/delete", methods=["POST"])
    def services_delete(item_id):
        from database.equipment_db import delete_service_default

        delete_service_default(item_id)
        return redirect(url_for("admin.index", section="servicios"))

    @bp.route("/servicios/batch-save", methods=["POST"])
    def services_batch_save():
        """Inline price/IVA/enabled edits from the list rows (no add/edit form open)."""
        from database.equipment_db import list_service_defaults, upsert_service_default

        form = request.form
        rows = list_service_defaults()
        for r in rows:
            # A row's price field is a text input, always present in a real
            # full-page submission — its absence means this row wasn't part
            # of the submitted form at all (e.g. a partial/malformed POST),
            # so skip it rather than defaulting price/IVA to 0 and enabled
            # to False, which would silently wipe data outside what was
            # actually being edited.
            if f"price_{r['id']}" not in form:
                continue
            new_price = float(form.get(f"price_{r['id']}") or 0)
            new_iva = float(form.get(f"iva_{r['id']}") or 0)
            new_enabled = _bool(form, f"enabled_{r['id']}")
            new_markup = _bool(form, f"markup_{r['id']}")
            old_price = float(r.get("unit_cost_usd") or 0)
            old_iva = float(r.get("iva_pct") or 0)
            old_enabled = bool(r.get("enabled", True))
            old_markup = bool(r.get("markup_eligible", True))
            if (abs(new_price - old_price) > 0.001 or abs(new_iva - old_iva) > 0.001
                    or new_enabled != old_enabled or new_markup != old_markup):
                upsert_service_default({
                    "id": r["id"], "item": r["item"],
                    "unit_cost_usd": new_price, "iva_pct": new_iva, "enabled": new_enabled,
                    "markup_eligible": new_markup,
                })
        return redirect(url_for("admin.index", section="servicios"))
