#!/usr/bin/env python3
"""Genera un diagrama unifilar (1 hoja, tamaño 11x17 apaisado) de un sistema solar
híbrido ACOPLADO EN AC: Fronius (FV) en el AC-OUT de 2 Victron MultiPlus-II en split-phase,
banco de baterías en Lynx Power In (con o sin Lynx Distributor) y Ekrano GX.

Uso:  python generate_unifilar.py config.json salida.pdf
Los campos que falten en config.json toman los valores por defecto de DEFAULTS.

En el app (Dimensionador FV) lo llama unifilar/config_builder.py: `build(cfg, out)` acepta una ruta
o un objeto tipo archivo (BytesIO), y el cfg sale de la configuración del diseño, sin texto libre de un LLM.
Copia del skill `unifilar-hibrido-ac`; el dibujo es la fuente de verdad: no cambiar convenciones sin preguntar al dueño.
"""
import json, sys, copy
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, black, white

W, H = 1224, 792
NAVY = HexColor('#12385B'); GREEN = HexColor('#4CB87E'); ORANGE = HexColor('#D9822B')
RED = HexColor('#B8322A'); BLUE = HexColor('#1F5FBF'); GRN = HexColor('#1E8449')
GRAY = HexColor('#666666'); LGRAY = HexColor('#EEF1F4'); MGRAY = HexColor('#BBBBBB')

DEFAULTS = {
    "project": {
        "name": "Proyecto", "client": "", "location": "", "date": "",
        "revision": "A (borrador)", "draft": True,
        "responsible": "Ing. Oscar Pauly Calvo · IE-30111",
    },
    "pv": {
        "strings": 2, "modules_per_string": 8, "module_w": 620,
        "module_label": "JA Solar 620 W", "roof_m2": None,
        "string_breaker": "32 A 2P DC", "dc_wire": "#10 SOLAR",
        "ground_wire": "T #10 AWG verde",
    },
    "fronius": {
        "label": "Fronius Primo 10.0-1 US 240 V", "kw": 10,
        "ac_breaker": "2P 60 A",
        "ac_conductors": ["L1 #4 AWG negro", "L2 #4 AWG rojo", "T #6 AWG verde"],
        "ground_wire": "T #6 AWG verde",
    },
    "multis": {
        "label": "MULTIPLUS-II 48/5000", "model": "MultiPlus-II 48/5000 120 V",
        "ac_in_breaker": "2P 100 A",
        "ac_in_conductors": ["L1 #4 AWG negro", "L2 #4 AWG rojo", "N #4 AWG blanco", "T #6 AWG verde"],
        "ac_out_conductors": ["L1 #4 AWG negro", "L2 #4 AWG rojo", "N #4 AWG blanco", "T #6 AWG verde"],
        "dc_pos": "+ #2 AWG rojo", "dc_neg": "- #2 AWG negro",
        "ground_wire": "T #6 AWG verde",
        "dc_fuse_labels": ["F1", "F2"],   # solo se dibujan si lynx = power_in_distributor
    },
    "battery": {
        "count": 4, "label": "Pylontech Fidus", "short": "Fidus", "kwh_each": 4.8,
        "fuse_prefix": "FB", "can_master": True,
        "lynx": "power_in",            # "power_in" o "power_in_distributor"
        "cables_note": ["Cables batería a Power In (+ / -):", "no listados en BOM, por definir"],
    },
    "gx": {"label": "EKRANO GX", "power_breaker": "QDC 2P", "power_note": "+ / - por definir"},
    "export": "grid_zero",             # "grid_zero" o "inyeccion"
    "subpanel": {
        "q2": "2P", "q4": "circuitos críticos", "spd": "SPD SDSA 1175",
        "loads": ["iluminación, internet, tomacorrientes,", "refrigerador, etc."],
    },
    "grid": {"voltage": "120/240 V · 60 Hz"},
    "comms_notes": {"vebus": "VE.Bus (cable no listado en BOM)",
                    "can": "CAN-bus BMS (Fidus #1 a Ekrano GX) · cable no listado en BOM",
                    "eth": "Ethernet / Modbus TCP (control de potencia del Fronius) · UTP no listado en BOM"},
}


def merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


def build(cfg_in, out_path):
    cfg = merge(DEFAULTS, cfg_in)
    P, PV, FR, MU, BA, GX, SP = (cfg[k] for k in ("project", "pv", "fronius", "multis", "battery", "gx", "subpanel"))
    n_str, n_mod, n_bat = PV["strings"], PV["modules_per_string"], BA["count"]
    dist = BA["lynx"] == "power_in_distributor"
    assert n_str in (1, 2), "pv.strings debe ser 1 o 2 (un MPPT por string)"
    assert 1 <= n_bat <= (4 if dist else 6), "battery.count: máx. 4 con Distributor, 6 sin él"
    grid_zero = cfg["export"] == "grid_zero"

    c = canvas.Canvas(out_path, pagesize=(W, H))
    c.setTitle(f"{P['name']} - Diagrama unifilar")
    c.setAuthor("Pauly y Compañía Ingenieros y Arquitectos S.A.")

    # ---------- helpers ----------
    def seg(pts, color=black, w=1.5, dash=None):
        c.saveState(); c.setStrokeColor(color); c.setLineWidth(w)
        if dash: c.setDash(*dash)
        p = c.beginPath(); p.moveTo(*pts[0])
        for q in pts[1:]: p.lineTo(*q)
        c.drawPath(p, stroke=1, fill=0); c.restoreState()

    def txt(x, y, s, size=7, font='Helvetica', color=black, align='c'):
        c.saveState(); c.setFont(font, size); c.setFillColor(color)
        {'c': c.drawCentredString, 'l': c.drawString, 'r': c.drawRightString}[align](x, y, s)
        c.restoreState()

    def lab(x, y, s, color=black, align='c', size=5.8):
        txt(x, y, s, size, 'Helvetica', color, align)

    def box(x, y, w, h, fill=white, stroke=black, lw=1.2):
        c.saveState(); c.setFillColor(fill); c.setStrokeColor(stroke); c.setLineWidth(lw)
        c.rect(x, y, w, h, fill=1, stroke=1); c.restoreState()

    def breaker(x, y, vert=False):
        c.saveState(); c.setFillColor(white); c.setStrokeColor(black); c.setLineWidth(0.9)
        if vert:
            c.rect(x - 4.5, y - 7, 9, 14, fill=1, stroke=1); c.line(x - 3, y - 5, x + 3, y + 5)
        else:
            c.rect(x - 7, y - 4.5, 14, 9, fill=1, stroke=1); c.line(x - 5, y - 3, x + 5, y + 3)
        c.restoreState()

    def fuse(x, y):
        c.saveState(); c.setFillColor(white); c.setStrokeColor(black); c.setLineWidth(0.9)
        c.rect(x - 4, y - 7, 8, 14, fill=1, stroke=1); c.line(x, y - 7, x, y + 7); c.restoreState()

    def ground(x, y, color=GRN):
        c.saveState(); c.setStrokeColor(color); c.setLineWidth(1)
        c.line(x - 7, y, x + 7, y); c.line(x - 4.5, y - 3, x + 4.5, y - 3); c.line(x - 2, y - 6, x + 2, y - 6)
        c.restoreState()

    def dot(x, y):
        c.saveState(); c.setFillColor(black); c.circle(x, y, 2.2, fill=1, stroke=0); c.restoreState()

    def stack(x, y, items, align='c'):
        for k, t in enumerate(items):
            lab(x, y - k * 7.5, t, GRN if t.startswith('T ') else black, align)

    # ---------- marco y cajetín ----------
    c.setStrokeColor(black); c.setLineWidth(1.6); c.rect(18, 18, W - 36, H - 36)
    X0, Y0, TW = 744, 18, 462
    c.setLineWidth(1.2); c.rect(X0, Y0, TW, 120)

    def cell(x, y, w, h, label, value, vs=8, bold=False):
        c.setLineWidth(0.6); c.rect(x, y, w, h)
        if label: txt(x + 4, y + h - 7, label, 5.5, 'Helvetica', GRAY, 'l')
        if value: txt(x + 4, y + 5, value, vs, 'Helvetica-Bold' if bold else 'Helvetica', black, 'l')

    c.setLineWidth(0.6); c.rect(X0, Y0 + 90, TW, 30)
    txt(X0 + 8, Y0 + 101, 'pauly', 17, 'Helvetica-Bold', GREEN, 'l')
    txt(X0 + 49, Y0 + 109, '&co', 7, 'Helvetica-Bold', NAVY, 'l')
    txt(X0 + 8, Y0 + 92.5, 'Ingenieros y Arquitectos', 5.5, 'Helvetica', NAVY, 'l')
    txt(X0 + TW - 8, Y0 + 106, 'Pauly y Compañía Ingenieros y Arquitectos S.A.', 8, 'Helvetica-Bold', NAVY, 'r')
    txt(X0 + TW - 8, Y0 + 96, 'Céd. jurídica 3-101-798034 · www.paulyco.com · info@paulyco.com', 6.5, 'Helvetica', GRAY, 'r')
    cell(X0, Y0 + 66, TW, 24, 'PROYECTO', P["name"], 8.5, True)
    cell(X0, Y0 + 42, 200, 24, 'CLIENTE', P["client"])
    cell(X0 + 200, Y0 + 42, 262, 24, 'UBICACIÓN', P["location"])
    cell(X0, Y0 + 18, 262, 24, 'PLANO', 'DIAGRAMA UNIFILAR', 8.5, True)
    cell(X0 + 262, Y0 + 18, 60, 24, 'REVISIÓN', P["revision"], 7)
    cell(X0 + 322, Y0 + 18, 140, 24, 'FECHA', P["date"])
    cell(X0, Y0, 262, 18, '', ''); txt(X0 + 4, Y0 + 5.5, 'Resp.: ' + P["responsible"], 7, 'Helvetica', black, 'l')
    cell(X0 + 262, Y0, 100, 18, '', ''); txt(X0 + 266, Y0 + 5.5, 'Escala: sin escala', 7, 'Helvetica', black, 'l')
    cell(X0 + 362, Y0, 100, 18, '', ''); txt(X0 + 366, Y0 + 5.5, 'Hoja 1 de 1', 7.5, 'Helvetica-Bold', black, 'l')

    total_kwh = n_bat * BA["kwh_each"]
    txt(30, 748, 'DIAGRAMA UNIFILAR', 17, 'Helvetica-Bold', NAVY, 'l')
    sub = (f"Sistema híbrido acoplado en AC · 2 × Victron {MU['model'].split(' 120')[0]} (split-phase 120/240 V, 60 Hz) + "
           f"{FR['label']} + {n_bat} × {BA['label']} ({total_kwh:.1f} kWh) · "
           + ("Cero inyección (Grid Zero)" if grid_zero else "Con inyección a la red"))
    txt(30, 734, sub, 7.5, 'Helvetica', GRAY, 'l')
    if P["draft"]:
        txt(1196, 748, 'BORRADOR · REV ' + P["revision"].split()[0], 10, 'Helvetica-Bold', RED, 'r')

    # ---------- arreglo FV ----------
    ys = [665, 635] if n_str == 2 else [650]
    box(40, 590, 240, 120, LGRAY)
    txt(160, 697, 'ARREGLO FOTOVOLTAICO', 8, 'Helvetica-Bold')
    kwp = n_str * n_mod * PV["module_w"] / 1000
    txt(160, 686, f"{n_str * n_mod} × {PV['module_label']} · {kwp:.2f} kWp", 7)
    pitch = min(24, 188 / n_mod); mw = pitch - 4
    for i, yc in enumerate(ys):
        txt(48, yc - 2.5, f"S{i + 1}", 7, 'Helvetica-Bold', NAVY, 'l')
        for k in range(n_mod):
            c.saveState(); c.setFillColor(HexColor('#DCE8F5')); c.setStrokeColor(NAVY); c.setLineWidth(0.8)
            c.rect(62 + k * pitch, yc - 7, mw, 14, fill=1, stroke=1); c.restoreState()
    foot = f"{n_str} {'string' if n_str == 1 else 'strings'} × {n_mod} módulos en serie" + (f" · {PV['roof_m2']} m2 de techo" if PV["roof_m2"] else "")
    txt(160, 600, foot, 6.5, 'Helvetica', GRAY)
    seg([(150, 590), (150, 572)], GRN, 1.1, (3, 2)); ground(150, 572); lab(160, 570, PV["ground_wire"], GRN, 'l')

    box(340, 600, 130, 105, white)
    txt(405, 692, 'GABINETE DC', 7.5, 'Helvetica-Bold')

    # ---------- Fronius ----------
    box(560, 590, 200, 120, LGRAY)
    txt(660, 696, 'INVERSOR ON-GRID (FV)', 8, 'Helvetica-Bold')
    txt(660, 685, FR["label"], 7)
    txt(660, 675, f"{FR['kw']} kW · {n_str} MPPT", 6.5, 'Helvetica', GRAY)
    for i, yc in enumerate(ys):
        txt(566, yc - 2.5, f"MPPT {i + 1}", 6.5, 'Helvetica', GRAY, 'l')
        seg([(254, yc), (560, yc)], ORANGE, 1.6)
    for i, yc in enumerate(ys):
        breaker(395, yc)
        txt(395, yc + 10, f"QS{i + 1} · {PV['string_breaker']}", 6, 'Helvetica', black)
        for xc in (311, 515):
            lab(xc, yc + 6, '+ ' + PV["dc_wire"], RED)
            lab(xc, yc - 9, '- ' + PV["dc_wire"], black)
    seg([(585, 590), (585, 572)], GRN, 1.1, (3, 2)); ground(585, 572); lab(595, 570, FR["ground_wire"], GRN, 'l')

    # salida AC del Fronius al sub-panel
    seg([(690, 590), (690, 436)], black, 1.8)
    txt(700, 575, 'AC 240 V', 6.5, 'Helvetica', black, 'l')
    stack(698, 563, FR["ac_conductors"], 'l')

    # ---------- red y tablero principal ----------
    c.saveState(); c.setFillColor(white); c.setStrokeColor(black); c.setLineWidth(1.3); c.circle(62, 436, 16, fill=1, stroke=1); c.restoreState()
    txt(62, 431, '~', 15, 'Helvetica-Bold')
    txt(62, 408, 'RED ELÉCTRICA', 7, 'Helvetica-Bold')
    txt(62, 399, cfg["grid"]["voltage"], 6.5, 'Helvetica', GRAY)
    seg([(78, 436), (126, 436)], black, 1.8)
    c.saveState(); c.setFillColor(white); c.setStrokeColor(black); c.setLineWidth(1.1); c.circle(140, 436, 14, fill=1, stroke=1); c.restoreState()
    txt(140, 433.5, 'kWh', 6.5, 'Helvetica-Bold'); txt(140, 454, 'Medidor', 6, 'Helvetica', GRAY)
    seg([(154, 436), (170, 436)], black, 1.8)

    box(170, 386, 110, 100, LGRAY)
    txt(225, 474, 'TABLERO PRINCIPAL', 7, 'Helvetica-Bold'); txt(225, 465, '(existente)', 6.5, 'Helvetica', GRAY)
    seg([(170, 436), (380, 436)], black, 1.8)
    breaker(200, 436); txt(200, 421, 'Int. principal', 6, 'Helvetica', GRAY)
    seg([(225, 386), (225, 368)], GRN, 1.1, (3, 2)); ground(225, 368); lab(235, 366, MU["ground_wire"], GRN, 'l')
    breaker(325, 436)
    txt(325, 446, 'Q1', 7, 'Helvetica-Bold'); txt(325, 424, MU["ac_in_breaker"], 6.5)
    stack(333, 413, MU["ac_in_conductors"])

    # ---------- MultiPlus-II ----------
    box(380, 372, 180, 150, white, black, 1.4)
    txt(470, 511, f"2 × VICTRON {MU['label']}", 7.5, 'Helvetica-Bold')
    txt(470, 501, 'Split-phase 120/240 V · VE.Bus', 6.5, 'Helvetica', GRAY)
    box(392, 445, 156, 45, LGRAY)
    txt(470, 473, 'MP#1 · L1 (maestro)', 7, 'Helvetica-Bold'); txt(470, 462, MU["model"], 6.5, 'Helvetica', GRAY)
    box(392, 382, 156, 45, LGRAY)
    txt(470, 410, 'MP#2 · L2 (esclavo)', 7, 'Helvetica-Bold'); txt(470, 399, MU["model"], 6.5, 'Helvetica', GRAY)
    for xa, xb in ((386, 392), (554, 548)):
        seg([(xa, 405), (xa, 467)], black, 1.4); seg([(xa, 467), (xb, 467)], black, 1.4); seg([(xa, 405), (xb, 405)], black, 1.4)
        dot(xa, 436)
    txt(378, 427, 'AC-IN', 5.5, 'Helvetica-Bold', GRAY, 'r'); txt(562, 427, 'AC-OUT', 5.5, 'Helvetica-Bold', GRAY, 'l')
    seg([(390, 372), (390, 352)], GRN, 1.1, (3, 2)); ground(390, 352); lab(382, 350, MU["ground_wire"], GRN, 'r')
    seg([(560, 436), (640, 436)], black, 1.8)
    stack(602, 466, MU["ac_out_conductors"])

    # ---------- sub-panel de cargas críticas ----------
    box(640, 366, 180, 140, LGRAY)
    txt(752, 494, 'SUB-PANEL CARGAS CRÍTICAS', 7, 'Helvetica-Bold'); txt(752, 485, '120/240 V', 6.5, 'Helvetica', GRAY)
    seg([(640, 436), (880, 436)], black, 1.8)
    seg([(690, 506), (690, 436)], black, 1.8); dot(690, 436)
    breaker(658, 436); txt(658, 446, 'Q2', 7, 'Helvetica-Bold'); txt(658, 424, SP["q2"], 6.5)
    breaker(690, 466, vert=True); txt(698, 464, f"Q3 · {FR['ac_breaker']} (FV)", 6.5, 'Helvetica', black, 'l')
    breaker(795, 436); txt(795, 446, 'Q4', 7, 'Helvetica-Bold'); txt(795, 455, SP["q4"], 6, 'Helvetica', GRAY)   # sobre la barra: abajo lo cruza el SPD
    if SP["spd"]:
        dot(775, 436)
        seg([(775, 436), (775, 408)], black, 1.4)
        c.saveState(); c.setFillColor(white); c.setStrokeColor(black); c.setLineWidth(0.9); c.rect(769.5, 394, 11, 14, fill=1, stroke=1)
        c.line(775, 406, 772.5, 399); c.line(772.5, 399, 777.5, 402); c.line(777.5, 402, 775, 396); c.restoreState()
        seg([(775, 394), (775, 354)], GRN, 1.1, (3, 2)); ground(775, 354); lab(785, 352, MU["ground_wire"], GRN, 'l')
        txt(766, 399, SP["spd"], 6.5, 'Helvetica', black, 'r')
    seg([(670, 366), (670, 352)], GRN, 1.1, (3, 2)); ground(670, 352); lab(680, 350, MU["ground_wire"], GRN, 'l')
    box(880, 406, 170, 60, white)
    txt(965, 449, 'CARGAS CRÍTICAS', 7.5, 'Helvetica-Bold')
    for k, t in enumerate(SP["loads"][:2]):
        txt(965, 438 - k * 9, t, 6.5, 'Helvetica', GRAY)

    # ---------- baterías + Lynx ----------
    xs = [40 + i * 88 + 38 for i in range(n_bat)]
    for i in range(n_bat):
        x = 40 + i * 88
        box(x, 170, 76, 55, LGRAY)
        txt(x + 38, 207, f"{BA['short']} #{i + 1}", 7.5, 'Helvetica-Bold')
        txt(x + 38, 196, f"{BA['kwh_each']:g} kWh", 6.5, 'Helvetica', GRAY)
        if i == 0 and BA["can_master"]:
            txt(x + 38, 183, '(maestro CAN)', 5.8, 'Helvetica', BLUE)
        seg([(xs[i], 225), (xs[i], 265)], RED, 1.8); fuse(xs[i], 245)
        txt(xs[i] + 7, 243, f"{BA['fuse_prefix']}{i + 1}", 6, 'Helvetica', black, 'l')
        if i < n_bat - 1:
            seg([(x + 76, 197), (x + 88, 197)], BLUE, 1, (2, 1.5))
    last = 40 + n_bat * 88 - 12
    for k, t in enumerate(BA["cables_note"][:3]):
        lab(last + 14, 248 - k * 7, t, GRAY, 'l')

    if dist:
        box(40, 265, 340, 28, white, black, 1.4)
        txt(210, 276, f'LYNX POWER IN · bus DC 48 V · {n_bat} baterías con fusible MEGA', 7, 'Helvetica-Bold')
        seg([(380, 279), (400, 279)], black, 4)
        box(400, 265, 190, 28, white, black, 1.4)
        txt(495, 276, 'LYNX DISTRIBUTOR · fusibles MEGA', 7, 'Helvetica-Bold')
    else:
        box(40, 265, 550, 28, white, black, 1.4)
        txt(315, 276, f'LYNX POWER IN · bus DC 48 V · {n_bat} baterías con fusible MEGA', 7, 'Helvetica-Bold')

    for idx, (xr, mp) in enumerate(((446, 'MP#1'), (516, 'MP#2'))):
        seg([(xr, 293), (xr, 372)], RED, 1.8); seg([(xr + 8, 293), (xr + 8, 372)], black, 1.8)
        txt(xr - 4, 361, mp, 6, 'Helvetica', GRAY, 'r')
        if dist and idx == 1:     # con Distributor no hay espacio a la derecha (línea VE.Bus): ambos rótulos a la izquierda
            lab(xr - 4, 352, MU["dc_pos"], RED, 'r'); lab(xr - 4, 344, MU["dc_neg"], black, 'r')
        else:
            yy = 332 if dist else (340 if idx == 0 else 312)
            lab(xr - 4, yy, MU["dc_pos"], RED, 'r'); lab(xr + 12, yy, MU["dc_neg"], black, 'l')
        if dist:
            fuse(xr, 320); txt(xr - 7, 318, MU["dc_fuse_labels"][idx], 6.5, 'Helvetica-Bold', black, 'r')

    # ---------- Ekrano GX ----------
    box(660, 235, 140, 60, LGRAY)
    txt(730, 281, GX["label"], 8, 'Helvetica-Bold'); txt(730, 270, 'Monitoreo y control ESS', 6.5, 'Helvetica', GRAY)
    if grid_zero:
        txt(730, 260, 'Límite de inyección = 0 W', 6.5, 'Helvetica', GRAY); txt(730, 246, '(Grid Zero)', 6.5, 'Helvetica', GRAY)
    else:
        txt(730, 260, 'Excedentes a la red vía AC-IN', 6.5, 'Helvetica', GRAY)
        txt(730, 246, '(según permiso de la distribuidora)', 6, 'Helvetica', GRAY)
    seg([(590, 286), (660, 286)], RED, 1.1); seg([(590, 282), (660, 282)], black, 1.1)
    breaker(625, 284, vert=True); txt(625, 295, GX["power_breaker"], 6, 'Helvetica', black); lab(625, 266, GX["power_note"], GRAY)

    CN = cfg["comms_notes"]
    if dist:
        seg([(560, 265), (560, 250), (660, 250)], BLUE, 1.1, (4, 2)); txt(610, 253, 'VE.Can', 6, 'Helvetica', BLUE)
    seg([(545, 372), (545, 330), (700, 330), (700, 295)], BLUE, 1.1, (4, 2)); txt(640, 334, CN["vebus"], 6, 'Helvetica', BLUE, 'l')
    seg([(xs[0], 170), (xs[0], 155), (725, 155), (725, 235)], BLUE, 1.1, (4, 2)); txt(400, 158, CN["can"], 6, 'Helvetica', BLUE)
    seg([(760, 650), (1070, 650), (1070, 265), (800, 265)], BLUE, 1.1, (4, 2))
    txt(915, 655, CN["eth"], 6, 'Helvetica', BLUE)

    # ---------- simbología ----------
    txt(30, 125, 'SIMBOLOGÍA', 7.5, 'Helvetica-Bold', NAVY, 'l')
    c.setLineWidth(0.6); c.setStrokeColor(MGRAY); c.line(24, 120, 735, 120)
    ly = [104, 85, 66, 47, 28]
    seg([(30, ly[0]), (70, ly[0])], black, 1.8); txt(80, ly[0] - 2.5, 'AC', 7, 'Helvetica', black, 'l')
    seg([(30, ly[1]), (70, ly[1])], ORANGE, 1.6); txt(80, ly[1] - 2.5, 'DC fotovoltaico', 7, 'Helvetica', black, 'l')
    seg([(30, ly[2] + 2.5), (70, ly[2] + 2.5)], RED, 1.8); seg([(30, ly[2] - 2.5), (70, ly[2] - 2.5)], black, 1.8)
    txt(80, ly[2] - 2.5, 'DC batería (+ rojo / - negro)', 7, 'Helvetica', black, 'l')
    seg([(30, ly[3]), (70, ly[3])], BLUE, 1.1, (4, 2)); txt(80, ly[3] - 2.5, 'Comunicaciones', 7, 'Helvetica', black, 'l')
    seg([(30, ly[4]), (70, ly[4])], GRN, 1.1, (3, 2)); txt(80, ly[4] - 2.5, 'Tierra (verde)', 7, 'Helvetica', black, 'l')
    sx = 255
    breaker(sx, ly[0]); txt(sx + 20, ly[0] - 2.5, 'Interruptor termomagnético', 7, 'Helvetica', black, 'l')
    fuse(sx, ly[1]); txt(sx + 20, ly[1] - 2.5, 'Fusible MEGA', 7, 'Helvetica', black, 'l')
    c.saveState(); c.setFillColor(white); c.setStrokeColor(black); c.setLineWidth(0.9); c.rect(sx - 5.5, ly[2] - 7, 11, 14, fill=1, stroke=1)
    c.line(sx, ly[2] + 5, sx - 2.5, ly[2] - 2); c.line(sx - 2.5, ly[2] - 2, sx + 2.5, ly[2] + 1); c.line(sx + 2.5, ly[2] + 1, sx, ly[2] - 5); c.restoreState()
    txt(sx + 20, ly[2] - 2.5, 'Supresor de picos (SPD)', 7, 'Helvetica', black, 'l')
    txt(sx, ly[3] - 2, 'L1 #4', 6, 'Helvetica', black); txt(sx + 20, ly[3] - 2.5, 'Calibre y función del conductor', 7, 'Helvetica', black, 'l')
    ground(sx, ly[4] + 3); txt(sx + 20, ly[4] - 2.5, 'Puesta a tierra', 7, 'Helvetica', black, 'l')

    c.showPage(); c.save()


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    cfg = json.load(open(sys.argv[1], encoding='utf-8'))
    build(cfg, sys.argv[2])
    print('ok ->', sys.argv[2])
