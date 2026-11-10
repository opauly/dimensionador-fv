"""One answer at Equipos to "do the goals from Objetivos hold up for this design?" (Off-Grid / Hybrid). Pure glue: it does not
compute anything new, it combines what the page already has — the goals-vs-design table (`goals_check`), the real-data
simulation (`sim_check`) and the roof fit (`roof_fit`) — into one verdict, and looks up the fleet's median for the
same rows so the table can show formula and real fleet side by side. Informational only; never blocks Equipos."""
from __future__ import annotations

from webapp.wizard_steps import s6_objetivos

_WORST = {"ok": 0, "justo": 1, "sobre": 1, "bajo": 2}


def fleet_medians(blob: dict) -> dict | None:
    """{row key: "17.9 kWp"} for the healthy-fleet median of panels / battery / inverter for a load like this one (cached 6 h by
    `fleet_reference`). None when the fleet gives no suggestion."""
    try:
        from calculations import fleet_reference as fr

        sp = s6_objetivos.sweet_spot(blob)
        if sp is None or sp["system_type"] not in ("off_grid", "hybrid"):
            return None
        inputs = sp["inputs"]
        daily = inputs["daily_kwh"] if sp["system_type"] == "off_grid" else inputs["critical_daily_kwh"]
        if not daily or daily <= 0:
            return None
        ref = fr.reference_class(fr.load_fleet(), system_type=sp["system_type"], daily_kwh=float(daily))
        sg = ref.get("suggestion")
        if not sg:
            return None
        out = {"pv": f"{sg['kwp']['median']:,.1f} kWp", "battery": f"{sg['battery_nominal_kwh']['median']:,.1f} kWh"}
        inv = ref.get("inverter") or {}
        if inv.get("fit"):
            out["inverter"] = f"{inv['inverter_kw']['median']:,.1f} kW"
        return out
    except Exception:                                   # noqa: BLE001 — informational, never break Equipos
        return None


def _row(label, design, goal, status, *, source, key="", band="—", note="", status_label=None):
    from calculations import goals_check as gc

    return {"key": key, "label": label, "achieved": design, "target": goal, "band": band, "status": status,
            "status_label": status_label or gc.STATUS_LABELS[status], "note": note, "source": source}


def _sim_rows(sc: dict) -> list[dict]:
    src = "Simulación"
    if sc.get("pending"):
        return [_row("Simulación con clima y consumos reales", "preparando…", "—", "info", source=src,
                     note="La primera vez tarda cerca de un minuto; recarga en un momento.")]
    ok = lambda good: "ok" if good else "bajo"          # noqa: E731
    if sc["kind"] == "off_grid":
        rows = [_row("Días con apagón (clima real)", f"{sc['fail_pct']:.1f} %", f"≤ {sc['fail_target']:.0f} %", ok(sc["fail_pct"] <= sc["fail_target"]), source=src,
                     note=f"{sc['scenarios']} escenarios con clima y consumos reales."),
                _row("Apagón más largo (clima real)", f"{sc['streak']:.0f} día(s)", f"≤ {sc['streak_target']:.0f} día(s)", ok(sc["streak"] <= sc["streak_target"]), source=src)]
        if sc.get("battery_min"):
            rows.append(_row("Batería mínima que cumple", f"{sc['battery']:.0f} kWh instalada", f"≥ {sc['battery_min']:.0f} kWh", "info", source=src,
                             note=f"Sin tocar el margen de {sc['reserve_pct']:.0f} % harían falta {sc['battery_min_reserve']:.0f} kWh." if sc.get("battery_min_reserve") else ""))
        return rows
    rows = [_row("Noches cubiertas", f"{sc['nights_ok_pct']:.0f} %", f"≥ {sc['night_target']:.0f} %", ok(sc["nights_ok_pct"] >= sc["night_target"]), source=src,
                 note=f"{sc['scenarios']} escenarios con clima y consumos reales.")]
    if sc.get("outage_cover_pct") is not None:
        rows.append(_row("Cortes de red que aguanta", f"{sc['outage_cover_pct']:.0f} %", f"≥ {sc['outage_target']:.0f} %", ok(sc["outage_cover_pct"] >= sc["outage_target"]), source=src))
    rows.append(_row("Carga que sigues comprando a la red", f"{sc['import_pct']:.0f} %", "—", "info", source=src,
                     note=f"Real típico ≈ {sc['import_pct_adj']:.0f} %." if sc.get("import_pct_adj") is not None else ""))
    return rows


def build(blob: dict, goals_check: dict | None, sim_check: dict | None, roof_fit: dict | None) -> dict | None:
    """One table (goal rows + roof + real-data simulation, each tagged with where it comes from) and an overall verdict.
    None when there is no goals table to judge (nothing to combine)."""
    from calculations import goals_check as gc

    if not goals_check:
        return None
    fleet = fleet_medians(blob)
    rows = [{**r, "source": "Metas"} for r in goals_check["rows"] if r["status"] != "info"]
    if roof_fit:
        fits = roof_fit["extra"] <= 0
        rows.append(_row("Paneles que caben en el techo", f"{roof_fit['fit']} de {roof_fit['panels']}", f"{roof_fit['panels']} (todos)",
                         "ok" if fits else "justo", source="Techo", band=f"~{roof_fit['roof_area_m2']:.0f} m²",
                         status_label=None if fits else "Espacio extra",
                         note="" if fits else f"Los {roof_fit['extra']} restantes ({roof_fit['extra_kwp']:.1f} kWp) necesitan ~{roof_fit['extra_area_m2']:.0f} m² más."))
    hint = None
    if sim_check:
        rows += [r for r in _sim_rows(sim_check) if r["status"] != "info" or sim_check.get("pending")]
        if sim_check.get("kind") == "off_grid" and sim_check.get("battery_min"):
            hint = f"Con clima y consumos reales, la batería mínima que cumple es {sim_check['battery_min']:.0f} kWh (tienes {sim_check['battery']:.0f})."
    summary = gc.summarize(rows)
    level = {"ok": 0, "justo": 1, "sobre": 1, "bajo": 2}[summary["overall"]]
    overall = ("ok", "justo", "bajo")[level]
    headline = {"ok": "Se cumplen tus metas con este diseño.", "justo": "Se cumplen con reservas.",
                "bajo": "No se cumplen todas las metas con este diseño."}[overall]
    return {"overall": overall, "headline": headline, "summary": summary["text"], "rows": rows, "hint": hint, "fleet": fleet,
            "sim_pending": bool(sim_check and sim_check.get("pending"))}
