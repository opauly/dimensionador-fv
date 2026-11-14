"""Materials list (purchase list, no prices) from a saved design.

Deterministic: every quantity comes from the design (equipment counts), the wiring sizing
(`calculations/wiring.py` branches) and explicit rules below. Nothing here comes from an LLM.

Output lines are keyed to Oscar's master checklist (`materials/catalog.py`) when the item exists
there, so the export lands on the same rows he already sends to dealers. A part the design needs
that the master list does not carry (a 16 A DC breaker, a 3/0 cable) is added as a new line
flagged `in_master=False` instead of being dropped or forced onto a wrong row.

Edits live in the project (`tech_spec["materials"]`) and are applied on top of the computed list,
so regenerating after a design change never wipes a manual quantity:

    layout     roof layout the mounting counts need (rows, orientation, rail length ...)
    options    project choices (string breaker rating, raceway material per run, fittings per run)
    overrides  {line id: {"qty": n, "comment": str}}   -- user-edited quantity / comment
    extras     [{"id", "key" | None, "name", "unit", "qty", "comment"}]   -- lines added by hand
"""
from __future__ import annotations

import math
from collections import OrderedDict

from calculations import bom as B
from calculations import nec_tables as T
from calculations import wiring as W
from calculations.meter_cts import ct_count
from materials.catalog import CATALOG, SECTIONS

WASTE = 0.10             # cut-offs and slack on cable and conduit
CABLE_STEP_M = 5         # cable is bought by the metre; round the request up to 5 m
TUBE_M = 3.0             # standard conduit length
SPARE_PCT = 5            # spare mounting hardware
FEET_PER_SILICONE = 20   # one tube of roof sealant per this many feet (L brackets)
EMT_STUBS_PER_INVERTER = 4   # short 1" EMT pieces (about 50 cm each) joining the wire duct to each inverter
EMT_TUBES_PER_INVERTER = 1   # linear rule from his purchase: one 3 m tube per inverter (2 inverters -> 2 tubes)
GZ_RUN_FALLBACK_M = 10.0     # Grid Zero: when the wiring lengths are not available (same as the wiring default)
GZ_LINK_FALLBACK_M = 2.0
CHINT_STRINGS = 2            # 2-pole string breakers that fit in one Chint DC 5-space box
GX_CABLE_GAUGE = "12"        # Ekrano/Cerbo supply cable (Oscar: #12 or #14, a few metres); #12 is the gauge already stocked for monitoring
GX_CABLE_M = 3
MONITOR_CIRCUIT_M = 15       # monitoring outlet circuit: metres of each #12 conductor
LUG_STEP = 5             # lugs are requested in fives
SHRINK_M_PER_LUG = 0.08  # heat-shrink per lug end (DC battery cables)
PANEL_GAP_M = 0.02       # gap between modules in a row
STRAP_SPACING_M = {"PVC": 1.25, "EMT": 1.5}

DEFAULT_LAYOUT = {"rows": None, "orientation": "portrait", "rail_len_m": 4.7, "foot_spacing_m": 1.0}
LAYOUT_SCRATCH_KEY = "roof_layout"   # where the wizard keeps the roof layout while a quote is being built


def clean_layout(raw: dict | None) -> dict:
    """Only the layout keys that carry a real value (rows > 0, a known orientation, positive lengths)."""
    raw, out = raw or {}, {}
    try:
        rows = int(float(str(raw.get("rows")).replace(",", ".")))
        if rows > 0:
            out["rows"] = rows
    except (TypeError, ValueError):
        pass
    if raw.get("orientation") in ("portrait", "landscape"):
        out["orientation"] = raw["orientation"]
    for k in ("rail_len_m", "foot_spacing_m"):
        try:
            v = float(str(raw.get(k)).replace(",", "."))
            if v > 0:
                out[k] = v
        except (TypeError, ValueError):
            pass
    return out


def layout_from_blob(blob: dict | None) -> dict:
    """The roof layout answered in the wizard (blob["scratch"]["roof_layout"])."""
    return clean_layout(((blob or {}).get("scratch") or {}).get(LAYOUT_SCRATCH_KEY))
DEFAULT_OPTIONS = {"string_breaker_a": None, "bends_per_raceway": 2, "lb_per_raceway": 0, "conduit_material": {}}
# Battery-side DC runs are not piped by default (the MultiPlus manual: no closed conduit around battery cables).
DEFAULT_CONDUIT_MATERIAL = {"bat_inv": "none", "cc_bat": "none"}
CONDUIT_MATERIALS = ("PVC", "EMT", "none")

WHERE = {
    "pv_strings": "Strings FV", "pv_cc": "Breakers CC → controlador", "pv_inv_ac": "Fronius → sub-panel",
    "cc_bat": "Controlador → baterías", "bat_inv": "Baterías → inversores", "ac_out": "AC Out", "ac_in": "AC In",
    "pv_dc_inv": "Breakers CC → Fronius", "gz_ac": "Fronius → base de generación",
    "gz_link": "Base de generación → base de consumo",
    "gz_disc": "Fronius → centro de carga de desconexión", "pv_disc": "Fronius → centro de carga de desconexión",
}

