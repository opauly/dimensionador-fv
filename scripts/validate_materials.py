"""Checks for the materials list engine, its xlsx export and the unifilar configuration.

    python3 scripts/validate_materials.py

Reference design: María José Castro (16 x SUN600, 2 x MultiPlus-II 48/5000 120 V, 4 x Fidus, Fronius
Primo 10.0-1, Ekrano). Where her real purchase (Proforma 180-2026, Protel Z12-010970, her Solicitud de
materiales) gives a number, the check says so; known differences are asserted as differences so a rule
change that closes (or widens) the gap is noticed.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl  # noqa: E402

from materials import engine  # noqa: E402
from materials.catalog import CATALOG  # noqa: E402
from materials.export_xlsx import build_workbook  # noqa: E402
from unifilar import config_builder as CB  # noqa: E402
from webapp.wizard_steps import og_coupling, og_wiring  # noqa: E402

fails: list[str] = []


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


PANEL = {"wp": 600, "voc": 48.15, "vmp": 40.46, "isc": 15.86, "imp": 14.95, "brand": "Sunergy", "model": "SUN600-66MDH12RS",
         "width_m": 1.134, "height_m": 2.382}
FRONIUS = {"id": "fr10", "type": "string_inverter", "brand": "Fronius", "model": "Primo 10.0-1", "kw": 10.0, "mppt_channels": 2,
           "vmax": 1000.0, "vmax_mppt": 800.0, "vmin_mppt": 200.0, "imax_mppt": 27.0}
MP = {"id": "mp5", "brand": "Victron Energy", "model": "MultiPlus-II 48/5000/70-95", "kw": 5.0, "output_v": 120.0,
      "ac_out_rated_a": 115.0, "ac_input_current_max_a": 95.0, "efficiency_pct": 96.0, "type": "hybrid"}
EQ = {"panel": PANEL, "panel_count": 16, "battery": {"brand": "Pylontech", "model": "Fidus", "voltage_v": 51.2, "capacity_kwh": 4.97},
      "battery_bank": {"battery_count": 4}, "inverter": MP, "inverter_qty": 2, "monitoring": {"brand": "Victron Energy", "model": "Ekrano GX"},
      "n_strings": 2, "panels_per_string": 8, "array": {"area_m2": 43.2}}
og_coupling.pv_inverter_options = lambda: [FRONIUS]
og_wiring._fresh_inverter = lambda eq: eq.get("inverter") or {}
og_wiring._ac_summary = lambda blob, qty: ({"ac_in": {"breaker_a": 190}}, 120.0, False, {"total_installed_kw": 13.25, "total_demand_kw": 8.8})
BLOB = {"meta": {"system_type": "hybrid"}, "equipment": EQ, "scratch": {"coupling": {"mode": "ac"}},
        "site": {"city": "Carrillo", "province": "Guanacaste"}}
CTX = og_wiring.build_context(BLOB)
LAYOUT = {"materials": {"layout": {"rows": 2, "orientation": "portrait"}}}


def lines(spec=None, ctx=CTX):
    r = engine.build_list(EQ, ctx, spec)
    return r, {ln["name"]: ln for ln in r["lines"]}


# ── Catalog ────────────────────────────────────────────────────────────────────
check("catalog has the 171 master lines", len(CATALOG), 171)
check("catalog keys are unique", len({r["key"] for r in CATALOG}), 171)
check("every cable / conduit / fuse pattern is tagged", sum(1 for r in CATALOG if r.get("kind")), 94)

# ── Without a roof layout each string is one row; with no strings either, the mounting is not guessed ──
r, by = lines()
check("no layout -> one string per row: rails are calculated", by["Rieles (largueros)"]["qty"], 9)
check("no layout but strings known -> nothing pending about the layout", any("layout del techo" in p for p in r["pending"]), False)
r, by = lines(ctx={**CTX, "coupling": {**CTX["coupling"], "strings": 0}})
check("no layout and no strings -> no rails", "Rieles (largueros)" in by, False)
check("no layout and no strings -> pending note", any("layout del techo" in p for p in r["pending"]), True)

# ── María José, 2 rows of 8 in portrait ─────────────────────────────────────────
r, by = lines(LAYOUT)
q = lambda n: by[n]["qty"] if n in by else None  # noqa: E731
check("layout: rows of 8 modules, 9.21 m, 4 rail lines, 8 rails", (r["counts"]["per_row"], r["counts"]["row_len_m"], r["counts"]["rail_lines"], r["counts"]["rails"]), (8, 9.21, 4, 8))
check("rails 9 (she bought 9)", q("Rieles (largueros)"), 9)
check("rail grounding lugs 8 (she bought 8)", q("Tierras para rieles"), 8)
check("splices 4 (she bought 8: known gap)", q("Uniones de riel"), 4)
check("mid clamps 30 (she bought 32)", q("Midclamp"), 30)
check("end clamps 9 (she bought 10)", q("Endclamp"), 9)
check("MC4 8 (she bought 8)", q("MC4"), 8)
check("SOLAR black / red by the metre: 2 strings x 15 m + 10 % = 35 m each", (q("Cable #10 AWG - SOLAR negro"), q("Cable #10 AWG - SOLAR rojo")), (35, 35))
check("panels 16, Multis 2, Fidus 4, Ekrano 1", (q("Paneles solares"), q("Inversor Multiplus 5000 120V"), q("Batería Pylontech Fidus"), q("Ekrano GX")), (16, 2, 4, 1))
check("Pylontech cable sets 4 (she bought 4)", q("Cables para Pylontech"), 4)
check("Lynx bars 2 / bolts 12 (she bought 3 bars / 12 bolts: open question)", (q("Lynx Power In"), q("Roscas para Lynx Power In")), (2, 12))
check("UTP 4 / VE.CAN 1 (she bought 4 / 1)", (q("Cable UTP normal"), q("Cable UTP tipo A")), (4, 1))
check("tape: one roll per colour used (4)", sum(1 for n in by if n.startswith("Tape color")), 4)
check("Fronius is a new line, not in the master list", (q("Inversor Fronius Primo 10.0-1"), by["Inversor Fronius Primo 10.0-1"]["in_master"]), (1, False))
check("string breaker follows the design: 32 A DC x2 (in the master list)", (q("Breaker DC para riel DIN 32A 2P"), by["Breaker DC para riel DIN 32A 2P"]["in_master"]), (2, True))
check("AC in: two 120 V Multis share one 2-pole 90 A breaker", q("Breaker AC para riel DIN 90A 2P"), 1)
check("AC out 70 A 2P x1, Fronius 60 A 2P x1", (q("Breaker AC para riel DIN 70A 2P"), q("Breaker AC para riel DIN 60A 2P")), (1, 1))
check("battery-to-Multi fuses: Mega 125 A x2 (4000 W continuous / 0.96 / 51.2 V x 1.25 = 102 A) + battery fuses by definir x4",
      (q("Fusible Mega 125A"), q("Fusible Mega de batería (calibre por definir)")), (2, 4))
check("ground by breaker (T250.122), one per raceway: #8 green = AC out 10 m + AC in 10 m, +10 % -> 25", q("Cable #8 AWG THHN, CU, color verde"), 25)
check("ground by breaker: #10 green = PV 15 m + Fronius 10 m (32 A and 60 A breakers), +10 % -> 30", q("Cable #10 AWG THHN, CU, color verde"), 30)
check("no #3 AWG cable is asked for (dealers do not stock it): AC in uses #2", ("Cable #3 AWG THHN, CU, color negro" in by, "Cable #2 AWG THHN, CU, color negro" in by), (False, True))
check("#4 black THHN is a master line, 15 m", (by["Cable #4 AWG THHN, CU, color negro"]["in_master"], q("Cable #4 AWG THHN, CU, color negro")), (True, 15))
check("heat-shrink for the DC lugs (#2 AWG), 1 m minimum", q("Termoencogible para cable #2 rojo"), 1)
check("battery-side DC runs are not piped (no 1 1/4 in conduit from them)", any("Tuberia 1 1/4" in n and by[n]["comment"].startswith("Baterías") for n in by), False)
check("PVC glue 1 when PVC is used", q("Pegamento para PVC"), 1)

# ── Options ────────────────────────────────────────────────────────────────────
spec32 = {"materials": {**LAYOUT["materials"], "options": {"string_breaker_a": 32}}}
_, by32 = lines(spec32)
check("string breaker 32 A (her choice) lands on the master row", (by32["Breaker DC para riel DIN 32A 2P"]["in_master"], by32["Breaker DC para riel DIN 32A 2P"]["qty"]), (True, 2))
specE = {"materials": {**LAYOUT["materials"], "options": {"conduit_material": {"ac_out": "EMT", "ac_in": "EMT"}}}}
_, byE = lines(specE)
check("EMT for the AC runs: EMT tubes + pressure connectors appear", ('Tuberia 1 1/4" / EMT' in byE, 'Conector de presión 1 1/4" EMT' in byE), (True, True))

# ── Edits survive regeneration ─────────────────────────────────────────────────
key = by["Midclamp"]["id"]
specEd = {"materials": {**LAYOUT["materials"], "overrides": {key: {"qty": 32}}, "extras": [
    {"id": "a1", "key": "gabinetes-cajas-registros-gabinete-metalico-50x40x20", "qty": 1, "comment": "Breaker DC / Cerbo"},
    {"id": "a2", "key": None, "name": "Caja de paso 4x4", "qty": 2, "unit": "un"}]}}
_, byEd = lines(specEd)
check("override keeps her 32 mid clamps and remembers the computed 30", (byEd["Midclamp"]["qty"], byEd["Midclamp"]["computed_qty"], byEd["Midclamp"]["edited"]), (32, 30, True))
check("extra from the master list keeps its section", byEd["Gabinete metálico 50x40x20"]["section"], "Generales")
check("free-text extra is a new line", (byEd["Caja de paso 4x4"]["qty"], byEd["Caja de paso 4x4"]["in_master"]), (2, False))

# ── xlsx export ────────────────────────────────────────────────────────────────
ws = openpyxl.load_workbook(io.BytesIO(build_workbook(r["lines"]))).active
rows = list(ws.iter_rows(values_only=True))
check("xlsx header like the master sheet", rows[0][:5], ("Detalle", "Cantidad", "Unidad", "Comentarios", "Avolta"))
check("xlsx dealer columns and Bodega left empty", all(v is None for row in rows[1:] for v in row[4:]), True)
check("xlsx starts a section with the master's header row", rows[1][:3], ("Paneles solares", "Cantidad", "Unidad"))
check("xlsx holds only lines with a quantity", all(row[1] for row in rows[1:] if isinstance(row[1], (int, float)) or row[1] is None and False), True)

# ── Unifilar configuration ─────────────────────────────────────────────────────
project = {"system_type": "hybrid", "client_name": "María José Castro"}
d = {"eq": EQ, "wiring": CTX, "blob": BLOB}
cfg, prob = CB.build_config(project, d, {})
check("both questions block the drawing until answered", (cfg, len(prob["blockers"])), (None, 2))
ans = {"export": "grid_zero", "lynx": "power_in"}
cfg, prob = CB.build_config(project, d, ans)
check("drawn from the sized design: string breaker / wire", (cfg["pv"]["string_breaker"], cfg["pv"]["dc_wire"]), ("32 A 2P DC", "#10 AWG SOLAR"))
check("Q3 Fronius breaker and conductors", (cfg["fronius"]["ac_breaker"], cfg["fronius"]["ac_conductors"]), ("2P 60 A", ["L1 #6 AWG negro", "L2 #6 AWG rojo", "T #10 AWG verde"]))
check("Q1 from the manual limit: 2P 90 A on #2 AWG (no #3 sold)", (cfg["multis"]["ac_in_breaker"], cfg["multis"]["ac_in_conductors"][0]), ("2P 90 A", "L1 #2 AWG negro"))
check("DC to the Multis uses the sized cable", (cfg["multis"]["dc_pos"], cfg["multis"]["dc_neg"]), ("+ #2 AWG rojo", "- #2 AWG negro"))
check("layout 2 strings x 8, label and title", (cfg["pv"]["strings"], cfg["pv"]["modules_per_string"], cfg["project"]["name"]), (2, 8, "Proyecto María José Castro en Carrillo, Guanacaste"))
cfg32, _ = CB.build_config(project, d, ans, string_breaker_a=32)
check("her 32 A string breaker reaches the drawing", cfg32["pv"]["string_breaker"], "32 A 2P DC")
check("only drawable characters in the labels", all(ch not in str(cfg) for ch in "→−≥≤"), True)
check("engineering notes stay out of the config", "warnings" in prob and "warnings" not in cfg, True)
check("review list mentions the 95 A input limit", any("95 A" in w["text"] for w in prob["warnings"]), True)
CC = {"brand": "Victron Energy", "model": "SmartSolar MPPT 250/100", "type": "MPPT", "vin_max": 250.0, "imax_in": 35.0, "imax_out": 100.0}
EQ_DC = {**EQ, "charge_controller": CC, "charge_controller_qty": 1, "panels_per_string": 8, "n_strings": 2}
BLOB_DC = {"meta": {"system_type": "hybrid"}, "equipment": EQ_DC, "scratch": {}, "site": BLOB["site"]}
dc_ctx = og_wiring.build_context(BLOB_DC)
check("DC coupling picks the off-grid drawing", CB.drawing_kind(project, dc_ctx), "off_grid")
d_dc = {"eq": EQ_DC, "wiring": dc_ctx, "blob": BLOB_DC}
_, nolynx = CB.build_config(project, d_dc, {})
check("off-grid drawing asks the Lynx question but not the injection one", [("Bus DC" in b) for b in nolynx["blockers"]], [True])
cfg_dc, prob_dc = CB.build_config(project, d_dc, {"lynx": "power_in"})
check("off-grid config: 2 inverters, 1 controller, 4 batteries, no grid-in without an AC-in run",
      (cfg_dc["kind"], cfg_dc["multis"]["qty"], cfg_dc["controllers"]["count"], cfg_dc["battery"]["count"], bool(cfg_dc["grid_in"]) == bool(CB._branch(dc_ctx["branches"], "ac_in"))),
      ("off_grid", 2, 1, 4, True))
check("off-grid controller output cable is the sized one", cfg_dc["controllers"]["out_pos"].startswith("+ #"), True)
_, dist = CB.build_config(project, d_dc, {"lynx": "power_in_distributor"})
check("off-grid drawing refuses the Distributor variant", any("Distributor" in b for b in dist["blockers"]), True)
out_dc = io.BytesIO()
from unifilar.generate_unifilar import build as _build_dc  # noqa: E402
_build_dc(cfg_dc, out_dc)
check("off-grid PDF renders", out_dc.getvalue()[:4], b"%PDF")
cfg_m, _ = CB.build_config(project, {"eq": {**EQ_DC, "energy_meter": {"brand": "Victron Energy", "model": "VM-3P75CT"}}, "wiring": dc_ctx, "blob": BLOB_DC}, {"lynx": "power_in"})
check("energy meter reaches the off-grid drawing", (cfg_m["meter"] or {}).get("title"), "MEDIDOR VM-3P75CT")
cfg_h, _ = CB.build_config(project, {"eq": {**EQ, "energy_meter": {"brand": "Victron Energy", "model": "VM-3P75CT"}}, "wiring": CTX, "blob": BLOB}, ans)
check("energy meter reaches the hybrid AC drawing", (cfg_h["meter"] or {}).get("title"), "MEDIDOR VM-3P75CT")
check("no meter selected: nothing drawn", (CB.build_config(project, d, ans)[0] or {}).get("meter"), None)
from unifilar.generate_unifilar import build  # noqa: E402
out = io.BytesIO()
build(cfg, out)
check("the PDF renders from the config", out.getvalue()[:4], b"%PDF")

# Roof layout answered in the wizard (blob scratch) feeds the list; the project's own answer wins key by key.
from materials import engine as ME  # noqa: E402
check("clean_layout drops blanks and junk", ME.clean_layout({"rows": "", "orientation": "diagonal", "rail_len_m": "-1", "foot_spacing_m": "1,2"}), {"foot_spacing_m": 1.2})
check("layout_from_blob reads scratch.roof_layout", ME.layout_from_blob({"scratch": {"roof_layout": {"rows": "2", "orientation": "landscape"}}}), {"rows": 2, "orientation": "landscape"})
wiz = {"rows": 2, "orientation": "landscape"}
check("wizard layout reaches the list", ME.build_list(EQ, CTX, {}, wiz)["layout"]["rows"], 2)
check("project layout wins over the wizard's", ME.build_list(EQ, CTX, {"materials": {"layout": {"rows": 3}}}, wiz)["layout"]["rows"], 3)
check("no layout: one string per row (2 strings -> 2 rows, 8 modules each)", (ME.build_list(EQ, CTX, {}, None)["layout"]["rows"], ME.build_list(EQ, CTX, {}, None)["counts"]["per_row"]), (2, 8))
_nostr = {**CTX, "coupling": {**CTX["coupling"], "strings": 0}}
check("no layout and no strings leaves mounting pending", any("layout del techo" in x for x in ME.build_list(EQ, _nostr, {}, None)["pending"]), True)
check("a row count typed by the user wins over the strings", ME.build_list(EQ, CTX, {"materials": {"layout": {"rows": 4}}}, None)["layout"]["rows"], 4)
_r = ME.layout_counts(PANEL, 16, {"rows": 2, "orientation": "portrait", "rail_len_m": 4.7, "foot_spacing_m": 1.0})
check("string of 8 modules is 9.21 m: 2 rails of 4.7 m + 1 splice per rail line, 4 rail lines", (_r["row_len_m"], _r["rails"], _r["splices"]), (9.21, 8, 4))

# Batch-1 rules: one enclosure (size to confirm), one SPD, roof sealant by feet; no roof screws, no sub-panel.
_res = ME.build_list(EQ, CTX, {"materials": {"layout": {"rows": 2}}}, None)
_by = {ln["name"]: ln for ln in _res["lines"] if ln["qty"]}
check("enclosure 50x40x20 x1 flagged to confirm", (_by["Gabinete metálico 50x40x20"]["qty"], _by["Gabinete metálico 50x40x20"]["comment"]), (1, "POR CONFIRMAR MEDIDA"))
check("one surge protector", _by["Supresor de Picos SDSA 1175"]["qty"], 1)
check("sealant: 1 tube per 20 feet", _by["Silicon 3M (especificar color según color de las láminas del techo)"]["qty"], 3)
check("no roof screws on the list", any("Tornillo de techo" in n for n in _by), False)
check("no sub-panel board on the list", any("Tablero NEMA" in n for n in _by), False)

# Batch-2 rules: Chint DC box, 4x4 duct + 2 caps, EMT stubs to the inverters, monitoring outlet kit, 1 tie pack, 1" solar conduit.
check("Chint DC 5-space box x1", _by["Centro de carga Chint DC 5 espacios"]["qty"], 1)
check("duct 4x4 x1 + 2 end caps", (_by["Ducto metálico cuadrado 4x4"]["qty"], _by["Tapas para ducto metálico 4x4"]["qty"]), (1, 2))
check("PG-21 cable glands x2", _by["Manguito prensacable de poliamida gris PG-21 (incluye contratuerca)"]["qty"], 2)
check("EMT stubs to the 2 inverters: 2 tubes, 8 pressure connectors", (_by['Tuberia 1" / EMT']["qty"], _by['Conector de presión 1" EMT']["qty"]), (2, 8))
check("monitoring outlet kit", [_by[n]["qty"] for n in ("Breaker 20A 1 polo CH (toma de monitoreo)", "Toma doble 15A 125V", "Placa de acero inoxidable para toma doble", 'Caja rectangular de intemperie 3 huecos 1/2"')], [1, 1, 1, 1])
check("monitoring circuit: #12 red / green / white, 15 m each", [_by[f"Cable #12 AWG THHN, CU, color {c}"]["qty"] for c in ("rojo", "verde", "blanco")], [15, 15, 15])
check("ties: one pack", _by["Gasas plásticas #8 (Negras)"]["qty"], 1)
check("solar strings go in at least 1 in conduit", [b["conduit"]["trade"] for b in CTX["branches"] if b.get("key") == "pv_strings"], ["1"])
check("no 3 AWG anywhere in the sized branches", any(b.get("ugc") in ("3", "1") for b in CTX["branches"]), False)

# Batch-5 rules: DIN rail, DIN terminal and strut x1 always; energy meter chosen in Equipos brings 2 CTs (size to verify) and 1 UTP.
check("DIN rail, DIN terminal and strut x1", [_by[n]["qty"] for n in ("Riel DIN perforado 35x15mm", "Terminal para riel din", "Riel strut perfil bajo")], [1, 1, 1])
check("no plexo box and no PVC pull box by default", any(n.startswith("Caja plexo") or n == "Caja de registro PVC" for n in _by), False)
check("no meter selected: no meter, no CTs", any("VM-3P75CT" in n or "Transformador de Corriente" in n for n in _by), False)
_utp0 = _by["Cable UTP normal"]["qty"]
_EQM = {**EQ, "energy_meter": {"brand": "Victron Energy", "model": "VM-3P75CT"}}
_resm = ME.build_list(_EQM, CTX, {"materials": {"layout": {"rows": 2}}}, None)
_bym = {ln["name"]: ln for ln in _resm["lines"] if ln["qty"]}
check("meter VM-3P75CT x1 on the Victron section", (_bym["Medidor VM-3P75CT"]["qty"], _bym["Medidor VM-3P75CT"]["section"]), (1, "Victron Energy"))
check("2 current transformers flagged to verify size", (_bym["Transformador de Corriente 100A:333mV"]["qty"], _bym["Transformador de Corriente 100A:333mV"]["comment"]), (2, "POR VERIFICAR TAMAÑO"))
check("meter adds no short UTP, it brings cat6e by metre", (_bym["Cable UTP normal"]["qty"], "Cable de red Ethernet cat6e" in _bym), (_utp0, True))
_run = CTX["lengths"]["ac_in_m"]
check("cat6e as long as the cabinet -> panel run (+waste, 5 m steps)", _bym["Cable de red Ethernet cat6e"]["qty"], ME._ceil_to(_run * (1 + ME.WASTE), ME.CABLE_STEP_M))
check("no meter: no cat6e", "Cable de red Ethernet cat6e" in _by, False)

# Batch-6 rules: Fidus fuse 125 A (max charge 100 A); Grid Zero list has no Victron / batteries / Lynx and carries the interconnection items.
_EQF = {**EQ, "battery": {**EQ["battery"], "fuse_a": 125, "max_charge_a": 100}}
_byf = {ln["name"]: ln for ln in ME.build_list(_EQF, CTX, {"materials": {"layout": {"rows": 2}}}, None)["lines"] if ln["qty"]}
check("Fidus fuse: 125 A, 4 batteries + 2 battery-to-Multi runs share the same Mega 125 A line", _byf["Fusible Mega 125A"]["qty"], 6)
check("no 'por definir' fuse once the battery has its fuse", any("calibre por definir" in n for n in _byf), False)
_PRIMO = {"brand": "Fronius", "model": "Primo 8.2-1", "kw": 8.2, "ac_output_current_a": 34.2, "max_ocpd_a": 45}
_GZ = {"panel": PANEL, "inverter": _PRIMO, "chosen_scenario": {"total_panels": 12, "strings": 2, "panels_per_string": 6}}
_gz = ME.build_list(_GZ, {"ready": False, "reason": "x", "branches": []}, {}, None, "grid_zero")
_bg = {ln["name"]: ln for ln in _gz["lines"] if ln["qty"]}
check("grid zero: panels and inverter come from the chosen scenario", (_bg["Paneles solares"]["qty"], _bg["Inversor Fronius Primo 8.2-1"]["qty"]), (12, 1))
check("grid zero: 45 A breaker (125 % of 34.2 A) for the meter base, base x1, padlock x1",
      (_bg["Breaker 45A compatible con base para medidor"]["qty"], _bg["Base para medidor monofásica con interruptor principal tipo parche, clase 100 (Combo base)"]["qty"], _bg["Candado pequeño para base medidor"]["qty"]), (1, 1, 1))
check("grid zero: no Victron, Lynx, fuses, duct, cabinet or monitoring kit", any(("Lynx" in n or "Fusible" in n or "Ducto" in n or "Gabinete" in n or "toma de monitoreo" in n or "Victron" in ln["section"]) for n, ln in _bg.items()), False)
check("grid zero: still carries rails, Chint DC box and SPD", all(n in _bg for n in ("Rieles (largueros)", "Centro de carga Chint DC 5 espacios", "Supresor de Picos SDSA 1175")), True)
_gz30 = ME.build_list({**_GZ, "inverter": {**_PRIMO, "ac_output_current_a": 20.8, "max_ocpd_a": 30}}, {"ready": False, "branches": []}, {}, None, "grid_zero")
check("grid zero: a 20.8 A inverter takes the master 30 A breaker line", any(ln["name"] == "Breaker 30A compatible con base para medidor" and ln["in_master"] for ln in _gz30["lines"] if ln["qty"]), True)
check("hybrid list has no interconnection base", any("Base para medidor" in n for n in _by), False)

# ── Grid Zero: NEC wiring, list and drawing ────────────────────────────────────
from webapp.wizard_steps import gz_wiring  # noqa: E402
GZ_BLOB = {"meta": {"system_type": "grid_zero"}, "site": BLOB["site"],
           "equipment": {"panel": PANEL, "inverter": FRONIUS, "chosen_scenario": {"total_panels": 16, "strings": 2, "panels_per_string": 8, "voc_total": 385.0}}}
GZ = gz_wiring.build_context(GZ_BLOB)
_gb = {b["key"]: b for b in GZ["branches"]}
check("grid zero wiring: four runs (strings, DC breakers -> inverter, inverter -> generation base, generation base -> consumption base)", list(_gb), ["pv_strings", "pv_dc_inv", "gz_ac", "gz_link"])
check("grid zero: DC breakers -> inverter has no breaker of its own", _gb["pv_dc_inv"]["ocpd_a"], None)
check("grid zero: string run is #10 solar in 1 in conduit", (_gb["pv_strings"]["ugc"], _gb["pv_strings"]["conduit"]["trade"]), ("10", "1"))
check("grid zero: meter-base breaker is 125 % of the inverter current, capped by the manufacturer", (_gb["gz_ac"]["ocpd_a"], _gb["gz_ac"].get("max_ocpd_a")), (60, 60))
GZ_EQ = GZ_BLOB["equipment"]
_gzl = {ln["name"]: ln for ln in engine.build_list(GZ_EQ, GZ, {}, None, "grid_zero")["lines"] if ln["qty"]}
check("grid zero list: DC string breakers counted once (2)", _gzl["Breaker DC para riel DIN 32A 2P"]["qty"], 2)
check("grid zero list: the AC breaker is the meter-base one, not a DIN breaker", (any(n.startswith("Breaker AC para riel DIN") for n in _gzl), _gzl["Breaker 60A compatible con base para medidor"]["qty"]), (False, 1))
check("grid zero list: solar cable for both DC runs and 240 V cable to the meter base", ("Cable #10 AWG - SOLAR rojo" in _gzl, any("THHN" in n and "negro" in n for n in _gzl)), (True, True))
cfg_gz, prob_gz = CB.build_config({"system_type": "grid_zero", "client_name": "Prueba"}, {"eq": GZ_EQ, "wiring": GZ, "blob": GZ_BLOB}, {})
check("grid zero drawing needs no questions", (cfg_gz["kind"], prob_gz["blockers"]), ("grid_zero", []))
check("grid zero drawing: base breaker and strings from the sized design", (cfg_gz["base"]["breaker"], cfg_gz["pv"]["strings"], cfg_gz["pv"]["string_breaker"]), ("2P 60 A", 2, "32 A 2P DC"))
out_gz = io.BytesIO()
_build_dc(cfg_gz, out_gz)
check("grid zero PDF renders", out_gz.getvalue()[:4], b"%PDF")

# ── Batch 8: one breaker per string in DC-coupled systems, abbreviated drawings for many units ─────────────────
_dcb = {b["key"]: b for b in dc_ctx["branches"]}
check("DC-coupled wiring: one breaker per string (2 runs), the run to the controller has none", (_dcb["pv_strings"]["qty"], _dcb["pv_strings"]["ocpd_a"] is not None, _dcb["pv_cc"]["ocpd_a"]), (2, True, None))
EQ_DC4 = {**EQ_DC, "n_strings": 4, "charge_controller_qty": 2}
BLOB_DC4 = {**BLOB_DC, "equipment": EQ_DC4}
dc4 = og_wiring.build_context(BLOB_DC4)
_dc4l = {ln["name"]: ln for ln in engine.build_list(EQ_DC4, dc4, {}, None)["lines"] if ln["qty"]}
check("DC-coupled list: 4 strings on 2 controllers -> 4 string breakers (not 2)", _dc4l["Breaker DC para riel DIN 32A 2P"]["qty"], 4)
check("DC-coupled list: the strings -> breakers and breakers -> controller runs both carry solar cable", sum(ln["qty"] for n, ln in _dc4l.items() if "SOLAR" in n) > 0, True)
from unifilar.generate_unifilar import _slots  # noqa: E402
check("up to 4 units are all drawn", _slots(4), [(0, 1), (1, 2), (2, 3), (3, 4)])
check("8 units: #1, #2, ellipsis, #8", _slots(8), [(0, 1), (1, 2), (2, None), (3, 8)])
EQ_BIG = {**EQ_DC4, "inverter_qty": 4, "battery_bank": {"battery_count": 8}}
d_big = {"eq": EQ_BIG, "wiring": og_wiring.build_context({**BLOB_DC4, "equipment": EQ_BIG}), "blob": {**BLOB_DC4, "equipment": EQ_BIG}}
cfg_big, prob_big = CB.build_config(project, d_big, {"lynx": "power_in"})
check("4 inverters + 8 batteries + 4 strings on 2 controllers are drawable", (prob_big["blockers"], cfg_big["multis"]["qty"], cfg_big["battery"]["count"]), ([], 4, 8))
check("Lynx bars follow the input count (8 + 4 + 2 = 14 -> 4)", cfg_big["battery"]["lynx_bars"], 4)
check("abbreviated-drawing note is shown", any("abreviado" in w["text"] for w in prob_big["warnings"]), True)
out_big = io.BytesIO()
_build_dc(cfg_big, out_big)
check("the abbreviated drawing renders", out_big.getvalue()[:4], b"%PDF")
cfg_h8 = {**cfg_h, "battery": {**cfg_h["battery"], "count": 8}}
out_h8 = io.BytesIO()
build(cfg_h8, out_h8)
check("AC-coupled hybrid with 8 batteries renders abbreviated", out_h8.getvalue()[:4], b"%PDF")

# ── Batch 9: Fronius Smart Meter + current transformers, interconnection cable, controllers with an ellipsis ───
from calculations.meter_cts import ct_count  # noqa: E402
SM = {"id": "sm", "brand": "Fronius", "model": "Smart Meter WR 100-600 V-3", "uses_cts": True}
check("CTs: one per phase (split-phase 2, three-phase 3), none for a meter without CTs",
      (ct_count(SM, _PRIMO), ct_count(SM, {**_PRIMO, "phase": "three"}), ct_count({"model": "Smart Meter 63A-3"}, _PRIMO)), (2, 3, 0))
check("CTs: a design saved before the column existed is still recognised by its model", ct_count({"model": "Smart Meter WR 100-600 V-3"}, _PRIMO), 2)
_gsm = {ln["name"]: ln for ln in ME.build_list({**_GZ, "monitoring": SM}, {"ready": False, "branches": []}, {}, None, "grid_zero")["lines"] if ln["qty"]}
check("grid zero list: Fronius Smart Meter x1 + 2 current transformers to verify", (_gsm["Fronius Smart Meter WR 100-600 V-3"]["qty"], _gsm["Transformador de Corriente 100A:333mV"]["qty"], _gsm["Transformador de Corriente 100A:333mV"]["comment"]), (1, 2, "POR VERIFICAR TAMAÑO"))
check("grid zero list: no CTs without the Smart Meter", "Transformador de Corriente 100A:333mV" in {ln["name"] for ln in _gz["lines"] if ln["qty"]}, False)
check("grid zero wiring: the link run has the same conductors as the generation-base run and no breaker of its own",
      (_gb["gz_link"]["ugc"] == _gb["gz_ac"]["ugc"], _gb["gz_link"]["ocpd_a"]), (True, None))
GZ_L = gz_wiring.build_context(GZ_BLOB, {"gz_link_m": 12})
check("grid zero wiring: the link length is editable", {b["key"]: b["length_m"] for b in GZ_L["branches"]}["gz_link"], 12)
check("grid zero list: the link carries 240 V cable (its own metres)", any("Base de generación → base de consumo" in w for ln in engine.build_list(GZ_EQ, GZ_L, {}, None, "grid_zero")["lines"] for w in ln.get("wheres") or []), True)
check("grid zero drawing: link conductors reach the config", len(cfg_gz["base"]["link_conductors"] or []), 3)
EQ_CC6 = {**EQ_DC, "n_strings": 12, "charge_controller_qty": 6}
BLOB_CC6 = {**BLOB_DC, "equipment": EQ_CC6}
d_cc6 = {"eq": EQ_CC6, "wiring": og_wiring.build_context(BLOB_CC6), "blob": BLOB_CC6}
cfg_cc6, prob_cc6 = CB.build_config(project, d_cc6, {"lynx": "power_in"})
check("6 controllers with 12 strings are drawable (abbreviated)", (prob_cc6["blockers"], cfg_cc6["controllers"]["count"], cfg_cc6["pv"]["strings"]), ([], 6, 12))
check("abbreviated note mentions the controllers", any("controladores" in w["text"] and "abreviado" in w["text"] for w in prob_cc6["warnings"]), True)
out_cc6 = io.BytesIO()
_build_dc(cfg_cc6, out_cc6)
check("the 6-controller drawing renders", out_cc6.getvalue()[:4], b"%PDF")
_, prob_few = CB.build_config(project, {**d_cc6, "eq": {**EQ_CC6, "n_strings": 5}}, {"lynx": "power_in"})
check("more controllers than strings is refused", any("al menos un string por controlador" in b for b in prob_few["blockers"]), True)

check("grid zero list: cat6e for the Smart Meter = (Fronius -> base 10 m + base -> base 12 m) x 1.1, in 5 m steps",
      {ln["name"]: ln for ln in ME.build_list({**GZ_EQ, "monitoring": SM}, GZ_L, {}, None, "grid_zero")["lines"] if ln["qty"]}["Cable de red Ethernet cat6e"]["qty"],
      ME._ceil_to((10 + 12) * (1 + ME.WASTE), ME.CABLE_STEP_M))
_gdef = {ln["name"]: ln for ln in ME.build_list({**_GZ, "monitoring": SM}, {"ready": False, "branches": []}, {}, None, "grid_zero")["lines"] if ln["qty"]}
check("grid zero list: without wiring lengths the cat6e still comes (10 + 2 m default)", _gdef["Cable de red Ethernet cat6e"]["qty"], ME._ceil_to((10 + 2) * (1 + ME.WASTE), ME.CABLE_STEP_M))

# ── Batch 10: the list and the drawing must agree (every breaker, device and count the drawing shows is on the list) ──
import re  # noqa: E402
from math import ceil  # noqa: E402


def _amps(text):
    m = re.search(r"(\d+) A", text or "")
    return int(m.group(1)) if m else None


def _list(eq, ctx, kind=None):
    return {ln["name"]: ln for ln in engine.build_list(eq, ctx, {}, None, kind)["lines"] if ln["qty"]}


def _qty(lines, prefix):
    return sum(ln["qty"] for n, ln in lines.items() if n.startswith(prefix))


# AC-coupled hybrid
_lh = _list({**EQ, "energy_meter": {"brand": "Victron Energy", "model": "VM-3P75CT"}}, CTX)
_ch, _ = CB.build_config(project, {"eq": {**EQ, "energy_meter": {"brand": "Victron Energy", "model": "VM-3P75CT"}}, "wiring": CTX, "blob": BLOB}, ans)
check("hybrid AC: Q1, Q2 and Q3 breakers of the drawing are on the list",
      [f"Breaker AC para riel DIN {_amps(x)}A 2P" in _lh for x in (_ch["multis"]["ac_in_breaker"], _ch["subpanel"]["q2"], _ch["fronius"]["ac_breaker"])], [True, True, True])
check("hybrid AC: string breakers of the drawing = list", (_qty(_lh, f"Breaker DC para riel DIN {_amps(_ch['pv']['string_breaker'])}A"), _ch["pv"]["strings"]), (_ch["pv"]["strings"], _ch["pv"]["strings"]))
check("hybrid AC: batteries, Multis and SPD of the drawing are on the list", (_lh["Batería Pylontech Fidus"]["qty"], _lh["Inversor Multiplus 5000 120V"]["qty"], "Supresor de Picos SDSA 1175" in _lh), (_ch["battery"]["count"], 2, True))
check("hybrid AC: one Mega fuse per battery plus one per Multi", _qty(_lh, "Fusible Mega"), _ch["battery"]["count"] + 2)
check("hybrid AC: the Ekrano supply breaker (QDC) is on the list, flagged to confirm", (_qty(_lh, "Breaker DC para riel DIN 16A"), _lh["Breaker DC para riel DIN 16A 2P"]["comment"]), (1, "ALIMENTACIÓN EKRANO/CERBO · POR CONFIRMAR AMPERAJE"))
check("hybrid AC: the meter in the drawing is on the list with its CTs", ("Medidor VM-3P75CT" in _lh, _lh["Transformador de Corriente 100A:333mV"]["qty"]), (True, 2))
# DC-coupled
_ld = _list({**EQ_DC, "energy_meter": {"brand": "Victron Energy", "model": "VM-3P75CT"}}, dc_ctx)
check("DC-coupled: string breakers, controllers, Multis, batteries of the drawing = list",
      (_qty(_ld, "Breaker DC para riel DIN 32A"), _ld["Controlador de carga 250/100"]["qty"], _ld["Inversor Multiplus 5000 120V"]["qty"], _ld["Batería Pylontech Fidus"]["qty"]),
      (cfg_dc["pv"]["strings"], cfg_dc["controllers"]["count"], cfg_dc["multis"]["qty"], cfg_dc["battery"]["count"]))
check("DC-coupled: Lynx bars of the drawing = list", (cfg_dc["battery"]["lynx_bars"], _ld["Lynx Power In"]["qty"]), (ceil((4 + 2 + 1) / 4),) * 2)
check("DC-coupled: AC breakers of the drawing are on the list",
      [f"Breaker AC para riel DIN {_amps(x)}A 2P" in _ld for x in ((cfg_dc["grid_in"] or {}).get("breaker"), cfg_dc["subpanel"]["q2"]) if x], [True, True])
# Grid Zero
_lg = _list({**GZ_EQ, "monitoring": SM}, GZ_L, "grid_zero")
_cgz, _ = CB.build_config({"system_type": "grid_zero", "client_name": "Prueba"}, {"eq": {**GZ_EQ, "monitoring": SM}, "wiring": GZ_L, "blob": GZ_BLOB}, {})
check("grid zero: generation-base breaker, string breakers and SPD of the drawing are on the list",
      (f"Breaker {_amps(_cgz['base']['breaker'])}A compatible con base para medidor" in _lg, _qty(_lg, "Breaker DC para riel DIN 32A"), "Supresor de Picos SDSA 1175" in _lg), (True, _cgz["pv"]["strings"], True))
check("grid zero: the meter and its CTs in the drawing are on the list (2 TC)", ("Fronius Smart Meter WR 100-600 V-3" in _lg, _lg["Transformador de Corriente 100A:333mV"]["qty"], _cgz["meter"]["ct_label"]), (True, 2, "2 TC"))
check("grid zero: no Ekrano supply breaker (no GX)", _qty(_lg, "Breaker DC para riel DIN 16A"), 0)
check("grid zero: the link cable of the drawing is on the list", all(f"Cable {_g}" for _g in _cgz["base"]["link_conductors"]) and any("Base de generación → base de consumo" in w for ln in _lg.values() for w in ln.get("wheres") or []), True)
# Chint boxes follow the strings (a 5-space box holds two 2-pole breakers)
check("Chint DC boxes: 2 strings -> 1, 3 -> 2, 12 -> 6",
      [_list({**EQ, "n_strings": n}, {"ready": False, "branches": [], "coupling": {"strings": n}}).get("Centro de carga Chint DC 5 espacios", {}).get("qty") for n in (2, 3, 12)], [1, 2, 6])

print("\n" + ("ALL MATERIALS CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
