from __future__ import annotations
"""Técnico tab — the engineering view of a project: the equipment it was designed with, the
system's technical data, the wiring / breaker / PVC-conduit sizing, and a preliminary bill of
materials derived from them.

Everything here is *read from a saved quote version* (`draft.load()` works on locked versions
too) — nothing is recomputed from the scenario engine. The project only owns a few small things,
stored in `projects.tech_spec` (migration 052):

    version_id       which version of the project's proposal the tab reads (default: the latest
                     locked one, else the latest) — the promoted version can be a stale design
    wiring_lengths   cable run lengths measured on site, which refine the sizing
    wiring_manual    the engineer's own breaker / gauge per branch, judged against the calculated one
    coupling         PV coupling of a hybrid design (DC controllers or AC-coupled PV inverter),
                     see webapp/wizard_steps/og_coupling.py
    disconnect       optional disconnect load center next to the Fronius, see webapp/wizard_steps/disconnect_center.py

The wiring maths is `calculations/wiring.py` (NEC tables from the CCC+FV workbook); the BOM
assembly is `calculations/bom.py`. Wiring is available for Off-Grid / Hybrid designs; Grid Zero
shows equipment and technical data only.
"""
from flask import render_template, request, url_for

# Quote lines that are equipment (shown in "Equipos elegidos"), so the "other quote lines"
# list below doesn't repeat them.
_EQUIPMENT_LINES = {
    "Paneles solares", "Inversor/cargador", "Inversores", "Baterías", "Controlador de carga",
    "Monitoreo", "Sistema de monitoreo remoto",
}


def _facts(blob: dict, project: dict) -> list[tuple[str, str]]:
    eq = blob.get("equipment") or {}
    panel, inv = eq.get("panel") or {}, eq.get("inverter") or {}
    arr = eq.get("array") or {}
    site, cons = blob.get("site") or {}, blob.get("consumption") or {}
    n_series, n_strings = int(eq.get("panels_per_string") or 0), int(eq.get("n_strings") or 0)
    facts: list[tuple[str, str]] = []
    if site.get("city"):
        facts.append(("Sitio", f"{site.get('city')}, {site.get('province') or ''}".strip(", ")))
    if arr.get("array_kw"):
        facts.append(("Arreglo FV", f"{arr['array_kw']} kW · {arr.get('panel_count')} paneles"))
    if n_series and n_strings:
        voc, vmp = float(panel.get("voc") or 0) * n_series, float(panel.get("vmp") or 0) * n_series
        facts.append(("Configuración", f"{n_strings} strings × {n_series} en serie · Voc {voc:.0f} V · Vmp {vmp:.0f} V"))
    if arr.get("area_m2"):
        facts.append(("Área de techo", f"{arr['area_m2']} m²"))
    if arr.get("daily_generation_kwh"):
        facts.append(("Generación estimada", f"{arr['daily_generation_kwh']} kWh/día"))
    bank = eq.get("battery_bank") or {}
    if bank.get("total_kwh_installed"):
        facts.append(("Banco de baterías", f"{bank['total_kwh_installed']} kWh · {bank.get('battery_count')} unidades"))
    if inv.get("kw"):
        facts.append(("Inversores", f"{int(eq.get('inverter_qty') or 1)} × {inv['kw']} kW = {float(inv['kw']) * int(eq.get('inverter_qty') or 1):.1f} kW"))
    if cons.get("daily_kwh"):
        div = cons.get("daily_kwh_diversified")
        facts.append(("Consumo de diseño", f"{cons['daily_kwh']} kWh/día" + (f" ({div} diversificado)" if div else "")))
    if cons.get("voltage_v"):
        facts.append(("Tensión CA", f"{int(float(cons['voltage_v']))} V" + (" · conectado a la red" if cons.get("grid_connected") else " · aislado")))
    return facts


def render_panel(ctx: dict, *, message: str | None = None) -> str:
    from calculations.bom import build_bom
    from webapp.blueprints import projects_design
    from webapp.blueprints.projects_common import fmt_usd

    project = ctx["project"]
    d = projects_design.load(project)
    spec, versions, chosen, blob, eq = d["spec"], d["versions"], d["chosen"], d["blob"], d["eq"]
    if d["empty"]:
        extra = {"versions": versions, "chosen": chosen} if chosen and not eq.get("panel") else {}
        return render_template("projects/_tecnico.html", pid=project["id"], empty=d["empty"], **extra)

    system_type = project.get("system_type")
    wiring_ctx = d["wiring"]
    wiring_ctx.update(post_url=url_for("projects.tecnico_guardar", pid=project["id"]),
                      form_target="#tech-panel", form_swap="outerHTML", manual_enabled=True)

    other_lines = [
        {"item": it.get("item"), "qty": it.get("qty"), "specs": it.get("specs") or ""}
        for it in ((blob.get("costs") or {}).get("line_items") or [])
        if it.get("item") and it.get("item") not in _EQUIPMENT_LINES
    ]
    version_options = [{
        "id": v["id"],
        "label": f"v{v['version_number']} · {fmt_usd(v.get('total_usd'))} · {'bloqueada' if v.get('locked') else 'borrador'}"
                 + (" · versión promovida" if v["id"] == project.get("version_id") else ""),
    } for v in versions]

    return render_template(
        "projects/_tecnico.html", pid=project["id"], empty=None, message=message,
        versions=version_options, chosen=chosen, chosen_total=fmt_usd(chosen.get("total_usd")),
        facts=_facts(blob, project), bom=build_bom(eq, wiring_ctx), wiring=wiring_ctx,
        other_lines=other_lines, system_type=system_type,
        custom_lengths=bool(spec.get("wiring_lengths")),
    )


def register(bp):
    @bp.route("/<pid>/tecnico", methods=["POST"])
    def tecnico_guardar(pid):
        """Saves the tab's two settings (design version, cable lengths) and re-renders the
        whole panel so the wiring table and the BOM can never disagree."""
        from database.projects_db import get_project, update_tech_spec
        from webapp.blueprints.projects_common import detail_ctx
        from webapp.wizard_steps import disconnect_center, og_coupling, og_wiring

        project = get_project(pid)
        if not project:
            return render_template("admin/_error.html", message="Proyecto no encontrado.")
        spec = dict(project.get("tech_spec") or {})
        form = request.form
        if form.get("version_id"):
            spec["version_id"] = form["version_id"]
        if any(k in form for k in og_wiring.DEFAULT_LENGTHS):
            spec["wiring_lengths"] = og_wiring.lengths_from_form(form, spec.get("wiring_lengths"))
        if form.get("manual_form"):
            spec["wiring_manual"] = og_wiring.manual_from_form(form)
        cpl = og_coupling.from_form(form)
        if cpl is not None:
            spec["coupling"] = cpl
        disc = disconnect_center.from_form(form)
        if disc is not None:
            spec["disconnect"] = disc
        update_tech_spec(pid, spec)
        return render_panel(detail_ctx(pid, active_tab="tecnico"))