# Equipment names in the master list -> substrings of "brand model" (lowercase) that mean the same item.
ALIASES = {
    "Inversor Quattro 48/10000/140 120V": ["quattro 48/10000"],
    "Inversor Multiplus 5000 120V": ["48/5000"],
    "Inversor Multiplus 3000 120V": ["48/3000"],
    "Controlador de carga 450/200": ["450/200"],
    "Controlador de carga 250/100": ["250/100"],
    "Controlador de carga 150/70": ["150/70"],
    "Batería Pylontech US5000": ["us5000"],
    "Batería Pylontech Fidus": ["fidus"],
    "Ekrano GX": ["ekrano"],
    "Cerbo GX": ["cerbo"],
    "Medidor VM-3P75CT": ["vm 3p75ct"],
}
CT_PER_METER = 2   # split-phase: one current transformer per line
BATTERY_STAND_SLOTS = 6  # US5000/UF5000 per metal stand (3 levels x 2), to be confirmed by Oscar
METER_CT_KEY = "interconexion-transformador-de-corriente-100a-333mv"
METER_BASE_KEY = "interconexion-base-para-medidor-monofasica-con-interruptor-principal-tipo-parche-clase-100-combo-base"
METER_BREAKER_KEY = "interconexion-breaker-30a-compatible-con-base-para-medidor"
PADLOCK_KEY = "interconexion-candado-pequeno-para-base-medidor"

_SECTION_RANK = {s: i for i, s in enumerate(SECTIONS)}
_BY_NAME = {(r["section"], r["name"]): r for r in CATALOG}
_BY_KEY = {r["key"]: r for r in CATALOG}
_INDEX = {r["key"]: i for i, r in enumerate(CATALOG)}


def _find(kind: str, **attrs) -> dict | None:
    for r in CATALOG:
        if r.get("kind") == kind and all(str(r["attrs"].get(k)) == str(v) for k, v in attrs.items()):
            return r
    return None


def _named(name: str, section: str | None = None) -> dict | None:
    if section:
        return _BY_NAME.get((section, name))
    return next((r for r in CATALOG if r["name"] == name), None)


def _norm(text: str) -> str:
    return " ".join((text or "").lower().replace("-", " ").split())


def match_equipment(item: dict | None) -> dict | None:
    text = _norm(f"{(item or {}).get('brand', '')} {(item or {}).get('model', '')}")
    for name, subs in ALIASES.items():
        if any(_norm(s) in text for s in subs):
            return _named(name)
    return None


def _ceil_to(x: float, step: float) -> float:
    return math.ceil(round(x, 6) / step) * step


class Collector:
    """Accumulates list lines; the same item added twice sums its quantity and joins its notes."""

    def __init__(self) -> None:
        self.lines: "OrderedDict[str, dict]" = OrderedDict()
        self._dyn = 0

    def add(self, row: dict | None, qty: float, *, name: str | None = None, unit: str = "un", section: str = "Generales",
            group: str | None = None, sibling: dict | None = None, where: str | None = None, note: str | None = None,
            source: str = "regla", comment: str | None = None) -> None:
        if qty is None or qty <= 0:
            return
        if row is not None:
            key, in_master = row["key"], True
            name, unit, section, group = row["name"], row["unit"], row["section"], row["group"]
            order = (_SECTION_RANK.get(section, 9), _INDEX[key], 0)
        else:
            key, in_master = "x:" + _slug(name or "item"), False
            if sibling:
                section, group = sibling["section"], sibling["group"]
            idx = max((_INDEX[r["key"]] for r in CATALOG if r["section"] == section and r["group"] == group), default=len(CATALOG))
            self._dyn += 1
            order = (_SECTION_RANK.get(section, 9), idx, self._dyn)
        line = self.lines.get(key)
        if line is None:
            line = {"id": key, "name": name, "unit": unit, "section": section, "group": group, "qty": 0.0, "in_master": in_master,
                    "source": source, "wheres": [], "notes": [], "comments": [], "order": order}
            self.lines[key] = line
        line["qty"] += qty
        for lst, val in ((line["wheres"], where), (line["notes"], note), (line["comments"], comment)):
            if val and val not in lst:
                lst.append(val)


def _slug(s: str) -> str:
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ── Rules ──────────────────────────────────────────────────────────────────────

def grid_zero_equipment(eq: dict) -> dict:
    """A Grid Zero design stores the array in `chosen_scenario` (string inverter, no batteries or controllers);
    the list reads the same keys as the other system types, so copy them up."""
    ch = eq.get("chosen_scenario") or {}
    return {**eq, "panel_count": int(eq.get("panel_count") or ch.get("total_panels") or 0),
            "n_strings": int(eq.get("n_strings") or ch.get("strings") or 0),
            "panels_per_string": int(eq.get("panels_per_string") or ch.get("panels_per_string") or 0), "inverter_qty": 1}


def _interconnection(c: Collector, eq: dict, branches: list[dict] | None = None) -> None:
    """Grid Zero only: meter base with main switch, the breaker that feeds the grid from the inverter
    (125 % of the inverter's maximum output current, next standard size) and the padlock."""
    inv = eq.get("inverter") or {}
    c.add(_BY_KEY[METER_BASE_KEY], 1, note="base de medidor de generación con interruptor principal: solo Grid Zero")
    out_a = float(inv.get("ac_output_current_a") or 0)
    sizes = list(T.OCPD_SIZES_A)
    if out_a > 0:
        amps = next((a for a in sizes if a >= out_a * 1.25), sizes[-1])
        why = f"125 % de la corriente máxima del inversor ({out_a:g} A), tamaño comercial siguiente"
        comment = None
    else:
        amps, why, comment = 30, "sin corriente máxima del inversor en el catálogo: se asume 30 A", "POR CONFIRMAR AMPERAJE"
    max_a = float(inv.get("max_ocpd_a") or 0)
    if max_a and amps > max_a:
        amps, why = int(max_a), why + f"; limitado al breaker máximo del fabricante ({max_a:g} A)"
    sized = next((b for b in branches or [] if b.get("key") == "gz_ac" and b.get("ocpd_a")), None)
    if sized:       # the wiring sizing already holds it (manual override included)
        amps, why, comment = int(sized["ocpd_a"]), f"el del tramo «{sized['label']}» (125 % de la corriente máxima del inversor, tamaño comercial siguiente)", None
    row = _BY_KEY[METER_BREAKER_KEY] if amps == 30 else None
    c.add(row, 1, name=f"Breaker {amps}A compatible con base para medidor", section="Generales", group="Interconexión",
          sibling=_BY_KEY[METER_BREAKER_KEY], comment=comment, note=why)
    c.add(_BY_KEY[PADLOCK_KEY], 1, note="candado para la base de medidor de generación")


