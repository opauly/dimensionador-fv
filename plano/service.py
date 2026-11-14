"""Glue for the Plano de taller tab: the saved answers, the wall spec, the layout and the PDF data of one project."""
from __future__ import annotations

from datetime import date

from plano import design, layout as L

SYSTEM_TEXT = {"hybrid": "Sistema híbrido", "off_grid": "Sistema aislado (off-grid)", "grid_zero": "Sistema Grid Zero"}


def clean_answers(saved: dict | None) -> dict:
    """{'wall_w_m', 'wall_h_m', 'margin_mm'}: the proposed wall in metres (None = not entered yet) and the margin around the equipment."""
    saved = saved or {}

    def num(v, lo, hi):
        try:
            x = float(str(v).replace(",", "."))
            return x if lo <= x <= hi else None
        except (TypeError, ValueError):
            return None

    return {"wall_w_m": num(saved.get("wall_w_m"), 0.3, 30), "wall_h_m": num(saved.get("wall_h_m"), 0.3, 10),
            "margin_mm": num(saved.get("margin_mm"), 0, 500) if saved.get("margin_mm") not in (None, "") else L.MARGIN}


def answers_from_form(form) -> dict:
    return clean_answers({"wall_w_m": form.get("wall_w_m"), "wall_h_m": form.get("wall_h_m"), "margin_mm": form.get("margin_mm")})


def all_parts(spec: L.Spec) -> list[L.Part]:
    order = [spec.victron, spec.fronius, spec.controllers, spec.gabinete, spec.chint, *spec.centers, spec.lynx, spec.fidus, spec.rack]
    return [p for p in order if p]


def compute(project: dict, d: dict, lines: list[dict], answers: dict, *, spec: L.Spec | None = None) -> dict:
    """Everything the tab and the PDF show: the spec, the chosen arrangement, the check against the wall and the notes."""
    spec = spec or design.build_spec(project, d, lines)
    margin = float(answers.get("margin_mm") if answers.get("margin_mm") is not None else L.MARGIN)
    wall_w = answers["wall_w_m"] * 1000 if answers.get("wall_w_m") else None
    wall_h = answers["wall_h_m"] * 1000 if answers.get("wall_h_m") else None
    lay, chk, tried = L.choose(spec, wall_w, wall_h, margin)
    parts = all_parts(spec)
    notes = list(lay.notes)
    if lay.mode == "double":
        notes.append("Los Victron van en dos filas porque en una sola no cabían en el ancho de la pared.")
    elif len(tried) > 1 and chk["fits"] is False:
        notes.append("Ni con los Victron en dos filas cabe: hace falta una pared más grande.")
    missing = [p.label for p in parts if p.missing]
    if missing:
        notes.append("Falta la ficha (medidas) de: " + ", ".join(missing) + ". Se dibuja un cuadro de relleno; el resultado no es confiable hasta cargarla.")
    notes.append("Línea punteada = medida estimada o nominal (gabinete 50x40x20, alto de la caja Chint, centros de carga y mueble de baterías).")
    notes.append(f"Separaciones usadas (por afinar con las fichas): entre inversores {L.GAP_INVERTERS} mm, entre bloques {L.GAP_BLOCKS} mm, "
                 f"inversores a ducto {L.GAP_TO_DUCT} mm, ducto a baterías {L.GAP_DUCT_ROW2} mm, baterías al piso {L.FLOOR_GAP} mm.")
    notes.append("No incluye la base de medidor, el tablero principal ni el sub-panel, y tampoco el espacio libre de trabajo frente a los equipos.")
    n_v = spec.victron.qty if spec.victron else 0
    arrangement = ("Acomodo: Victron en dos filas" if lay.mode == "double" else "Acomodo: una fila de equipos arriba, ducto 4x4 debajo, baterías y Lynx abajo")
    title = f"{SYSTEM_TEXT.get(spec.system, 'Sistema')} · " + " + ".join(
        f"{p.qty} × {p.label}" for p in (spec.victron, spec.fronius, spec.controllers, spec.fidus, spec.rack) if p)
    return {"spec": spec, "layout": lay, "check": chk, "parts": parts, "notes": notes, "margin": margin, "title": title,
            "arrangement": arrangement, "wall": (wall_w, wall_h) if (wall_w and wall_h) else None, "n_victron": n_v}


def pdf_data(project: dict, d: dict, comp: dict) -> dict:
    site = d["blob"].get("site") or {}
    place = ", ".join(x for x in (site.get("city"), site.get("province")) if x)
    client = project.get("client_name") or "Cliente"
    return {
        "project": {"name": f"Proyecto {client}" + (f" en {place}" if place else ""), "client": client,
                    "location": (place + ", Costa Rica") if place else "Costa Rica", "date": date.today().isoformat(),
                    "revision": "A (borrador)", "draft": True, "responsible": "Ing. Oscar Pauly Calvo · IE-30111"},
        "title": comp["title"], "layout": comp["layout"], "check": comp["check"], "parts": comp["parts"], "margin": comp["margin"],
        "wall": comp["wall"], "notes": comp["notes"], "arrangement": comp["arrangement"],
    }
