"""Design -> unifilar config (and the engineering checks that go with it).

Deterministic: the labels on the drawing are the gauges, breakers and colours that
`og_wiring` already sized for the project (the same numbers the materials list uses), so the
diagram and the purchase list cannot disagree. Nothing comes from an LLM.

`build_config()` returns `(cfg, problems)`. `cfg` is the JSON the drawing script
(`unifilar/generate_unifilar.py`, the `unifilar-hibrido-ac` skill) takes; `problems` is split into
- `blockers`: out of the skill's scope or missing answers — the drawing is not generated,
- `warnings`: engineering checks to review. They go to the UI, never inside the PDF
  (the plan must be able to go to the client).
"""
from __future__ import annotations

import re
from datetime import date

from calculations import wiring as W

# Questions the drawing cannot infer and the wizard must never assume (docs/unifilar/CONTEXTO.md §3.4, §7).
EXPORT_CHOICES = (("grid_zero", "Cero inyección (Grid Zero)"), ("inyeccion", "Con inyección a la red"))
LYNX_CHOICES = (("power_in", "Solo Lynx Power In"), ("power_in_distributor", "Lynx Power In + Lynx Distributor"))

DEFAULT_ANSWERS = {
    "export": None, "lynx": None, "spd": True, "spd_label": "SPD SDSA 1175",
    "q4": "circuitos críticos", "loads1": "iluminación, internet, tomacorrientes,", "loads2": "refrigerador, etc.",
    "revision": "A (borrador)", "draft": True,
}

_LATIN = str.maketrans({"→": "-", "−": "-", "≥": ">=", "≤": "<=", "–": "-", "—": "-", "“": '"', "”": '"', "’": "'"})


def latin(s: str) -> str:
    """Helvetica in reportlab has no arrows or minus signs; keep the text drawable."""
    return (s or "").translate(_LATIN)


def clean_answers(saved: dict | None) -> dict:
    a = {**DEFAULT_ANSWERS, **(saved or {})}
    a["export"] = a["export"] if a["export"] in dict(EXPORT_CHOICES) else None
    a["lynx"] = a["lynx"] if a["lynx"] in dict(LYNX_CHOICES) else None
    return a


def answers_from_form(form) -> dict:
    return clean_answers({
        "export": form.get("export"), "lynx": form.get("lynx"), "spd": form.get("spd") == "1",
        "spd_label": (form.get("spd_label") or "").strip() or DEFAULT_ANSWERS["spd_label"],
        "q4": (form.get("q4") or "").strip() or DEFAULT_ANSWERS["q4"],
        "loads1": (form.get("loads1") or "").strip() or DEFAULT_ANSWERS["loads1"],
        "loads2": (form.get("loads2") or "").strip(),
        "revision": (form.get("revision") or "").strip() or DEFAULT_ANSWERS["revision"],
        "draft": form.get("draft") == "1",
    })


def _g(gauge: str) -> str:
    return f"#{gauge} AWG" if W.T.T8_CMILS[gauge] <= W.T.T8_CMILS["4/0"] else f"{gauge} kcmil"


def _branch(branches: list[dict], key: str) -> dict | None:
    return next((b for b in branches if b.get("key") == key), None)


def _egc(b: dict | None) -> str | None:
    return b.get("egc") if b else None


def _model(item: dict) -> str:
    return f"{item.get('brand', '')} {item.get('model', '')}".strip()


KIND_TEXT = {
    "hybrid_ac": "Sistema híbrido acoplado en AC: Fronius en el AC-OUT de dos MultiPlus-II en split-phase, baterías en Lynx Power In y Ekrano GX.",
    "off_grid": "Sistema acoplado en DC (aislado o híbrido): strings, controladores MPPT, baterías en Lynx Power In, Multis y sub-panel de cargas críticas.",
    "grid_zero": "Sistema Grid Zero: strings, centro de carga DC, inversor Fronius, base de medidor de generación con su breaker (interconectada con la base de medición de consumo) y tablero principal; sin baterías ni equipo Victron.",
}