def _equipment(c: Collector, eq: dict, coupling: dict, lengths: dict | None = None, grid_zero: bool = False) -> None:
    panel, inv = eq.get("panel") or {}, eq.get("inverter") or {}
    bat, cc, mon = eq.get("battery") or {}, eq.get("charge_controller") or {}, eq.get("monitoring") or {}
    model = lambda it: f"{it.get('brand', '')} {it.get('model', '')}".strip()  # noqa: E731
    n_panels = int(eq.get("panel_count") or 0)
    if panel and n_panels:
        c.add(_named("Paneles solares", "Paneles solares"), n_panels, source="diseño", comment=model(panel),
              note=f"{n_panels} módulos del diseño")
    if grid_zero:
        if inv:
            c.add(None, 1, name=f"Inversor {model(inv)}", section="Paneles solares", source="diseño",
                  comment=f"{inv.get('kw')} kW · Grid Zero", note="inversor de strings del diseño")
        if eq.get("monitoring"):
            c.add(None, 1, name=model(eq["monitoring"]), section="Generales", group="Monitoreo", source="diseño",
                  sibling=_named("Cable UTP, cat 5 (interiores o exteriores)"))
            n_ct = ct_count(eq["monitoring"], inv)
            if n_ct:
                c.add(_BY_KEY[METER_CT_KEY], n_ct, comment="POR VERIFICAR TAMAÑO",
                      note=f"{n_ct} transformadores de corriente del medidor Fronius: uno por fase ({'trifásico' if n_ct == 3 else 'monofásico'}), "
                           "justo después del medidor de consumo")
                # Modbus (RS485) from the meter, where the CTs sit after the consumption meter, to the inverter: Ethernet cat6e as long as the
                # inverter -> generation base run plus the hop between the two meter bases.
                run = float((lengths or {}).get("ac_out_m") or GZ_RUN_FALLBACK_M) + float((lengths or {}).get("gz_link_m") or GZ_LINK_FALLBACK_M)
                c.add(None, _ceil_to(run * (1 + WASTE), CABLE_STEP_M), name="Cable de red Ethernet cat6e", unit="m", section="Generales",
                      group="Monitoreo", sibling=_named("Cable UTP, cat 5 (interiores o exteriores)"), where="Medidor Fronius → inversor",
                      note=f"{run:g} m (Fronius → base de generación + base de generación → base de consumo) + {int(WASTE * 100)} % de desperdicio, de a {CABLE_STEP_M:g} m")
        return
    if inv:
        qty = int(eq.get("inverter_qty") or 1)
        row = match_equipment(inv)
        c.add(row, qty, name=model(inv), section="Victron Energy", source="diseño", comment=None if row else "no está en la lista maestra",
              note=f"{qty} inversor(es) del diseño")
    if coupling.get("ac") and coupling.get("pv_inverter"):
        pv = coupling["pv_inverter"]
        c.add(None, int(coupling.get("qty") or 1), name=f"Inversor {model(pv)}", section="Paneles solares", source="diseño",
              comment=f"{pv.get('kw')} kW · acople AC", note="Inversor FV del acople AC")
    elif cc:
        qty = int(eq.get("charge_controller_qty") or 1)
        row = match_equipment(cc)
        c.add(row, qty, name=model(cc), section="Victron Energy", source="diseño", note=f"{qty} controlador(es) del diseño")
    n_bat = int((eq.get("battery_bank") or {}).get("battery_count") or 0)
    if bat and n_bat:
        row = match_equipment(bat)
        c.add(row, n_bat, name=model(bat), section="Victron Energy", source="diseño", note=f"{n_bat} batería(s) del diseño")
        if "pylontech" in _norm(bat.get("brand", "")):
            c.add(_named("Cables para Pylontech", "Victron Energy"), n_bat, source="regla", note="un juego de cables por batería Pylontech")
        if _norm(bat.get("model", "")).startswith(("us5000", "uf5000")):
            # US5000/UF5000 are rack batteries and sit on a separate metal stand (Fidus is wall-mounted and needs none).
            stands = max(1, math.ceil(n_bat / BATTERY_STAND_SLOTS))
            c.add(None, stands, name="Mueble metálico para baterías", unit="un", section="Generales", source="regla", comment="POR CONFIRMAR MEDIDA",
                  note=f"{n_bat} baterías {bat.get('model')} van en mueble aparte, hasta {BATTERY_STAND_SLOTS} por mueble (por confirmar)")
    if mon:
        row = match_equipment(mon)
        c.add(row, 1, name=model(mon), section="Victron Energy", source="diseño")
    meter = eq.get("energy_meter") or {}
    if meter:
        row = match_equipment(meter)
        c.add(row, 1, name=model(meter), section="Victron Energy", source="diseño", comment=None if row else "no está en la lista maestra",
              note="medidor de energía elegido en Equipos")
        c.add(_BY_KEY[METER_CT_KEY], CT_PER_METER, comment="POR VERIFICAR TAMAÑO",
              note=f"{CT_PER_METER} transformadores de corriente para el medidor (uno por línea)")
        # Ethernet from the meter (at the electrical panel) to the Cerbo/Ekrano in the cabinet: same run as grid -> inverters.
        run = float((lengths or {}).get("ac_in_m") or 0)
        if run > 0:
            c.add(None, _ceil_to(run * (1 + WASTE), CABLE_STEP_M), name="Cable de red Ethernet cat6e", unit="m", section="Generales",
                  group="Monitoreo", sibling=_named("Cable UTP, cat 5 (interiores o exteriores)"), where="Medidor → Cerbo/Ekrano GX",
                  note=f"{run:g} m del tramo gabinete → tablero eléctrico (largo de «Red → entrada AC») + {int(WASTE * 100)} % de desperdicio, de a {CABLE_STEP_M:g} m")


