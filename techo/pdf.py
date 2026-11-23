"""PDF of the roof plan, laid out like Pauly & Co's roof sheets (lámina «Detalle de instalación en techo»): the aerial photo with the modules to
scale and its caption on the left; on the right the SIMBOLOGÍA box, the DETALLE DE SISTEMA text and the DETALLE DE MÓDULO FOTOVOLTAICO.
One 11x17 landscape sheet with the same title block as the Plano de taller and the unifilar (`plano.generate_plano._frame`)."""
from __future__ import annotations

import io

from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

from plano.generate_plano import GRAY, H, NAVY, RED, W, _frame, _t
from techo import geometry as G
from techo import service as S

PHOTO_BOX = (40, 150, 770, 712)      # x0, y0, x1, y1 (pt): the photo is anchored top-left inside it
RIGHT_X0, RIGHT_X1 = 800, 1184       # right column: symbols, system, module
MODULE_BLUE = HexColor("#0B57D0")
MAX_PX = 3200                        # the photo is downscaled so the PDF stays light


def _nice(m: float) -> float:
    """A round scale-bar length near `m` metres."""
    for v in (1, 2, 5, 10, 20, 50, 100):
        if v >= m:
            return float(v)
    return 100.0


def _heading(c, x, y, text, size=11):
    """Underlined heading, like the CAD sheets («DETALLE DE SISTEMA»)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    _t(c, x, y, text, size, "Helvetica", black)
    c.setStrokeColor(black); c.setLineWidth(0.8)
    c.line(x, y - 2.5, x + stringWidth(text, "Helvetica", size), y - 2.5)


def _wrapped(c, x, y, text, width, size=8.5, lead=12, font="Helvetica", color=black) -> float:
    """Draw wrapped text from y downwards; returns the y below the last line."""
    for ln in simpleSplit(text, font, size, width):
        _t(c, x, y, ln, size, font, color)
        y -= lead
    return y


def _module_detail(c, p: dict, x0: float, x1: float, y0: float, y1: float) -> None:
    """Schematic front view of the module with its two outer dimensions, and its electrical data."""
    wm, hm = p["width_m"], p["height_m"]
    if not (wm and hm):
        return
    k = min((y1 - y0 - 30) / hm, 118 / wm)                  # points per metre
    mw, mh = wm * k, hm * k
    mx, my = x0 + 34, y0 + 4
    c.setFillColor(HexColor("#1F3B63")); c.setStrokeColor(black); c.setLineWidth(1)
    c.rect(mx, my, mw, mh, fill=1, stroke=1)
    c.setStrokeColor(HexColor("#7F95B5")); c.setLineWidth(0.4)
    for i in range(1, 6):
        c.line(mx + mw * i / 6, my, mx + mw * i / 6, my + mh)
    for j in range(1, 12):
        c.line(mx, my + mh * j / 12, mx + mw, my + mh * j / 12)
    c.setStrokeColor(RED); c.setLineWidth(0.6)
    ty = my + mh + 8                                          # width dimension (above)
    c.line(mx, ty, mx + mw, ty); c.line(mx, ty - 3, mx, ty + 3); c.line(mx + mw, ty - 3, mx + mw, ty + 3)
    _t(c, mx + mw / 2, ty + 3, f"{wm * 1000:.0f} mm", 7, color=RED, align="c")
    tx = mx - 8                                               # height dimension (left)
    c.line(tx, my, tx, my + mh); c.line(tx - 3, my, tx + 3, my); c.line(tx - 3, my + mh, tx + 3, my + mh)
    c.saveState(); c.translate(tx - 3, my + mh / 2); c.rotate(90); _t(c, 0, 0, f"{hm * 1000:.0f} mm", 7, color=RED, align="c"); c.restoreState()
    rows = [("Módulo", f"{p['brand']} {p['model']}".strip()), ("Pmax", f"{p['wp']:g} W" if p["wp"] else ""), ("Voc", f"{p.get('voc', 0):g} V" if p.get("voc") else ""),
            ("Isc", f"{p.get('isc', 0):g} A" if p.get("isc") else ""), ("Vmp", f"{p.get('vmp', 0):g} V" if p.get("vmp") else ""), ("Imp", f"{p.get('imp', 0):g} A" if p.get("imp") else ""),
            ("Dimensiones", f"{wm * 1000:.0f} × {hm * 1000:.0f} mm"), ("Peso", f"{p.get('weight_kg', 0):g} kg" if p.get("weight_kg") else "")]
    y = y1 - 6
    sx = mx + mw + 26
    for label, val in rows:
        if not val:
            continue
        _t(c, sx, y, label, 7.5, color=GRAY); y = _wrapped(c, sx + 62, y, val, x1 - sx - 62, 8, 10, "Helvetica-Bold") - 2


def build(data: dict, out) -> None:
    """data: project (name, client, location, date, revision, draft, responsible), plan (cleaned), info (design_info), photo_bytes."""
    from PIL import Image

    P, plan, info = dict(data["project"]), data["plan"], data["info"]
    P["sheet"] = "PLANO DE TECHO"
    img = Image.open(io.BytesIO(data["photo_bytes"])).convert("RGB")
    iw, ih = img.size
    if max(iw, ih) > MAX_PX:
        k = MAX_PX / max(iw, ih)
        img = img.resize((int(iw * k), int(ih * k)))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=88); buf.seek(0)

    # The plan's coordinates are in the ORIGINAL photo pixels (plan["photo"]["w"/"h"]); the sheet maps them to points.
    pw, ph = plan["photo"]["w"] or iw, plan["photo"]["h"] or ih
    fit = min((PHOTO_BOX[2] - PHOTO_BOX[0]) / pw, (PHOTO_BOX[3] - PHOTO_BOX[1] - 40) / ph)        # points per photo pixel (40 pt for the caption)
    ox, oy = PHOTO_BOX[0], PHOTO_BOX[3] - ph * fit                                                   # bottom-left of the photo, anchored top-left
    X = lambda x: ox + x * fit                                                # noqa: E731
    Y = lambda y: oy + (ph - y) * fit                                         # noqa: E731  (photo y runs down)
    scale = plan.get("scale")
    pt_per_m = (scale["px_per_m"] * fit) if scale else 0.0
    P["scale"] = f"1:{round(1000.0 / (pt_per_m * 25.4 / 72)):d}" if pt_per_m else "sin escala"

    c = canvas.Canvas(out, pagesize=(W, H))
    c.setTitle(f"{P['name']} - Plano de techo"); c.setAuthor("Pauly y Compañía Ingenieros y Arquitectos S.A.")
    _frame(c, P)
    pn = info["panel"]
    _t(c, 30, 748, "PLANO DE TECHO", 17, "Helvetica-Bold", NAVY)
    _t(c, 30, 734, f"{sum(s['count'] for s in plan['strings'])} × {pn['brand']} {pn['model']} · {pn['width_m'] * 1000:.0f} × {pn['height_m'] * 1000:.0f} mm · "
                   f"separación entre módulos (midclamp) {plan['gap_mm']:g} mm", 7.5, color=GRAY)
    if P.get("draft"):
        _t(c, 1196, 748, "BORRADOR · REV " + P["revision"].split()[0], 10, "Helvetica-Bold", RED, "r")

    # ---- photo with the modules ----
    c.drawImage(ImageReader(buf), ox, oy, width=pw * fit, height=ph * fit)
    c.setStrokeColor(black); c.setLineWidth(0.6); c.rect(ox, oy, pw * fit, ph * fit)
    c.saveState(); clip = c.beginPath(); clip.rect(ox, oy, pw * fit, ph * fit); c.clipPath(clip, stroke=0, fill=0)
    roof = [tuple(q) for q in plan["roof"]]
    if len(roof) >= 3:
        c.setStrokeColor(white); c.setLineWidth(1.2); c.setDash(6, 4)
        pp = c.beginPath(); pp.moveTo(X(roof[0][0]), Y(roof[0][1]))
        for x, y in roof[1:]:
            pp.lineTo(X(x), Y(y))
        pp.close(); c.drawPath(pp, stroke=1, fill=0); c.setDash()
    chk = {}
    if scale and pn["width_m"] and pn["height_m"]:
        chk = G.check(plan["strings"], pn["width_m"], pn["height_m"], plan["gap_mm"] / 1000.0, scale["px_per_m"], roof)
        bad = {i for pair in chk["overlaps"] for i in pair}
        for s in plan["strings"]:
            sx = sy = n = 0
            for q in chk["polys"][s["id"]]:
                pp = c.beginPath(); pp.moveTo(X(q[0][0]), Y(q[0][1]))
                for x, y in q[1:]:
                    pp.lineTo(X(x), Y(y))
                pp.close()
                c.setFillColor(Color(MODULE_BLUE.red, MODULE_BLUE.green, MODULE_BLUE.blue, alpha=0.9)); c.setStrokeColor(RED if s["id"] in bad else HexColor("#CFE0FF"))
                c.setLineWidth(1.4 if s["id"] in bad else 0.5); c.drawPath(pp, stroke=1, fill=1)
                sx += sum(p_[0] for p_ in q) / 4; sy += sum(p_[1] for p_ in q) / 4; n += 1
            if n:
                _t(c, X(sx / n), Y(sy / n) - 3.5, f"S{s['id']}", 10, "Helvetica-Bold", white, "c")
    c.restoreState()
    if pt_per_m:                                              # scale bar, bottom-left of the photo
        bar_m = _nice(110.0 / pt_per_m)
        bx, by = ox + 14, oy + 14
        c.setFillColor(white); c.rect(bx - 6, by - 6, bar_m * pt_per_m + 12, 24, fill=1, stroke=0)
        c.setStrokeColor(black); c.setLineWidth(1.2); c.line(bx, by, bx + bar_m * pt_per_m, by)
        c.line(bx, by - 3, bx, by + 3); c.line(bx + bar_m * pt_per_m, by - 3, bx + bar_m * pt_per_m, by + 3)
        _t(c, bx + bar_m * pt_per_m / 2, by + 5, f"{bar_m:g} m", 7.5, "Helvetica-Bold", align="c")
    _heading(c, ox + 4, oy - 22, "DETALLE DE INSTALACIÓN EN TECHO", 13)

    # string table + fit warnings under the caption
    y = oy - 46
    for s in plan["strings"]:
        wm, hm = G.module_dims(pn["width_m"], pn["height_m"], s["orient"])
        bl = G.block_layout(s["count"], s["rows"], wm, hm, plan["gap_mm"] / 1000.0)
        flag = "  · CHOCA" if chk and any(s["id"] in pr for pr in chk["overlaps"]) else ("  · FUERA DEL TECHO" if chk and s["id"] in chk["outside"] else "")
        _t(c, ox + 4, y, f"S{s['id']}: {s['count']} módulos · {bl['rows']} fila(s) × {bl['cols']} · {'vertical' if s['orient'] != 'landscape' else 'horizontal'} · "
                         f"giro {s['rot']:.0f}° · bloque {bl['w']:.2f} × {bl['h']:.2f} m{flag}", 7.5, color=RED if flag else black)
        y -= 11
    _t(c, ox + 4, y, f"Separación entre módulos (midclamp): {plan['gap_mm']:g} mm", 7.5, color=GRAY)
    if not scale:
        _t(c, ox + 4, y - 11, "La escala no está calibrada: las medidas del plano no son confiables.", 7.5, "Helvetica-Bold", RED)

    # ---- right column ----
    top = 712
    from utils.pdf_sheet import COL1_TEXT, LEGEND_ROWS, legend_header, legend_text

    legend_header(c)
    ly = LEGEND_ROWS
    c.setFillColor(MODULE_BLUE); c.setStrokeColor(black); c.setLineWidth(0.6); c.rect(40, ly[0] - 6, 20, 12, fill=1, stroke=1)
    legend_text(c, COL1_TEXT, 0, "Módulo fotovoltaico de marco y características definidas en planos eléctricos")
    row = 1
    if len(roof) >= 3:
        c.setStrokeColor(GRAY); c.setLineWidth(1.2); c.setDash(6, 4); c.line(30, ly[row], 70, ly[row]); c.setDash()
        legend_text(c, COL1_TEXT, row, "Contorno de la superficie del techo"); row += 1
    if chk and (chk["overlaps"] or chk["outside"]):
        c.setFillColor(MODULE_BLUE); c.setStrokeColor(RED); c.setLineWidth(1.6); c.rect(40, ly[row] - 6, 20, 12, fill=1, stroke=1)
        legend_text(c, COL1_TEXT, row, "Módulos que chocan entre sí o salen del contorno"); row += 1
    c.setStrokeColor(black); c.setLineWidth(1.2); c.line(30, ly[row], 70, ly[row]); c.line(30, ly[row] - 3, 30, ly[row] + 3); c.line(70, ly[row] - 3, 70, ly[row] + 3)
    legend_text(c, COL1_TEXT, row, "Escala gráfica (en la foto)")

    ty = top - 10
    _heading(c, RIGHT_X0, ty, "DETALLE DE SISTEMA", 11)
    y = ty - 22
    for ln in S.system_lines(plan, info):
        y = _wrapped(c, RIGHT_X0, y, ln, RIGHT_X1 - RIGHT_X0, 8.5, 12) - 5

    _module_detail(c, pn, RIGHT_X0, RIGHT_X1, 192, min(y - 18, 420))
    _heading(c, RIGHT_X0, 164, "DETALLE DE MÓDULO FOTOVOLTAICO", 11)
    c.showPage(); c.save()
