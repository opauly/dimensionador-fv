"""PDF of the workshop plan: the wall (front view, to scale), the equipment placed on it, the minimum work area and, when the proposed wall is
known, whether it is enough. One 11x17 landscape sheet with the Pauly & Co title block, like the unifilar."""
from __future__ import annotations

from reportlab.lib.colors import HexColor, black, white
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from plano import layout as L

W, H = 1224, 792
NAVY = HexColor("#12385B"); GREEN = HexColor("#4CB87E"); RED = HexColor("#B8322A"); OKG = HexColor("#1E8449")
GRAY = HexColor("#666666"); LGRAY = HexColor("#EEF1F4"); DIM = HexColor("#B03030")
FILL = {"victron": "#A9CDF2", "fronius": "#D9D9D9", "controller": "#8FC1EA", "gabinete": "#E6E6E0", "chint": "#E9E2CF", "center": "#E4E0F0",
        "lynx": "#8FC1EA", "fidus": "#F4F4F4", "stand": "#E8E8E8", "duct": "#B8BCC2"}
AREA = (40, 185, 700, 705)          # x0, y0, x1, y1 of the drawing area (pt)


def _t(c, x, y, s, size=7, font="Helvetica", color=black, align="l"):
    c.setFillColor(color); c.setFont(font, size)
    {"l": c.drawString, "c": c.drawCentredString, "r": c.drawRightString}[align](x, y, s)


def _fit_label(c, text: str, cx: float, cy: float, w: float, h: float, size: float) -> None:
    """Centre `text` in a w x h box: shrink it, then split it in two lines, then turn it upright; never spill outside the box."""
    font = "Helvetica-Bold"
    sizes = [size - 0.4 * k for k in range(0, int((size - 4.2) / 0.4) + 1)] or [4.2]
    for sz in sizes:
        if stringWidth(text, font, sz) <= w - 4:
            _t(c, cx, cy, text, sz, font, align="c"); return
    words = text.split()
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        for sz in sizes:
            if max(stringWidth(a, font, sz), stringWidth(b, font, sz)) <= w - 4:
                _t(c, cx, cy + sz * 0.6, a, sz, font, align="c"); _t(c, cx, cy - sz * 0.6, b, sz, font, align="c"); return
    if h > w:
        c.saveState(); c.translate(cx, cy); c.rotate(90)
        for sz in sizes:
            if stringWidth(text, font, sz) <= h - 6:
                _t(c, 0, -sz * 0.3, text, sz, font, align="c"); break
        else:
            _t(c, 0, -2, text, sizes[-1], font, align="c")
        c.restoreState()
    else:
        _t(c, cx, cy, text, sizes[-1], font, align="c")


def _frame(c, P):
    c.setStrokeColor(black); c.setLineWidth(1.6); c.rect(18, 18, W - 36, H - 36)
    X0, Y0, TW = 744, 18, 462
    c.setLineWidth(1.2); c.rect(X0, Y0, TW, 120)

    def cell(x, y, w, h, label, value, vs=8, bold=False):
        c.setLineWidth(0.6); c.rect(x, y, w, h)
        if label: _t(c, x + 4, y + h - 7, label, 5.5, color=GRAY)
        if value: _t(c, x + 4, y + 5, value, vs, "Helvetica-Bold" if bold else "Helvetica")

    c.setLineWidth(0.6); c.rect(X0, Y0 + 90, TW, 30)
    _t(c, X0 + 8, Y0 + 101, "pauly", 17, "Helvetica-Bold", GREEN); _t(c, X0 + 49, Y0 + 109, "&co", 7, "Helvetica-Bold", NAVY)
    _t(c, X0 + 8, Y0 + 92.5, "Ingenieros y Arquitectos", 5.5, color=NAVY)
    _t(c, X0 + TW - 8, Y0 + 106, "Pauly y Compañía Ingenieros y Arquitectos S.A.", 8, "Helvetica-Bold", NAVY, "r")
    _t(c, X0 + TW - 8, Y0 + 96, "Céd. jurídica 3-101-798034 · www.paulyco.com · info@paulyco.com", 6.5, color=GRAY, align="r")
    cell(X0, Y0 + 66, TW, 24, "PROYECTO", P["name"], 8.5, True)
    cell(X0, Y0 + 42, 200, 24, "CLIENTE", P["client"]); cell(X0 + 200, Y0 + 42, 262, 24, "UBICACIÓN", P["location"])
    cell(X0, Y0 + 18, 262, 24, "PLANO", "PLANO DE TALLER", 8.5, True)
    cell(X0 + 262, Y0 + 18, 60, 24, "REVISIÓN", P["revision"], 7); cell(X0 + 322, Y0 + 18, 140, 24, "FECHA", P["date"])
    cell(X0, Y0, 262, 18, "", ""); _t(c, X0 + 4, Y0 + 5.5, "Resp.: " + P["responsible"], 7)
    cell(X0 + 262, Y0, 100, 18, "", ""); _t(c, X0 + 266, Y0 + 5.5, "Escala: " + P["scale"], 7)
    cell(X0 + 362, Y0, 100, 18, "", ""); _t(c, X0 + 366, Y0 + 5.5, "Hoja 1 de 1", 7.5, "Helvetica-Bold")