def _system(c: Collector, eq: dict, coupling: dict, wiring_ctx: dict) -> None:
    for r in B.system_rows(eq, coupling, wiring_ctx):
        item = r["item"]
        if item.startswith("Victron Lynx Power In"):
            c.add(_named("Lynx Power In", "Victron Energy"), r["qty"], note=r["note"])
        elif item.startswith("Pernos"):
            c.add(_named("Roscas para Lynx Power In", "Victron Energy"), r["qty"], note=r["note"])
        elif item.startswith("Fusible MEGA de batería") and r.get("amps"):
            c.add(_find("fuse_mega", amps=r["amps"]), r["qty"], name=f"Fusible Mega {r['amps']}A", section="Victron Energy",
                  sibling=_find("fuse_mega", amps=225), note=r["note"])
        elif item.startswith("Fusible MEGA de batería"):
            c.add(None, r["qty"], name="Fusible Mega de batería (calibre por definir)", section="Victron Energy",
                  sibling=_find("fuse_mega", amps=225), note=r["note"], comment="calibre por definir")
        elif item.startswith("Cable UTP"):
            c.add(_named("Cable UTP normal", "Victron Energy"), r["qty"], note=r["note"])
        elif item.startswith("Cable VE.CAN"):
            c.add(_named("Cable UTP tipo A", "Victron Energy"), r["qty"], note=r["note"] + " (cable VE.CAN)")


def string_count(eq: dict, coupling: dict | None) -> int:
    coupling = coupling or {}
    return int(coupling.get("strings") or 0) if coupling.get("ac") else int(eq.get("n_strings") or 0)


def with_default_rows(layout: dict, strings: int) -> dict:
    """Without an answer, each string is one row of modules (two rails per string). `rows_auto`
    tells the screens the number came from the design and not from the user."""
    auto = not layout.get("rows") and strings > 0
    return {**layout, "rows": strings if auto else layout.get("rows"), "rows_auto": auto}


def layout_counts(panel: dict, n_panels: int, layout: dict) -> dict | None:
    """Rails, feet and clamps for `rows` rows of modules (two rails under each row)."""
    rows = int(layout.get("rows") or 0)
    if not (rows and n_panels):
        return None
    ppr = math.ceil(n_panels / rows)
    portrait = layout.get("orientation") != "landscape"
    dim = float(panel.get("width_m" if portrait else "height_m") or 0)
    if not dim:
        return None
    row_len = ppr * dim + (ppr - 1) * PANEL_GAP_M
    lines = rows * 2
    rails_per_line = math.ceil(row_len / float(layout["rail_len_m"]))
    return {
        "rows": rows, "per_row": ppr, "row_len_m": round(row_len, 2), "rail_lines": lines,
        "rails": lines * rails_per_line, "splices": lines * (rails_per_line - 1),
        "feet": lines * (math.ceil(row_len / float(layout["foot_spacing_m"])) + 1),
        "mid": rows * (ppr - 1) * 2, "end": rows * 4,
    }


def _mounting(c: Collector, eq: dict, layout: dict, pending: list[str]) -> None:
    panel = eq.get("panel") or {}
    n_panels = int(eq.get("panel_count") or 0)
    if not n_panels:
        return
    counts = layout_counts(panel, n_panels, layout)
    if counts is None:
        pending.append("Falta el layout del techo (filas de paneles): rieles, patas y clamps no se calculan sin él.")
        return
    spare = 1 + SPARE_PCT / 100
    desc = (f"{counts['rows']} fila(s) de {counts['per_row']} módulos ({layout['orientation']})"
            f"{', un string por fila' if layout.get('rows_auto') else ''}, "
            f"{counts['row_len_m']} m por fila, 2 rieles por fila")
    for name, key, base, why in (
        ("Rieles (largueros)", "rails", counts["rails"], f"{desc}; rieles de {layout['rail_len_m']} m"),
        ("Patas tipo \"L\" / Escuadra de fijación", "feet", counts["feet"], f"una pata cada {layout['foot_spacing_m']} m de riel + 1 por línea"),
        ("Midclamp", "mid", counts["mid"], "2 por cada espacio entre módulos de una fila"),
        ("Endclamp", "end", counts["end"], "4 por fila (2 en cada extremo)"),
    ):
        c.add(_named(name, "Paneles solares"), math.ceil(base * spare), note=f"{why}; {base} calculados + {SPARE_PCT} % de repuesto")
    c.add(_named("Tierras para rieles", "Paneles solares"), counts["rails"], note="una tierra por riel")
    if counts["splices"]:
        c.add(_named("Uniones de riel", "Paneles solares"), counts["splices"], note="una unión por empalme de riel")