def drawing_kind(project: dict, wiring: dict) -> str | None:
    """Which drawing fits the project: hybrid AC-coupled, DC-coupled (off-grid or hybrid) or Grid Zero."""
    st = project.get("system_type")
    if st == "grid_zero":
        return "grid_zero"
    if st in ("off_grid", "hybrid"):
        return "hybrid_ac" if (wiring.get("coupling") or {}).get("ac") else "off_grid"
    return None


def check_scope(project: dict, eq: dict, wiring: dict, answers: dict) -> list[str]:
    """Reasons the drawing cannot be generated (empty list = go)."""
    out: list[str] = []
    kind = drawing_kind(project, wiring)
    if kind is None:
        return ["No hay un unifilar para este tipo de proyecto."]
    if not wiring.get("ready"):
        out.append("Falta un diseño completo: " + (wiring.get("reason") or "el cableado no se puede dimensionar"))
        return out
    if kind == "grid_zero":
        n = int(eq.get("n_strings") or (eq.get("chosen_scenario") or {}).get("strings") or 0)
        if not 1 <= n <= 4:
            out.append(f"El dibujo admite de 1 a 4 strings; el diseño tiene {n}.")
        return out
    if kind == "off_grid":
        inv, qty = eq.get("inverter") or {}, int(eq.get("inverter_qty") or 1)
        if not 1 <= qty <= 8:
            out.append(f"El dibujo admite de 1 a 8 inversores Victron; este diseño tiene {qty}.")
        n_str, n_cc = int(eq.get("n_strings") or 0), int(eq.get("charge_controller_qty") or 1)
        if not 1 <= n_str <= (4 if n_cc <= 4 else 200):
            out.append(f"El dibujo admite de 1 a 4 strings (más solo con más de 4 controladores); el diseño tiene {n_str}.")
        if n_cc < 1:
            out.append("El diseño no tiene controladores de carga.")
        elif n_cc > 4 and n_str < n_cc:
            out.append(f"Con más de 4 controladores el dibujo necesita al menos un string por controlador; el diseño tiene {n_str} strings y {n_cc} controladores.")
        n_bat = int((eq.get("battery_bank") or {}).get("battery_count") or 0)
        if not 1 <= n_bat <= 24:
            out.append(f"El dibujo admite de 1 a 24 baterías; el diseño tiene {n_bat}.")
        if answers.get("lynx") == "power_in_distributor":
            out.append("El dibujo de acople DC solo cubre Lynx Power In (sin Distributor).")
        if not eq.get("monitoring"):
            out.append("El dibujo incluye un Ekrano GX; el diseño no tiene equipo de monitoreo.")
        return out
    cpl = wiring.get("coupling") or {}
    inv, qty = eq.get("inverter") or {}, int(eq.get("inverter_qty") or 1)
    if qty != 2:
        out.append(f"El dibujo es para 2 MultiPlus-II en split-phase; este diseño tiene {qty}. Un solo Multi o 3+ está fuera de alcance.")
    if float(inv.get("output_v") or 120) >= 200:
        out.append("El dibujo supone Multis de 120 V en split-phase; el inversor del diseño no es de 120 V.")
    if int(cpl.get("qty") or 1) != 1:
        out.append("El dibujo tiene un solo inversor FV.")
    if int(cpl.get("strings") or 0) not in (1, 2):
        out.append(f"El dibujo admite 1 o 2 strings (un MPPT cada uno); el diseño tiene {cpl.get('strings')}.")
    n_bat = int((eq.get("battery_bank") or {}).get("battery_count") or 0)
    dist = answers.get("lynx") == "power_in_distributor"
    if not 1 <= n_bat <= (4 if dist else 24):
        out.append(f"El dibujo admite 1 a {4 if dist else 24} baterías{' con Distributor' if dist else ''}; el diseño tiene {n_bat}.")
    if not eq.get("monitoring"):
        out.append("El dibujo incluye un Ekrano GX; el diseño no tiene equipo de monitoreo.")
    return out


