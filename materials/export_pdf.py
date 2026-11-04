"""The materials list as a PDF to send to every dealer and ask for availability.

Same lines, order and section / group rows as the xlsx, without dealer, Bodega or price columns:
Detalle, Cantidad, Unidad, Comentarios. Only lines with a quantity are written.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from materials.catalog import SECTIONS

NAVY, GREEN, LINE = colors.HexColor("#1F2A4F"), colors.HexColor("#E8F0EC"), colors.HexColor("#C9D3CD")
_REPLACE = {"″": '"', "≥": ">=", "≤": "<=", "→": "->", "−": "-", "·": "-", "‑": "-"}


def _t(text) -> str:
    """Escaped text the standard PDF fonts can draw (Windows-1252): odd symbols are swapped, not boxed."""
    s = str(text or "")
    for bad, good in _REPLACE.items():
        s = s.replace(bad, good)
    return escape(s.encode("cp1252", "replace").decode("cp1252"))


def _qty(q) -> str:
    return str(int(q)) if float(q).is_integer() else f"{float(q):g}"


def build_pdf(lines: list[dict], title: str = "Solicitud de materiales", subtitle: str = "") -> bytes:
    base = ParagraphStyle("b", fontName="Helvetica", fontSize=8.6, leading=10.6)
    name = ParagraphStyle("n", parent=base)
    note = ParagraphStyle("c", parent=base, fontSize=7.8, leading=9.4, textColor=colors.HexColor("#555555"))
    right = ParagraphStyle("r", parent=base, alignment=2)
    head = ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", textColor=colors.white)
    h_title = ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=NAVY)
    h_sub = ParagraphStyle("s", parent=base, fontSize=9.5, leading=12, textColor=colors.HexColor("#444444"))
    sec = ParagraphStyle("sec", parent=base, fontName="Helvetica-Bold", fontSize=10, textColor=NAVY)
    grp = ParagraphStyle("g", parent=base, fontName="Helvetica-Bold", fontSize=8.6)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=title, author="Pauly & Co")
    widths = [86 * mm, 20 * mm, 15 * mm, doc.width - 121 * mm]
    wanted = [ln for ln in lines if ln.get("qty")]

    story = [Paragraph(_t(title), h_title)]
    if subtitle:
        story.append(Paragraph(_t(subtitle), h_sub))
    story.append(Paragraph(f"Fecha: {date.today().strftime('%d/%m/%Y')} &nbsp;·&nbsp; Favor indicar disponibilidad de cada línea.", h_sub))
    story.append(Spacer(1, 6 * mm))

    for section in SECTIONS:
        rows = [ln for ln in wanted if ln["section"] == section]
        if not rows:
            continue
        data = [[Paragraph(_t(section), head), Paragraph("Cantidad", ParagraphStyle("hr", parent=head, alignment=2)),
                 Paragraph("Unidad", head), Paragraph("Comentarios", head)]]
        style = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        group = None
        for ln in rows:
            if ln["group"] and ln["group"] != group:
                data.append([Paragraph(_t(ln["group"]), grp), "", "", ""])
                r = len(data) - 1
                style += [("BACKGROUND", (0, r), (-1, r), GREEN), ("SPAN", (0, r), (-1, r))]
            group = ln["group"]
            data.append([Paragraph(_t(ln["name"]), name), Paragraph(_qty(ln["qty"]), right),
                         Paragraph(_t(ln["unit"]), base), Paragraph(_t(ln.get("comment")), note)])
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle(style))
        story += [table, Spacer(1, 5 * mm)]

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(d.leftMargin, 9 * mm, "Pauly & Co · lista de materiales sin precios")
        canvas.drawRightString(letter[0] - d.rightMargin, 9 * mm, f"Página {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