def _project_kit(c: Collector, eq: dict, coupling: dict, layout: dict, pending: list[str], grid_zero: bool = False) -> None:
    """Items every project carries whatever its size (Oscar's rules): one enclosure, one surge
    protector, roof sealant, the DC breaker box, the wire duct and its EMT stubs to the inverters,
    and the monitoring outlet. Roof screws are not listed: the L brackets already come with theirs.
    The critical-loads sub-panel is supplied by the owner or builder, so it is not listed either."""
    if not eq.get("panel"):
        return
    # Oscar (2026-11-13): the gabinete is the norm in every system, Grid Zero included (the Fronius Smart Meter goes in it); the plexo box is
    # only for the odd case with no gabinete, which is a manual edit of this line in the Lista.
    c.add(_named("Gabinete metálico 50x40x20", "Generales"), 1, comment="POR CONFIRMAR MEDIDA",
          note=("un gabinete para el Fronius Smart Meter y sus bornes (Grid Zero); medida base 50x40x20" if grid_zero
                else "un gabinete para los breakers AC (riel DIN), el Ekrano/Cerbo GX y la barra de tierras; medida base 50x40x20"))
    c.add(_named("Supresor de Picos SDSA 1175", "Generales"), 1, note="uno por proyecto")
    c.add(_named("Riel DIN perforado 35x15mm", "Generales"), 1, note="uno por proyecto: para los breakers y bornes del gabinete")
    c.add(_named("Terminal para riel din", "Generales"), 1, note="uno por proyecto")
    c.add(_named("Riel strut perfil bajo", "Generales"), 1, note="uno por proyecto")

    strings = int(coupling.get("strings") or 0) if coupling.get("ac") else int(eq.get("n_strings") or 0)
    chint = max(1, math.ceil(strings / CHINT_STRINGS))       # a 5-space box holds two 2-pole breakers
    c.add(_named("Centro de carga Chint DC 5 espacios", "Generales"), chint,
          note="siempre va: aloja los breakers DC de los strings" + (f" ({CHINT_STRINGS} strings por caja, {strings} strings)" if chint > 1 else ""))
    c.add(None, 2, name="Manguito prensacable de poliamida gris PG-21 (incluye contratuerca)", section="Generales",
          sibling=_named("Centro de carga Chint DC 5 espacios", "Generales"), note="2 por proyecto, como en la cotización de MAZ")
    if chint > 1:
        pending.append(f"Cada centro de carga Chint de 5 espacios aloja 2 breakers 2P de strings; el diseño tiene {strings} strings, así que van {chint} cajas.")
    if not grid_zero and eq.get("monitoring"):     # the Ekrano/Cerbo takes its power straight from the Lynx bus (internal fuse, no breaker)
        for color in ("rojo", "negro"):
            c.add(_find("cable_thhn", gauge=GX_CABLE_GAUGE, color=color), GX_CABLE_M, name=f"Cable #{GX_CABLE_GAUGE} AWG THHN, CU, color {color}", unit="m",
                  section="Generales", group="Cable", sibling=_find("cable_thhn", gauge=GX_CABLE_GAUGE, color="negro"), where="Alimentación Ekrano/Cerbo",
                  note=f"{GX_CABLE_M} m de #{GX_CABLE_GAUGE} para alimentar el Ekrano/Cerbo desde la barra Lynx (+ rojo, - negro); lleva fusible interno, sin breaker")

    counts = layout_counts(eq.get("panel") or {}, int(eq.get("panel_count") or 0), layout)
    feet = counts["feet"] if counts else 0
    c.add(_named("Silicon 3M (especificar color según color de las láminas del techo)", "Generales"),
          max(1, math.ceil(feet / FEET_PER_SILICONE)),
          note=f"un tubo por cada {FEET_PER_SILICONE} patas (mínimo 1)")

    # Oscar (2026-11-13): Grid Zero carries the 4x4 duct, the short EMT stubs to the inverter and the monitoring outlet kit too.
    c.add(_named("Ducto metálico cuadrado 4x4", "Generales"), 1, note="mínimo 1: lleva el cableado general de los inversores (el cable de batería va por fuera del tubo)")
    c.add(_named("Tapas para ducto metálico 4x4", "Generales"), 2, note="2 tapas finales por ducto (mínimo)")
    inv_qty = int(eq.get("inverter_qty") or 1) if eq.get("inverter") else 0
    stubs = inv_qty * EMT_STUBS_PER_INVERTER
    if stubs:
        c.add(_find("conduit_tube", material="EMT", trade="1"), inv_qty * EMT_TUBES_PER_INVERTER, where="Ducto → inversores",
              note=f"un tubo de {TUBE_M:g} m por inversor ({EMT_STUBS_PER_INVERTER} tramos de unos 50 cm del ducto a cada inversor)")
        c.add(_find("conduit_press_connector", material="EMT", trade="1"), stubs, where="Ducto → inversores",
              note=f"{EMT_STUBS_PER_INVERTER} tramos por inversor, un conector de presión por tramo")

    kit = "toma de monitoreo (Ekrano/router): siempre va"
    c.add(None, 1, name="Breaker 20A 1 polo CH (toma de monitoreo)", section="Generales", sibling=_named("Breaker de 20A 2 polos, marca CH /SD"), note=kit)
    c.add(None, 1, name="Toma doble 15A 125V", section="Generales", sibling=_named("Tomacorriente tipo parche 15A, 120V."), note=kit)
    c.add(None, 1, name="Placa de acero inoxidable para toma doble", section="Generales", sibling=_named("Tomacorriente tipo parche 15A, 120V."), note=kit)
    c.add(None, 1, name="Caja rectangular de intemperie 3 huecos 1/2\"", section="Generales", sibling=_named("Tomacorriente tipo parche 15A, 120V."), note=kit)
    for color in ("rojo", "verde", "blanco"):
        c.add(_find("cable_thhn", gauge="12", color=color), MONITOR_CIRCUIT_M, name=f"Cable #12 AWG THHN, CU, color {color}", unit="m",
              section="Generales", group="Cable", sibling=_find("cable_thhn", gauge="12", color="negro"), where="Toma de monitoreo",
              note=f"{MONITOR_CIRCUIT_M} m para el circuito de la toma de monitoreo (fase, neutro y tierra)")