def missing_answers(answers: dict, kind: str = "hybrid_ac") -> list[str]:
    out = []
    if kind == "grid_zero":
        return out
    if not answers.get("export") and kind == "hybrid_ac":
        out.append("Inyección a la red: elige cero inyección o con inyección.")
    if not answers.get("lynx"):
        out.append("Bus DC de baterías: elige solo Lynx Power In o con Lynx Distributor (siempre se pregunta, no se supone).")
    return out


def build_config(project: dict, d: dict, answers: dict, string_breaker_a: int | None = None) -> tuple[dict | None, dict]:
    """(cfg | None, {'blockers': [...], 'warnings': [{'level','text'}]})."""
    eq, wiring, blob = d["eq"], d["wiring"], d["blob"]
    answers = clean_answers(answers)
    kind = drawing_kind(project, wiring)
    blockers = check_scope(project, eq, wiring, answers) + missing_answers(answers, kind or "hybrid_ac")
    if blockers:
        return None, {"blockers": blockers, "warnings": []}
    if kind == "grid_zero":
        return _build_grid_zero(project, d, answers, string_breaker_a)
    if kind == "off_grid":
        return _build_off_grid(project, d, answers, string_breaker_a)

    cpl, branches = wiring["coupling"], wiring["branches"]
    panel, inv, bat, mon = eq["panel"], eq["inverter"], eq["battery"], eq["monitoring"]
    pv_inv = cpl["pv_inverter"]
    pv, fr = _branch(branches, "pv_strings"), _branch(branches, "pv_inv_ac")
    ac_in, ac_out, bat_inv = _branch(branches, "ac_in"), _branch(branches, "ac_out"), _branch(branches, "bat_inv")
    n_bat = int((eq.get("battery_bank") or {}).get("battery_count") or 0)
    site = blob.get("site") or {}
    place = ", ".join(x for x in (site.get("city"), site.get("province")) if x)
    client = project.get("client_name") or "Cliente"
    string_a = string_breaker_a or pv["ocpd_a"]

    def hots(b, neutral=True):
        g, e = b["ugc"], b.get("egc") or b["ugc"]
        return [f"L1 {_g(g)} negro", f"L2 {_g(g)} rojo"] + ([f"N {_g(g)} blanco"] if neutral else []) + [f"T {_g(e)} verde"]

    multi_label = "MULTIPLUS-II " + (re.search(r"48/\d+", inv.get("model", "")) or re.search(r"\d+", inv.get("model", "") + "0"))[0]
    cfg = {
        "kind": "hybrid_ac", "meter": _meter(eq),
        "project": {
            "name": f"Proyecto {client}" + (f" en {place}" if place else ""), "client": client,
            "location": (place + ", Costa Rica") if place else "Costa Rica", "date": date.today().isoformat(),
            "revision": answers["revision"], "draft": bool(answers["draft"]),
        },
        "pv": {
            "strings": int(cpl["strings"]), "modules_per_string": int(cpl["series"]), "module_w": int(panel.get("wp") or 0),
            "module_label": f"{panel.get('brand', '')} {panel.get('wp')} W".strip(),
            "roof_m2": (eq.get("array") or {}).get("area_m2"),
            "string_breaker": f"{string_a} A 2P DC", "dc_wire": f"{_g(pv['ugc'])} SOLAR",
            "ground_wire": f"T {_g(_egc(pv) or pv['ugc'])} verde",
        },
        "fronius": {
            "label": f"{_model(pv_inv)} 240 V", "kw": pv_inv.get("kw"), "ac_breaker": f"2P {fr['ocpd_a']} A",
            "ac_conductors": [x for x in hots(fr, neutral=False)], "ground_wire": f"T {_g(_egc(fr) or fr['ugc'])} verde",
        },
        "multis": {
            "label": multi_label, "model": f"{inv.get('model', '').split('/70')[0]} 120 V",
            "ac_in_breaker": f"2P {ac_in['ocpd_a']} A" if ac_in else "2P por definir",
            "ac_in_conductors": hots(ac_in) if ac_in else ["por definir"],
            "ac_out_conductors": hots(ac_out),
            "dc_pos": f"+ {_g(bat_inv['ugc'])} rojo", "dc_neg": f"- {_g(bat_inv['ugc'])} negro",
            "ground_wire": f"T {_g(_egc(ac_out) or ac_out['ugc'])} verde",
        },
        "battery": {
            "count": n_bat, "label": _model(bat), "short": bat.get("model") or "Batería", "kwh_each": float(bat.get("capacity_kwh") or 0),
            "can_master": "pylontech" in (bat.get("brand") or "").lower(), "lynx": answers["lynx"],
            "lynx_bars": 1 if answers["lynx"] == "power_in_distributor" else max(1, -(-(n_bat + 2) // 4)),
            "cables_note": (["Cables batería a Power In (+ / -):", "juego de cables de la batería"] if "pylontech" in (bat.get("brand") or "").lower()
                            else ["Cables batería a Power In (+ / -):", "por definir"]),
        },
        "gx": {"label": (mon.get("model") or "GX").upper()},
        "export": answers["export"],
        "subpanel": {
            "q2": f"2P {ac_out['ocpd_a']} A" if ac_out else "2P", "q4": answers["q4"],
            "spd": answers["spd_label"] if answers["spd"] else None,
            "loads": [x for x in (answers["loads1"], answers["loads2"]) if x],
        },
        "comms_notes": {
            "vebus": "VE.Bus (UTP RJ-45, en lista de materiales)",
            "can": f"CAN-bus BMS ({bat.get('model') or 'batería'} #1 a {mon.get('model') or 'GX'}) · cable VE.CAN en lista de materiales",
            "eth": "Ethernet / Modbus TCP (control de potencia del Fronius) · UTP en lista de materiales",
        },
    }
    cfg = _latinize(cfg)
    return cfg, {"blockers": [], "warnings": warnings(project, d, answers, string_a)}


def _project_block(project: dict, d: dict, answers: dict) -> dict:
    site = d["blob"].get("site") or {}
    place = ", ".join(x for x in (site.get("city"), site.get("province")) if x)
    client = project.get("client_name") or "Cliente"
    return {"name": f"Proyecto {client}" + (f" en {place}" if place else ""), "client": client,
            "location": (place + ", Costa Rica") if place else "Costa Rica", "date": date.today().isoformat(),
            "revision": answers["revision"], "draft": bool(answers["draft"])}


def _meter(eq: dict, grid_zero: bool = False) -> dict | None:
    """Energy meter drawn in parallel at the main panel (the VM-3P75CT picked in Equipos; the Fronius Smart Meter in Grid Zero)."""
    if grid_zero:
        mon = eq.get("monitoring") or {}
        if "meter" not in (mon.get("model") or "").lower():
            return None
        from calculations.meter_cts import ct_count

        n_ct = ct_count(mon, eq.get("inverter")) or 2
        model = (mon.get("model") or "").upper()
        return {"title": f"{(mon.get('brand') or '').upper()} SMART METER".strip(),
                "lines": [model.replace("SMART METER", "").strip() or "en paralelo", "en paralelo en el tablero principal", f"{n_ct} TC (POR VERIFICAR TAMAÑO)"],
                "ct_label": f"{n_ct} TC", "comm": "Modbus RTU (cat6e) al Fronius"}
    m = eq.get("energy_meter")
    if not m:
        return None
    return {"title": f"MEDIDOR {m.get('model', '')}".upper(), "lines": ["en paralelo en el tablero principal", "2 TC (POR VERIFICAR TAMAÑO)"],
            "ct_label": "2 TC", "comm": f"Ethernet cat6e al {(eq.get('monitoring') or {}).get('model') or 'GX'}"}


def _spd_label(answers: dict) -> str | None:
    return answers["spd_label"] if answers["spd"] else None


def _build_grid_zero(project: dict, d: dict, answers: dict, string_breaker_a: int | None):
    eq, wiring = d["eq"], d["wiring"]
    from materials.engine import grid_zero_equipment

    eq = grid_zero_equipment(eq)
    branches = wiring["branches"]
    panel, inv = eq["panel"], eq["inverter"]
    pv, dc_inv, ac = _branch(branches, "pv_strings"), _branch(branches, "pv_dc_inv"), _branch(branches, "gz_ac")
    link = _branch(branches, "gz_link")
    string_a = string_breaker_a or pv["ocpd_a"]
    cfg = {
        "kind": "grid_zero", "project": _project_block(project, d, answers), "meter": _meter(eq, grid_zero=True),
        "pv": {
            "strings": int(eq["n_strings"]), "modules_per_string": int(eq["panels_per_string"]), "module_w": int(panel.get("wp") or 0),
            "module_label": f"{panel.get('brand', '')} {panel.get('wp')} W".strip(), "roof_m2": None,
            "string_breaker": f"{string_a} A 2P DC", "dc_wire": f"{_g(pv['ugc'])} SOLAR", "dc_inv_wire": f"{_g(dc_inv['ugc'])} SOLAR",
            "ground_wire": f"T {_g(_egc(pv) or pv['ugc'])} verde",
        },
        "fronius": {
            "label": f"{_model(inv)} 240 V", "kw": inv.get("kw"), "mppt": int(inv.get("mppt_channels") or int(eq["n_strings"])),
            "ac_conductors": [f"L1 {_g(ac['ugc'])} negro", f"L2 {_g(ac['ugc'])} rojo", f"T {_g(_egc(ac) or ac['ugc'])} verde"],
            "ground_wire": f"T {_g(_egc(ac) or ac['ugc'])} verde",
        },
        "base": {"breaker": f"2P {ac['ocpd_a']} A", "ground_wire": f"T {_g(_egc(ac) or ac['ugc'])} verde",
                 "link_conductors": ([f"L1 {_g(link['ugc'])} negro", f"L2 {_g(link['ugc'])} rojo", f"T {_g(_egc(link) or link['ugc'])} verde"] if link else None)},
        "subpanel": {"spd": _spd_label(answers)},
    }
    return _latinize(cfg), {"blockers": [], "warnings": warnings_grid_zero(eq, wiring, string_a)}


def _build_off_grid(project: dict, d: dict, answers: dict, string_breaker_a: int | None):
    eq, wiring = d["eq"], d["wiring"]
    branches = wiring["branches"]
    panel, inv, bat, mon, cc = eq["panel"], eq["inverter"], eq["battery"], eq["monitoring"], eq.get("charge_controller") or {}
    pv_cc, cc_bat, bat_inv = _branch(branches, "pv_strings"), _branch(branches, "cc_bat"), _branch(branches, "bat_inv")
    dc_cc = _branch(branches, "pv_cc") or pv_cc
    ac_in, ac_out = _branch(branches, "ac_in"), _branch(branches, "ac_out")
    qty = int(eq.get("inverter_qty") or 1)
    n_bat = int((eq.get("battery_bank") or {}).get("battery_count") or 0)
    leg_240 = float(inv.get("output_v") or 120) >= 200

    def hots(b):
        g, e = b["ugc"], b.get("egc") or b["ugc"]
        live = ["L1 %s negro" % _g(g), "L2 %s rojo" % _g(g)] if (leg_240 or qty >= 2) else ["L1 %s negro" % _g(g)]
        return live + [f"N {_g(g)} blanco", f"T {_g(e)} verde"]

    fam = "QUATTRO" if "quattro" in (inv.get("model") or "").lower() else "MULTIPLUS-II"
    mshort = (re.search(r"48/\d+", inv.get("model", "")) or re.search(r"\d+", inv.get("model", "") + "0"))[0]
    cfg = {
        "kind": "off_grid", "project": _project_block(project, d, answers), "meter": _meter(eq),
        "pv": {
            "strings": int(eq["n_strings"]), "modules_per_string": int(eq["panels_per_string"]), "module_w": int(panel.get("wp") or 0),
            "module_label": f"{panel.get('brand', '')} {panel.get('wp')} W".strip(), "roof_m2": (eq.get("array") or {}).get("area_m2"),
            "string_breaker": f"{string_breaker_a or pv_cc['ocpd_a']} A 2P DC", "dc_wire": f"{_g(pv_cc['ugc'])} SOLAR",
            "dc_out_wire": f"{_g(dc_cc['ugc'])} SOLAR", "ground_wire": f"T {_g(_egc(pv_cc) or pv_cc['ugc'])} verde",
        },
        "controllers": {
            "count": int(eq.get("charge_controller_qty") or 1), "label": _model(cc),
            "out_pos": f"+ {_g(cc_bat['ugc'])} rojo", "out_neg": f"- {_g(cc_bat['ugc'])} negro",
        },
        "multis": {
            "label": f"{fam} {mshort}", "model": f"{inv.get('model', '').split('/70')[0]} {int(float(inv.get('output_v') or 120))} V", "qty": qty,
            "single_note": "Split-phase 120/240 V · VE.Bus" if leg_240 else "120 V · VE.Bus",
            "ac_out_conductors": hots(ac_out), "dc_pos": f"+ {_g(bat_inv['ugc'])} rojo", "dc_neg": f"- {_g(bat_inv['ugc'])} negro",
            "ground_wire": f"T {_g(_egc(ac_out) or ac_out['ugc'])} verde",
        },
        "battery": {
            "count": n_bat, "label": _model(bat), "short": bat.get("model") or "Batería", "kwh_each": float(bat.get("capacity_kwh") or 0),
            "can_master": "pylontech" in (bat.get("brand") or "").lower(), "lynx": "power_in",
            "lynx_bars": max(1, -(-(n_bat + qty + int(eq.get("charge_controller_qty") or 1)) // 4)),
            "cables_note": (["Cables batería a Power In (+ / -):", "juego de cables de la batería"] if "pylontech" in (bat.get("brand") or "").lower()
                            else ["Cables batería a Power In (+ / -):", "por definir"]),
        },
        "gx": {"label": (mon.get("model") or "GX").upper()},
        "grid_in": ({"label": "RED ELÉCTRICA", "breaker": f"{'2P' if (leg_240 or qty >= 2) else '1P'} {ac_in['ocpd_a']} A", "conductors": hots(ac_in)} if ac_in else None),
        "subpanel": {"q2": f"{'2P' if (leg_240 or qty >= 2) else '1P'} {ac_out['ocpd_a']} A", "q4": answers["q4"], "spd": _spd_label(answers),
                     "loads": [x for x in (answers["loads1"], answers["loads2"]) if x]},
        "comms_notes": {
            "vebus": "VE.Bus (UTP RJ-45, en lista de materiales)",
            "can": f"CAN-bus BMS ({bat.get('model') or 'batería'} #1 a {mon.get('model') or 'GX'}) · cable VE.CAN en lista de materiales",
        },
    }
    return _latinize(cfg), {"blockers": [], "warnings": warnings_off_grid(project, eq, wiring, answers, int(string_breaker_a or pv_cc["ocpd_a"]))}


def _latinize(x):
    if isinstance(x, str):
        return latin(x)
    if isinstance(x, list):
        return [_latinize(i) for i in x]
    if isinstance(x, dict):
        return {k: _latinize(v) for k, v in x.items()}
    return x


def warnings(project: dict, d: dict, answers: dict, string_a: int) -> list[dict]:
    """Engineering reviews (docs/unifilar/references/diseno.md). Advice to confirm, not verdicts."""
    eq, wiring = d["eq"], d["wiring"]
    cpl, branches = wiring["coupling"], wiring["branches"]
    panel, inv = eq["panel"], eq["inverter"]
    out: list[dict] = []

    def add(level, text):
        out.append({"level": level, "text": text})

    ac_in, ac_out, pv = _branch(branches, "ac_in"), _branch(branches, "ac_out"), _branch(branches, "pv_strings")
    fr, bat_inv = _branch(branches, "pv_inv_ac"), _branch(branches, "bat_inv")
    rated_in = float(inv.get("ac_input_current_max_a") or 0)
    if ac_in and rated_in:
        add("info", f"Q1 (AC-IN): 2P {ac_in['ocpd_a']} A sobre {_g(ac_in['ugc'])} ({ac_in.get('ugc_ampacity'):g} A a 75 °C); cada Multi admite {rated_in:g} A de entrada AC. "
                    f"Un breaker de 100 A estaría por encima de ese límite.")
    isc = float(panel.get("isc") or 0)
    need = 1.56 * isc
    if string_a < need:
        add("warn", f"Breaker de string {string_a} A es menor que 1.56 × Isc = {need:.1f} A.")
    else:
        ms = float(panel.get("max_series_fuse_a") or 0)
        if ms and string_a > ms:
            add("warn", f"Breaker de string {string_a} A supera la protección máxima en serie del módulo ({ms:g} A, datasheet).")
        series_txt = (f"protección máxima en serie del módulo {ms:g} A: cumple" if ms
                      else "falta cargar en el catálogo la protección máxima en serie del módulo (datasheet)")
        add("info", f"Breaker de string {string_a} A ≥ 1.56 × Isc ({need:.1f} A); {series_txt}. "
                    f"Confirmar que su tensión nominal CC cubra el Voc del string ({cpl['check']['voc_string']:.0f} V).")
    if fr:
        add("info", f"Q3 (Fronius): 2P {fr['ocpd_a']} A ≥ 125 % de {fr['current_a']:.1f} A.")
    if answers.get("lynx") == "power_in":
        add("warn", "Sin Lynx Distributor, los Multis quedan protegidos por los fusibles de las baterías y los del Power In: confirmar que baste y revisar la capacidad de interrupción frente a la corriente de falla del banco.")
    if bat_inv:
        add("info", f"DC de cada Multi: {bat_inv['current_a']:.0f} A, cable {_g(bat_inv['ugc'])} con fusible de {bat_inv['ocpd_a']} A. El manual del MultiPlus-II pide no instalar los cables de batería en conducto cerrado.")
    for c in cpl["check"]["checks"]:
        if c["ok"] is False:
            add("warn", f"{c['label']}: {c['detail']}")
    note = _abbreviated_note(eq)
    if note:
        out.append(note)
    if eq.get("battery", {}).get("fuse_a"):
        add("info", f"Fusibles MEGA de las baterías: {int(float(eq['battery']['fuse_a']))} A según el datasheet de la batería.")
    else:
        add("warn", "Fusibles MEGA de las baterías sin calibre definido (según manual de la batería): falta el dato en el catálogo.")
    add("info", "El sub-panel de cargas críticas lo pone el propietario o constructor y no va en la lista; en la lista están los breakers Q1, Q2 y Q3 (Q4 y los circuitos del sub-panel quedan a su cargo).")
    if answers.get("export") == "grid_zero":
        add("info", "Grid Zero requiere el UTP Fronius ↔ Ekrano (incluido en la lista de materiales).")
    add("info", "Calibres y breakers salen del dimensionamiento de la pestaña Técnico con los largos por defecto; ajusta los largos de obra antes de emitir el plano.")
    return out


def _string_checks(panel: dict, string_a: int, voc_string: float | None, per: str) -> list[dict]:
    out: list[dict] = []
    isc = float(panel.get("isc") or 0)
    need = 1.56 * isc
    ms = float(panel.get("max_series_fuse_a") or 0)
    if string_a < need:
        out.append({"level": "warn", "text": f"Breaker {string_a} A {per} es menor que 1.56 × Isc = {need:.1f} A."})
    else:
        if ms and string_a > ms:
            out.append({"level": "warn", "text": f"Breaker {string_a} A {per} supera la protección máxima en serie del módulo ({ms:g} A, datasheet)."})
        series_txt = (f"protección máxima en serie del módulo {ms:g} A: cumple" if ms
                      else "falta cargar en el catálogo la protección máxima en serie del módulo (datasheet)")
        volt = f" Confirmar que su tensión nominal CC cubra el Voc del string ({voc_string:.0f} V)." if voc_string else ""
        out.append({"level": "info", "text": f"Breaker {string_a} A {per} ≥ 1.56 × Isc ({need:.1f} A); {series_txt}.{volt}"})
    return out


def warnings_grid_zero(eq: dict, wiring: dict, string_a: int) -> list[dict]:
    panel, inv = eq["panel"], eq["inverter"]
    ch = eq.get("chosen_scenario") or {}
    out = _string_checks(panel, string_a, ch.get("voc_total"), "por string")
    ac = _branch(wiring["branches"], "gz_ac")
    if ac:
        out.append({"level": "info", "text": f"Fronius → base de medidor de generación: breaker 2P {ac['ocpd_a']} A sobre {_g(ac['ugc'])}"
                                             + (f" (máximo del fabricante {ac['max_ocpd_a']} A)." if ac.get("max_ocpd_a") else ".")})
    out.append({"level": "info", "text": "La base de medidor de generación con interruptor principal, el breaker y el candado están en la lista de materiales. "
                                         "Se dibuja interconectada con la base de medición de consumo existente; el cable de esa interconexión no está en la lista."})
    if _meter(eq, grid_zero=True):
        out.append({"level": "info", "text": "El medidor del Fronius va en paralelo en el tablero principal (se dibuja ahí)."})
    out.append({"level": "info", "text": "Calibres y breakers salen del dimensionamiento de la pestaña Técnico con los largos por defecto; ajusta los largos de obra antes de emitir el plano."})
    return out


def _abbreviated_note(eq: dict, qty: int | None = None) -> dict | None:
    n_bat = int((eq.get("battery_bank") or {}).get("battery_count") or 0)
    parts = []
    n_cc = int(eq.get("charge_controller_qty") or 1) if qty else 0     # only the DC-coupled drawing has controllers
    if n_cc > 4:
        parts.append(f"{n_cc} controladores y sus strings (MPPT 1, MPPT 2, «…» y MPPT {n_cc})")
    if n_bat > 4:
        parts.append(f"{n_bat} baterías (#1, #2, «…» y #{n_bat})")
    if qty and qty > 3:
        parts.append(f"{qty} inversores (MP#1, MP#2, «…» y MP#{qty})")
    if not parts:
        return None
    return {"level": "info", "text": "Dibujo abreviado: " + " y ".join(parts) + ". El cableado de los equipos omitidos se repite igual que el de los dibujados."}


def warnings_off_grid(project: dict, eq: dict, wiring: dict, answers: dict, string_a: int) -> list[dict]:
    panel, inv = eq["panel"], eq["inverter"]
    branches = wiring["branches"]
    out = _string_checks(panel, string_a, None, "por string")
    note = _abbreviated_note(eq, int(eq.get("inverter_qty") or 1))
    if note:
        out.append(note)
    bat_inv = _branch(branches, "bat_inv")
    if bat_inv:
        out.append({"level": "info", "text": f"DC de cada inversor: {bat_inv['current_a']:.0f} A, cable {_g(bat_inv['ugc'])} con fusible de {bat_inv['ocpd_a']} A. "
                                             "El manual del MultiPlus-II pide no instalar los cables de batería en conducto cerrado."})
    if eq.get("battery", {}).get("fuse_a"):
        out.append({"level": "info", "text": f"Fusibles MEGA de las baterías: {int(float(eq['battery']['fuse_a']))} A según el datasheet de la batería."})
    else:
        out.append({"level": "warn", "text": "Fusibles MEGA de las baterías sin calibre definido (según manual de la batería): falta el dato en el catálogo."})
    out.append({"level": "warn", "text": "Sin Lynx Distributor, los inversores quedan protegidos por los fusibles de las baterías y los del Power In: confirmar que baste y revisar la capacidad de interrupción."})
    if not _branch(branches, "ac_in"):
        out.append({"level": "info", "text": "Sistema aislado: sin entrada AC (red o generador) en el dibujo."})
    if eq.get("energy_meter"):
        out.append({"level": "info", "text": "El medidor VM va en paralelo en el tablero principal; si el sistema no tiene tablero principal en el dibujo, se anota en el sub-panel de cargas críticas."})
    out.append({"level": "info", "text": "El sub-panel de cargas críticas lo pone el propietario o constructor y no va en la lista; en la lista están los breakers Q1 y Q2 (Q4 y los circuitos del sub-panel quedan a su cargo)."})
    out.append({"level": "info", "text": "Calibres y breakers salen del dimensionamiento de la pestaña Técnico con los largos por defecto; ajusta los largos de obra antes de emitir el plano."})
    return out
