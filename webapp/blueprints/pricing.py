"""Proforma import: upload a supplier proforma PDF, review what was parsed, and
update stored catalog prices / service rates (with "last updated" provenance).

Reachable from Admin (Equipos / Servicios) and from the quote wizard's Costos
step (`?vid=<version id>` carries the draft so the screen can pre-fill the
project kWp and send the user back to the quote). Nothing is written until the
user presses "Aplicar" on the review screen.
"""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

bp = Blueprint("pricing", __name__, url_prefix="/proformas")


def _draft_kwp(vid: str | None) -> float | None:
    """Quoted kWp of the draft this import was opened from (Costos step)."""
    if not vid:
        return None
    try:
        from pricing.service_rates import kwp_from_blob
        from wizard import draft

        return kwp_from_blob(draft.load(vid)) or None
    except Exception:
        return None


def _page(**ctx):
    vid = ctx.get("vid")
    back_url = None
    if vid:
        from webapp.blueprints.wizard import STEP_COSTOS

        back_url = url_for("wizard.paso", vid=vid, n=STEP_COSTOS)
    return render_template("pricing/importar.html", back_url=back_url, **ctx)


@bp.route("/importar")
def importar():
    vid = request.args.get("vid") or None
    return _page(vid=vid, stage="upload")


@bp.route("/importar/leer", methods=["POST"])
def leer():
    from pricing.apply import load_catalog, load_services, stage_pdf, target_options
    from pricing.matching import suggest
    from pricing.proforma_parser import parse_proforma

    vid = request.form.get("vid") or None
    f = request.files.get("pdf")
    if not f or not f.filename:
        return _page(vid=vid, stage="upload", error="Selecciona un archivo PDF.")
    pdf_bytes = f.read()
    if not pdf_bytes.startswith(b"%PDF"):
        return _page(vid=vid, stage="upload", error="El archivo no parece ser un PDF.")
    try:
        parsed = parse_proforma(pdf_bytes)
    except Exception as exc:  # corrupt/encrypted PDFs
        return _page(vid=vid, stage="upload", error=f"No se pudo leer el PDF: {exc}")

    catalog = load_catalog()
    by_id = {f"{t}:{r['id']}": r for t, rows in catalog.items() for r in rows}
    rows = []
    for i, line in enumerate(parsed["lines"]):
        target, conf = suggest(line["description"], catalog)
        cur = by_id.get(target)
        rows.append({**line, "i": i, "target": target, "confidence": conf,
                     "cur_cost": (cur or {}).get("cost_usd"),
                     "cur_date": ((cur or {}).get("price_updated_at") or "")[:10]})
    storage_path = stage_pdf(pdf_bytes, f.filename, parsed.get("doc_date"))

    # kWp for the per-Wp structure rate: the draft's, else this proforma's panels.
    kwp = _draft_kwp(vid)
    if not kwp:
        wp_by = {f"panels:{r['id']}": float(r.get("wp") or 0) for r in catalog["panels"]}
        kwp = sum((r["qty"] or 0) * wp_by.get(r["target"], 0) for r in rows) / 1000.0 or None

    totals = parsed["totals"]
    disc_pct = None
    if totals.get("subtotal") and totals.get("descuento"):
        disc_pct = round(totals["descuento"] / totals["subtotal"] * 100, 2)
    catalog_prices = {k: {"cost": r.get("cost_usd"), "date": (r.get("price_updated_at") or "")[:10]}
                      for k, r in by_id.items()}
    return _page(vid=vid, stage="review", parsed=parsed, rows=rows, kwp=kwp, disc_pct=disc_pct,
                 options=target_options(catalog), filename=f.filename, storage_path=storage_path or "",
                 catalog_prices=catalog_prices, services=load_services())


@bp.route("/importar/aplicar", methods=["POST"])
def aplicar():
    from pricing.apply import apply_import

    form = request.form
    vid = form.get("vid") or None
    n = int(form.get("n_lines") or 0)

    def num(v, default=None):
        try:
            return float(str(v).replace(",", "")) if str(v).strip() != "" else default
        except ValueError:
            return default

    lines = []
    for i in range(n):
        qty = num(form.get(f"qty_{i}"), 0.0)
        unit = num(form.get(f"unit_{i}"), 0.0)
        iva = form.get(f"iva_{i}")
        lines.append({
            "description": form.get(f"desc_{i}", ""), "qty": qty, "unit_usd": unit,
            "total_usd": round(qty * unit, 2),
            "iva_rate": 0.13 if iva == "13" else 0.0,
            "target": form.get(f"target_{i}", "skip"),
        })
    totals = {"subtotal": num(form.get("subtotal")), "descuento": num(form.get("descuento"))}
    result = apply_import(
        supplier=(form.get("supplier") or "").strip(), doc_number=(form.get("doc_number") or "").strip(),
        doc_date=(form.get("doc_date") or "").strip() or None, filename=form.get("filename", ""),
        storage_path=form.get("storage_path") or None, lines=lines, kwp=num(form.get("kwp")),
        apply_discount=form.get("apply_discount") == "on", totals=totals,
    )
    return _page(vid=vid, stage="done", result=result)


@bp.route("/importar/refrescar", methods=["POST"])
def refrescar():
    """After an import opened from a quote: refresh that quote's Costos prices
    (same effect as the "Refrescar precios" button) and go back to the step."""
    from webapp.blueprints.wizard import STEP_COSTOS
    from webapp.wizard_steps import gz_s7_costs, og_s7_costs
    from wizard import draft

    vid = request.form.get("vid")
    if not vid:
        return redirect(url_for("admin.index"))
    blob = draft.load(vid)
    st = (blob.get("meta") or {}).get("system_type") or "off_grid"
    module = gz_s7_costs if st == "grid_zero" else og_s7_costs
    new_costs, _n = module.refresh_prices(blob)
    draft.patch(vid, "costs", new_costs)
    return redirect(url_for("wizard.paso", vid=vid, n=STEP_COSTOS))
