from __future__ import annotations
"""Quote-vs-final price adjustment — set or change a project's quoted-price
baseline and the reason the final price differs.

The negotiated final price is `projects.contract_usd` (what payments and profit
already use); the quote lines and versions are never edited to absorb a
discount. This route only records the baseline (`quoted_usd`) and the reason —
the discount and its percentage are derived by
`projects_common.price_adjustment_info()`, never stored.
"""
from flask import abort, redirect, request


def register(bp):
    @bp.route("/<pid>/ajuste-precio", methods=["POST"])
    def ajuste_precio(pid):
        from database.projects_db import update_price_adjustment
        from webapp.blueprints.projects_common import tab_url

        raw = (request.form.get("quoted_usd") or "").replace(",", "").replace("$", "").strip()
        try:
            quoted = float(raw) if raw else None
        except ValueError:
            abort(400)
        if quoted is not None and quoted < 0:
            abort(400)
        update_price_adjustment(pid, quoted, request.form.get("reason"))
        return redirect(tab_url(pid, request.form.get("tab") or "presupuesto"), code=303)
