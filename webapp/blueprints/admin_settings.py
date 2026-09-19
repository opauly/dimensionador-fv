"""Ajustes: company + bank info forms, and logo/signature asset upload
(pages/05_admin.py's _settings_company_form / _settings_bank_form /
_settings_assets_section)."""
from __future__ import annotations

from flask import abort, redirect, render_template, request, url_for

ASSET_KINDS = [
    ("logo",            "Logo"),
    ("signature",       "Firma (fondo claro)"),
    ("signature_white", "Firma (fondo oscuro)"),
    ("isotipo_white",   "Isotipo (fondo oscuro)"),
]


def render_settings_panel():
    from wizard.state import get_asset_b64, get_bank_info, get_company_info

    assets = [
        {"kind": kind, "label": label, "preview_b64": get_asset_b64(kind)}
        for kind, label in ASSET_KINDS
    ]
    return render_template(
        "admin/_ajustes.html", company=get_company_info(), bank=get_bank_info(),
        assets=assets, error=None,
    )


def register(bp):
    @bp.route("/ajustes/company/save", methods=["POST"])
    def settings_company_save():
        from wizard.state import get_bank_info, get_company_info, save_company_info

        form = request.form
        save_company_info({
            "name": form.get("name", "").strip(),
            "license": form.get("license", "").strip(),
            "contact_name": form.get("contact_name", "").strip(),
            "contact_title": form.get("contact_title", "").strip(),
            "phone": form.get("phone", "").strip(),
            "email": form.get("email", "").strip(),
            "website": form.get("website", "").strip(),
            "contact_title_en": form.get("contact_title_en", "").strip(),
        })
        return redirect(url_for("admin.index", section="ajustes"))

    @bp.route("/ajustes/bank/save", methods=["POST"])
    def settings_bank_save():
        from wizard.state import save_company_info

        def _lines(key):
            return [ln.strip() for ln in request.form.get(key, "").splitlines() if ln.strip()]

        save_company_info({
            "bank_local_lines": _lines("bank_local_lines"),
            "bank_intl_lines": _lines("bank_intl_lines"),
            "bank_local_lines_en": _lines("bank_local_lines_en"),
            "bank_intl_lines_en": _lines("bank_intl_lines_en"),
        })
        return redirect(url_for("admin.index", section="ajustes"))

    @bp.route("/ajustes/assets/<kind>/save", methods=["POST"])
    def settings_asset_save(kind):
        from wizard.state import save_asset

        if kind not in dict(ASSET_KINDS):
            abort(404)

        uploaded = request.files.get("file")
        if uploaded and uploaded.filename:
            save_asset(kind, uploaded.read())
        return redirect(url_for("admin.index", section="ajustes"))