def build(data: dict, out) -> None:
    """data: project (name, client, location, date, revision, draft, responsible), title, layout (L.Layout), check (dict), parts (list of Part),
    margin, wall (w, h mm | None), notes (list), arrangement (text)."""
    P = dict(data["project"])
    lay: L.Layout = data["layout"]
    chk, margin, wall = data["check"], data["margin"], data.get("wall")
    nw, nh = lay.needed(margin)
    ww, wh = (wall or (None, None))
    draw_w, draw_h = max(nw, ww or 0), max(nh, wh or 0)
    pad = 260                                           # room for the dimension lines
    s = min((AREA[2] - AREA[0]) / (draw_w + pad), (AREA[3] - AREA[1]) / (draw_h + pad * 0.6))
    ox, oy = AREA[0] + 55, AREA[1] + 30
    px, py = (lambda mm: ox + mm * s), (lambda mm: oy + mm * s)
    P["scale"] = f"1:{round((72 / 25.4) / s):d}" if s else "sin escala"

    c = canvas.Canvas(out, pagesize=(W, H))
    c.setTitle(f"{P['name']} - Plano de taller"); c.setAuthor("Pauly y Compañía Ingenieros y Arquitectos S.A.")
    _frame(c, P)
    _t(c, 30, 748, "PLANO DE TALLER", 17, "Helvetica-Bold", NAVY)
    _t(c, 30, 734, data["title"], 7.5, color=GRAY)
    if P.get("draft"):
        _t(c, 1196, 748, "BORRADOR · REV " + P["revision"].split()[0], 10, "Helvetica-Bold", RED, "r")

    # floor + wall
    c.setStrokeColor(black); c.setLineWidth(1.6); c.line(ox - 30, oy, px(draw_w) + 20, oy)
    if wall:
        c.setLineWidth(1.4); c.setStrokeColor(NAVY); c.rect(px(0), py(0), ww * s, wh * s)
        _t(c, px(ww) - 4, py(wh) + 4, f"Pared propuesta {ww:g} × {wh:g} mm", 7, "Helvetica-Bold", NAVY, "r")
    # minimum work area
    c.setDash(6, 4); c.setStrokeColor(GRAY); c.setLineWidth(1); c.rect(px(0), py(0), nw * s, nh * s); c.setDash()
    _t(c, px(0) + 3, py(nh) - 9, "Área mínima de trabajo", 6.5, color=GRAY)

    def box(r: L.Rect):
        x, y = px(r.x + margin), py(r.y)
        c.setFillColor(HexColor(FILL.get(r.kind, "#EEEEEE"))); c.setStrokeColor(black); c.setLineWidth(1.0)
        if not r.real:
            c.setDash(4, 3)
        c.rect(x, y, r.w * s, r.h * s, fill=1, stroke=1); c.setDash()
        words = r.label
        _fit_label(c, words, x + r.w * s / 2, y + r.h * s / 2 + 1, r.w * s, r.h * s, 7)
        _t(c, x + r.w * s / 2, y + 3, f"{r.w:g} × {r.h:g}", 5.2 if r.w * s < 70 else 6, align="c", color=GRAY)

    for r in lay.rects:
        box(r)
    if lay.duct:
        d = lay.duct
        c.setFillColor(HexColor(FILL["duct"])); c.setStrokeColor(black); c.setLineWidth(1)
        c.rect(px(d.x + margin), py(d.y), d.w * s, d.h * s, fill=1, stroke=1)
        _t(c, px(d.x + margin) + d.w * s / 2, py(d.y) + d.h * s / 2 - 2.5, d.label, 6.5, "Helvetica-Bold", align="c")

    # dimension lines
    def dim_h(x1, x2, y, text):
        c.setStrokeColor(DIM); c.setLineWidth(0.6)
        c.line(px(x1), py(y), px(x2), py(y)); c.line(px(x1), py(y) - 3, px(x1), py(y) + 3); c.line(px(x2), py(y) - 3, px(x2), py(y) + 3)
        _t(c, (px(x1) + px(x2)) / 2, py(y) + 3, text, 7, color=DIM, align="c")

    def dim_v(y1, y2, x, text):
        c.setStrokeColor(DIM); c.setLineWidth(0.6)
        c.line(px(x), py(y1), px(x), py(y2)); c.line(px(x) - 3, py(y1), px(x) + 3, py(y1)); c.line(px(x) - 3, py(y2), px(x) + 3, py(y2))
        c.saveState(); c.translate(px(x) - 3, (py(y1) + py(y2)) / 2); c.rotate(90); _t(c, 0, 0, text, 7, color=DIM, align="c"); c.restoreState()

    dim_h(0, nw, -110, f"{nw:.0f} mm  (ancho mínimo)")
    dim_v(0, nh, draw_w + 90, f"{nh:.0f} mm  (alto mínimo)")
    if wall:
        dim_h(0, ww, -170, f"{ww:g} mm  (pared)")
        dim_v(0, wh, draw_w + 170, f"{wh:g} mm  (pared)")

    # result + parts table
    rx, ry = 744, 700
    if chk["fits"] is None:
        verdict, vcol = "SIN PARED INGRESADA", GRAY
    else:
        verdict, vcol = ("CUMPLE", OKG) if chk["fits"] else ("NO CUMPLE", RED)
    c.setFillColor(vcol); c.roundRect(rx, ry - 6, 150, 28, 5, fill=1, stroke=0)
    _t(c, rx + 75, ry + 4, verdict, 13, "Helvetica-Bold", white, "c")
    y = ry - 22
    rows = [f"Mínimo requerido: {chk['need_w']} × {chk['need_h']} mm (equipos + {margin:g} mm de margen)"]
    if chk["fits"] is not None:
        rows.append(f"Pared propuesta: {ww:g} × {wh:g} mm")
        rows.append(f"Ancho: {'sobran' if chk['slack_w'] >= 0 else 'faltan'} {abs(chk['slack_w'])} mm · Alto: {'sobran' if chk['slack_h'] >= 0 else 'faltan'} {abs(chk['slack_h'])} mm")
    rows.append(data["arrangement"])
    for r in rows:
        _t(c, rx, y, r, 7.5); y -= 11
    y -= 6
    _t(c, rx, y, "Equipos en la pared", 8.5, "Helvetica-Bold", NAVY); y -= 12
    c.setStrokeColor(GRAY); c.setLineWidth(0.5)
    _t(c, rx, y, "Equipo", 6.5, "Helvetica-Bold", GRAY); _t(c, rx + 190, y, "Cant.", 6.5, "Helvetica-Bold", GRAY, "r")
    _t(c, rx + 205, y, "An × Al × Fo (mm)", 6.5, "Helvetica-Bold", GRAY); _t(c, rx + 330, y, "Medida", 6.5, "Helvetica-Bold", GRAY); y -= 4
    c.line(rx, y, rx + 450, y); y -= 9
    for p in data["parts"]:
        _t(c, rx, y, p.label[:34], 7); _t(c, rx + 190, y, str(p.qty), 7, align="r")
        _t(c, rx + 205, y, f"{p.w:g} × {p.h:g} × {p.d:g}" if not p.missing else "sin ficha cargada", 7)
        _t(c, rx + 330, y, "ficha" if p.real else ("FALTA FICHA" if p.missing else "estimada"), 7, color=black if p.real else RED)
        y -= 10
    y -= 6
    _t(c, rx, y, "Notas", 8.5, "Helvetica-Bold", NAVY); y -= 11
    for n in data["notes"]:
        words, line = n.split(), ""
        for w_ in words:
            if len(line) + len(w_) > 88:
                _t(c, rx, y, line, 6.5, color=GRAY); y -= 8.5; line = w_
            else:
                line = (line + " " + w_).strip()
        _t(c, rx, y, line, 6.5, color=GRAY); y -= 10
    c.setDash(6, 4); c.setStrokeColor(GRAY); c.setLineWidth(1); c.line(30, 158, 60, 158); c.setDash()
    _t(c, 66, 155.5, "Área mínima de trabajo", 6.5)
    c.setDash(4, 3); c.setStrokeColor(black); c.setLineWidth(1.0); c.rect(190, 152, 22, 12); c.setDash()
    _t(c, 218, 155.5, "Medida estimada o nominal (por confirmar)", 6.5)
    c.setStrokeColor(black); c.setLineWidth(1.0); c.rect(400, 152, 22, 12)
    _t(c, 428, 155.5, "Medida de la ficha", 6.5)
    c.showPage(); c.save()