def _pv_connectors(c: Collector, eq: dict, coupling: dict) -> None:
    strings = int(coupling.get("strings") or 0) if coupling.get("ac") else int(eq.get("n_strings") or 0)
    if strings:
        c.add(_named("MC4", "Paneles solares"), strings * 2 * 2, comment="Parejas macho/hembra",
              note=f"{strings} strings × 2 polaridades × 2 extremos del tendido")


def _cable_lines(branches: list[dict]) -> tuple[dict, dict]:
    """({(kind, gauge, color): metres}, {(gauge): conductor ends needing a lug})."""
    tally: dict[tuple, dict] = {}
    lugs: dict[str, dict] = {}

    def put(kind, gauge, color, m, where, ends=0):
        t = tally.setdefault((kind, gauge, color), {"m": 0.0, "where": []})
        t["m"] += m
        if where not in t["where"]:
            t["where"].append(where)
        if ends:
            lg = lugs.setdefault(gauge, {"n": 0, "where": [], "dc": {}})
            lg["n"] += ends
            if where not in lg["where"]:
                lg["where"].append(where)
            if kind == "cable_thhn" and color in ("rojo", "negro") and where in ("Baterías → inversores", "Controlador → baterías"):
                lg["dc"][color] = lg["dc"].get(color, 0) + ends

    for b in branches:
        key, where, L = b.get("key"), WHERE.get(b.get("key"), b["label"]), b["length_m"]
        for i in range(b["qty"]):
            for r in b.get("conductors") or []:
                g, n = r["gauge"], r["count"]
                if r["role"] == "EGC":
                    if i >= b.get("raceways", b["qty"]):
                        continue            # a shared pipe carries one ground for all its runs
                    put("cable_thhn", g, "verde", n * L, where, 2 * n)
                elif key in ("pv_strings", "pv_cc", "pv_dc_inv"):
                    put("cable_solar", g, "rojo", L, where)
                    put("cable_solar", g, "negro", L, where)
                elif key in ("cc_bat", "bat_inv"):
                    put("cable_thhn", g, "rojo", L, where, 2)
                    put("cable_thhn", g, "negro", L, where, 2)
                elif key in ("pv_inv_ac", "gz_ac", "gz_link", "gz_disc", "pv_disc"):
                    put("cable_thhn", g, "negro", L, where, 2)
                    put("cable_thhn", g, "rojo", L, where, 2)
                elif r["role"] == "Neutro":
                    put("cable_thhn", g, "blanco", n * L, where, 2 * n)
                else:   # AC phases: inverter 1 on L1 (black), inverter 2 on L2 (red)
                    put("cable_thhn", g, "negro" if i % 2 == 0 else "rojo", n * L, where, 2 * n)
    return tally, lugs


def _cables(c: Collector, branches: list[dict]) -> None:
    tally, lugs = _cable_lines(branches)
    total_m, colors = 0.0, set()
    for (kind, g, color), t in tally.items():
        m = t["m"] * (1 + WASTE)
        label = W.gauge_label(g)
        if kind == "cable_solar":
            qty = _ceil_to(m, CABLE_STEP_M)
            row, name, section, group = _find(kind, gauge=g, color=color), f"Cable #{g} AWG - SOLAR {color}", "Paneles solares", None
            note = f"{t['m']:g} m calculados (distancia del techo al centro de carga DC) + {int(WASTE * 100)} % de desperdicio, pedido por metro en pasos de {CABLE_STEP_M} m"
        else:
            qty = _ceil_to(m, CABLE_STEP_M)
            row, name = _find(kind, gauge=g, color=color), f"Cable #{g} AWG THHN, CU, color {color}"
            section, group = "Generales", "Cable"
            note = f"{t['m']:g} m calculados ({label}) + {int(WASTE * 100)} % de desperdicio, redondeado a {CABLE_STEP_M} m"
            total_m += t["m"]
        colors.add(color)
        c.add(row, qty, name=name, unit="m", section=section, group=group, sibling=_find(kind, gauge="10", color=color) or _find(kind, gauge="4", color=color),
              where=" · ".join(t["where"]), note=note)

    for g, lg in lugs.items():
        n = math.ceil(lg["n"] * (1 + WASTE))
        c.add(_find("lug", gauge=g), _ceil_to(n, LUG_STEP), name=f"Conector de ojo para cable #{g} AWG", section="Generales",
              group="Accesorios eléctricos", sibling=_find("lug", gauge="4"), where=" · ".join(lg["where"]),
              note=f"{lg['n']} extremos de conductor × 1.1, de a {LUG_STEP}")
        for color, ends in lg["dc"].items():
            m = max(1, math.ceil(ends * SHRINK_M_PER_LUG))
            c.add(_find("shrink", gauge=g, color=color), m, name=f"Termoencogible para cable #{g} {color}", unit="m", section="Generales",
                  group="Accesorios eléctricos", sibling=_find("shrink", gauge="4", color=color), note=f"{ends} terminales × {SHRINK_M_PER_LUG * 100:g} cm, mínimo 1 m")
    for color in sorted(colors):
        row = _find("tape", color=color)
        if row:
            c.add(row, 1, note=f"un rollo por color de conductor usado ({color})")
    c.add(_named("Gasas plásticas #8 (Negras)", "Generales"), 1, note="un paquete (lo mínimo)", comment="Paquetes")
    c.add(_named("Kit barra de tierras", "Generales"), 1, note="uno por sistema")


