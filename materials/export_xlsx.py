"""The materials list as an .xlsx in the layout of Oscar's "Solicitud de materiales" workbook.

Same header and the same section / group rows, dealer columns (Avolta … MAZ) and Bodega left
empty: he sends the sheet to every dealer and marks the cheapest one with an "x" when the quotes
come back. Only lines with a quantity are written; no prices.
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from materials.catalog import SECTIONS

HEADER = ["Detalle", "Cantidad", "Unidad", "Comentarios", "Avolta", "ALCO", "Ditesa", "HCG", "Protel", "Electrocaribe", "MAZ", "Bodega"]


def build_workbook(lines: list[dict], title: str = "Solicitud de materiales") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Materiales"
    wb.properties.title = title
    bold, fill = Font(bold=True), PatternFill("solid", fgColor="E8F0EC")
    ws.append(HEADER)
    for cell in ws[1]:
        cell.font, cell.fill = bold, fill
    ws.freeze_panes = "A2"

    wanted = [ln for ln in lines if ln.get("qty")]
    for section in SECTIONS:
        rows = [ln for ln in wanted if ln["section"] == section]
        if not rows:
            continue
        ws.append([section, "Cantidad", "Unidad"])
        for cell in ws[ws.max_row]:
            cell.font, cell.fill = bold, fill
        group = None
        for ln in rows:
            if ln["group"] and ln["group"] != group:
                ws.append([ln["group"]])
                ws[ws.max_row][0].font = bold
            group = ln["group"]
            ws.append([ln["name"], ln["qty"], ln["unit"], ln.get("comment") or ""])
            ws[ws.max_row][1].alignment = Alignment(horizontal="right")
    for i, width in enumerate([62, 10, 8, 44] + [11] * 8, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