def _protections(c: Collector, branches: list[dict], opts: dict) -> None:
    for b in branches:
        amps, key, where = b.get("ocpd_a"), b.get("key"), WHERE.get(b.get("key"), b["label"])
        if not amps or key in ("gz_ac", "gz_disc", "pv_disc"):      # Grid Zero: the AC breaker sits in the meter base (see _interconnection); the disconnect center's in _disconnect
            continue
        hot = next((r["count"] for r in b.get("conductors") or [] if r["role"] == "UGC"), 2)
        if b.get("protection") == "fuse":
            c.add(_find("fuse_mega", amps=amps), b["qty"], name=f"Fusible Mega {amps}A", section="Victron Energy", sibling=_find("fuse_mega", amps=225),
                  where=where, note=f"un fusible por tendido ({b['qty']}) en la barra Lynx Power In")
        elif key in ("pv_strings", "pv_cc"):
            a = int(opts.get("string_breaker_a") or amps) if key == "pv_strings" else amps
            note = "uno por string" + (f" (calculado {amps} A, elegido {a} A)" if a != amps else "")
            c.add(_find("breaker_dc_din", amps=a, poles=2), b["qty"], name=f"Breaker DC para riel DIN {a}A 2P", section="Paneles solares",
                  sibling=_find("breaker_dc_din", amps=32, poles=2), where=where, note=note)
        else:
            qty, poles = b["qty"], hot
            note = f"{amps} A calculado"
            if key in ("ac_in", "ac_out") and hot == 1 and qty % 2 == 0:
                qty, poles, note = qty // 2, 2, f"{b['qty']} inversores de 120 V en L1 y L2 comparten un breaker de 2 polos de {amps} A"
            c.add(_find("breaker_ac_din", amps=amps, poles=poles), qty, name=f"Breaker AC para riel DIN {amps}A {poles}P", section="Generales",
                  sibling=_find("breaker_ac_din", amps=90, poles=2), where=where, note=note)


def _conduit(c: Collector, branches: list[dict], opts: dict) -> None:
    mats = {**DEFAULT_CONDUIT_MATERIAL, **(opts.get("conduit_material") or {})}
    groups: dict[tuple, dict] = {}
    for b in branches:
        cd = b.get("conduit")
        mat = mats.get(b.get("key"), "PVC")
        if not cd or mat == "none":
            continue
        g = groups.setdefault((mat, cd["trade"]), {"raceways": 0, "m": 0.0, "where": []})
        g["raceways"] += b.get("raceways", b["qty"])
        g["m"] += b.get("raceways", b["qty"]) * b["length_m"]
        g["where"].append(WHERE.get(b.get("key"), b["label"]))
    used_pvc = False
    bends, lbs = int(opts.get("bends_per_raceway", 2)), int(opts.get("lb_per_raceway", 0))
    for (mat, trade), g in groups.items():
        where = " · ".join(g["where"])
        tubes = math.ceil(g["m"] * (1 + WASTE) / TUBE_M)
        per = max(1, math.ceil(tubes / g["raceways"]))
        used_pvc = used_pvc or mat == "PVC"
        spacing = STRAP_SPACING_M[mat]
        conn_kind = "conduit_press_connector" if mat == "EMT" else "conduit_connector"
        conn_name = f'Conector de presión {trade}" EMT' if mat == "EMT" else f'Conector {trade}"/ {mat} SCH-40'
        for kind, text, qty, note in (
            ("conduit_tube", f'Tuberia {trade}" / {mat}', tubes,
             f"{g['m']:g} m de recorrido × 1.1 en tubos de {TUBE_M:g} m ({g['raceways']} canalización(es))"),
            (conn_kind, conn_name, 2 * g["raceways"], "2 por canalización (uno en cada extremo)"),
            ("conduit_union", f'Uniones de {trade}" / {mat}', g["raceways"] * (per - 1), f"{per - 1} por canalización (tubos de {TUBE_M:g} m)"),
            ("conduit_bend", f'Curva de {trade}" / {mat}', bends * g["raceways"], f"{bends} curvas por canalización"),
            ("conduit_lb", f'Conduleta LB {trade}"', lbs * g["raceways"], f"{lbs} por canalización"),
            ("conduit_strap", f'Gasa channel {trade}"', math.ceil(g["m"] / spacing), f"una cada {spacing:g} m de recorrido"),
        ):
            sibling = _find(kind, material=mat, trade="1") or _find(kind, material="PVC", trade="1")
            c.add(_find(kind, material=mat, trade=trade), qty, name=text, section="Generales", sibling=sibling, where=where, note=note)
    if used_pvc:
        c.add(_named("Pegamento para PVC", "Generales"), 1, note="una unidad si hay tubería PVC")


DISC_BOX_KEY = "interconexion-tablero-nema-3r-4-espacios-marca-ch-sd-barras-de-125a-monofasico"
METER_FEED_GAUGE = "12"    # Smart Meter voltage supply from the disconnect center: a few metres of #12
METER_FEED_M = 3


def _disconnect(c: Collector, wiring_ctx: dict, eq: dict, grid_zero: bool) -> None:
    """Optional disconnect load center next to the Fronius (Oscar, 2026-11-13): a 4-space load center with a 2-pole breaker for the
    Fronius output (the same size as the generation-base / sub-panel breaker) and, in Grid Zero with a Smart Meter, a second 2-pole breaker
    of the same size that feeds the meter. It adds to the rest of the interconnection, it does not replace it."""
    if not (wiring_ctx.get("disconnect") or {}).get("enabled"):
        return
    key = "gz_disc" if grid_zero else "pv_disc"
    branch = next((b for b in wiring_ctx.get("branches") or [] if b.get("key") == key), None)
    c.add(_BY_KEY[DISC_BOX_KEY], 1, note="centro de carga de desconexión junto al Fronius (opcional): corta la salida del inversor cerca de él")
    amps = int((branch or {}).get("ocpd_a") or 0)
    meter_fed = grid_zero and bool(eq.get("monitoring"))
    n_breakers = 2 if meter_fed else 1
    where = "Centro de carga de desconexión"
    if amps:
        row = _find("breaker_panel", amps=amps, poles=2)
        c.add(row, n_breakers, name=f"Breaker de {amps}A 2 polos, marca CH /SD", section="Generales", group="Interconexión",
              sibling=_find("breaker_panel", amps=40, poles=2), where=where,
              note=("1 para la salida del Fronius" + (" + 1 para alimentar el Smart Meter" if meter_fed else "")) + f", del mismo amperaje ({amps} A)")
    else:
        c.add(None, n_breakers, name="Breaker 2 polos para centro de carga (amperaje por definir)", section="Generales", group="Interconexión",
              sibling=_find("breaker_panel", amps=40, poles=2), where=where, comment="POR CONFIRMAR AMPERAJE")
    if meter_fed:
        for color in ("negro", "rojo"):
            c.add(_find("cable_thhn", gauge=METER_FEED_GAUGE, color=color), METER_FEED_M, name=f"Cable #{METER_FEED_GAUGE} AWG THHN, CU, color {color}", unit="m",
                  section="Generales", group="Cable", sibling=_find("cable_thhn", gauge=METER_FEED_GAUGE, color="negro"),
                  where="Centro de carga → Smart Meter", note=f"{METER_FEED_M} m de #{METER_FEED_GAUGE} para alimentar el Smart Meter desde su breaker del centro de carga")


# ── Public API ─────────────────────────────────────────────────────────────────

def build_list(eq: dict, wiring_ctx: dict, spec: dict | None = None, base_layout: dict | None = None, system_type: str | None = None) -> dict:
    """{'lines': [...], 'pending': [...], 'layout': {...}, 'options': {...}, 'counts': {...}}.

    `wiring_ctx` is `og_wiring.build_context(...)`; `spec` the project's tech_spec (edits live in
    spec["materials"]). `base_layout` is the layout answered in the wizard; what the project saved in
    its Lista tab wins over it, key by key. Lines are in master-list order, new lines at the end of
    their group."""
    mat = ((spec or {}).get("materials")) or {}
    grid_zero = system_type == "grid_zero"
    if grid_zero:
        eq = grid_zero_equipment(eq)
    layout = {**DEFAULT_LAYOUT, **clean_layout(base_layout), **clean_layout(mat.get("layout"))}
    opts = {**DEFAULT_OPTIONS, **(mat.get("options") or {})}
    coupling = wiring_ctx.get("coupling") or {}
    layout = with_default_rows(layout, string_count(eq, coupling))
    branches = wiring_ctx.get("branches") or []
    pending: list[str] = []

    c = Collector()
    _equipment(c, eq, coupling, wiring_ctx.get("lengths"), grid_zero)
    if grid_zero:
        _interconnection(c, eq, branches)
    else:
        _system(c, eq, coupling, wiring_ctx)
    _mounting(c, eq, layout, pending)
    _project_kit(c, eq, coupling, layout, pending, grid_zero)
    _pv_connectors(c, eq, coupling)
    if wiring_ctx.get("ready"):
        _cables(c, branches)
        _protections(c, branches, opts)
        _disconnect(c, wiring_ctx, eq, grid_zero)
        _conduit(c, branches, opts)
    else:
        pending.append("El cableado todavía no se puede dimensionar (" + (wiring_ctx.get("reason") or "faltan datos del diseño")
                       + "): cables, protecciones y tubería quedan fuera.")
    pending.append(("Lo que no sale del diseño se agrega con «Agregar línea». "
                    + ("" if grid_zero else "El sub-panel de cargas críticas lo pone el propietario o constructor.")).strip())

    lines = apply_edits(list(c.lines.values()), mat)
    return {"lines": lines, "pending": pending, "layout": layout, "options": opts,
            "counts": layout_counts(eq.get("panel") or {}, int(eq.get("panel_count") or 0), layout)}


def _finish(line: dict) -> dict:
    qty = line["qty"]
    line["qty"] = int(qty) if float(qty).is_integer() else round(qty, 1)
    line["comment"] = " · ".join(dict.fromkeys(line["wheres"] + line["comments"]))
    line["note"] = "; ".join(line["notes"])
    return line


def apply_edits(lines: list[dict], mat: dict) -> list[dict]:
    """Computed lines + the user's quantity/comment overrides + hand-added lines."""
    overrides, extras = mat.get("overrides") or {}, mat.get("extras") or []
    out = []
    for line in lines:
        _finish(line)
        line["computed_qty"], line["computed_comment"] = line["qty"], line["comment"]
        line["edited"] = False
        ov = overrides.get(line["id"]) or {}
        if "qty" in ov:
            line["qty"], line["edited"] = ov["qty"], True
        if ov.get("comment"):
            line["comment"], line["edited"] = ov["comment"], True
        out.append(line)
    for i, ex in enumerate(extras):
        row = _BY_KEY.get(ex.get("key")) if ex.get("key") else None
        name = row["name"] if row else ex.get("name") or "Línea manual"
        out.append({
            "id": "m:" + str(ex.get("id") or i), "name": name, "unit": row["unit"] if row else ex.get("unit") or "un",
            "section": row["section"] if row else ex.get("section") or "Generales", "group": row["group"] if row else ex.get("group"),
            "qty": ex.get("qty") or 0, "computed_qty": None, "edited": False, "in_master": bool(row), "source": "manual",
            "comment": ex.get("comment") or "", "note": "agregada a mano", "manual": True,
            "order": (_SECTION_RANK.get(row["section"] if row else ex.get("section") or "Generales", 9),
                      _INDEX[row["key"]] if row else 10_000, 1000 + i),
        })
    out.sort(key=lambda line: line["order"])
    return out


def catalog_options() -> list[dict]:
    """The master list as {key, name, section, group} for the 'add a line' picker."""
    return [{"key": r["key"], "name": r["name"], "section": r["section"], "group": r["group"] or ""} for r in CATALOG]
