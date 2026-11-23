"""Pieces every Pauly & Co engineering sheet shares (unifilar, plano de taller, plano de techo): the SIMBOLOGÍA block at the bottom-left, where
the legend entries sit on the same rows and columns on every sheet. The title block is `plano.generate_plano._frame`; the logo is `utils.pdf_logo`."""
from __future__ import annotations

from reportlab.lib.colors import HexColor, black

NAVY = HexColor("#12385B")
MGRAY = HexColor("#9AA3AD")
LEGEND_ROWS = (104, 85, 66, 47, 28)     # y of the five legend rows (pt)
COL1_SAMPLE = (30, 70)                  # x range of the line / swatch sample, first column
COL1_TEXT = 80
COL2_SAMPLE = 255                       # x of the symbol, second column
COL2_TEXT = 275


def legend_header(c) -> None:
    """«SIMBOLOGÍA» and its rule, bottom-left (as in the unifilar)."""
    c.setFillColor(NAVY); c.setFont("Helvetica-Bold", 7.5); c.drawString(30, 125, "SIMBOLOGÍA")
    c.setLineWidth(0.6); c.setStrokeColor(MGRAY); c.line(24, 120, 735, 120)


def legend_text(c, x: float, row: int, text: str) -> None:
    """Label of legend row `row` (0-4) at x."""
    c.setFillColor(black); c.setFont("Helvetica", 7); c.drawString(x, LEGEND_ROWS[row] - 2.5, text)


# ── numbering and location of the sheets (the same on every sheet's title block) ──────────────────────────────────────
SHEET_ORDER = ("unifilar", "techo", "taller")      # the set, in delivery order: 1 Diagrama unifilar, 2 Plano de techo, 3 Plano de taller


def sheet_no(kind: str) -> str:
    """«Hoja 2 de 3» for a sheet kind of SHEET_ORDER."""
    return f"Hoja {SHEET_ORDER.index(kind) + 1} de {len(SHEET_ORDER)}" if kind in SHEET_ORDER else "Hoja 1 de 1"


def location_fields(project: dict | None, blob: dict | None) -> dict:
    """{province, canton, district} of the title block. Order of preference: what was typed for this project's sheets (`tech_spec["sheet_location"]`),
    the quote's site step (province, canton or city, district) and last the client's «Ciudad, Provincia» text."""
    own = ((project or {}).get("tech_spec") or {}).get("sheet_location") or {}
    site = (blob or {}).get("site") or {}
    loc = (((blob or {}).get("client") or {}).get("location") or "")
    first, _, rest = [x.strip() for x in loc.partition(",")]
    return {"province": own.get("province") or site.get("province") or rest,
            "canton": own.get("canton") or site.get("canton") or site.get("city") or first,
            "district": own.get("district") or site.get("district") or ""}


def status_fields(project: dict | None) -> dict:
    """{revision, draft}: the one switch of the set. `tech_spec["sheet_status"] = {"draft": bool, "revision": "A"}`; without it the sheets are drafts
    (a quote preview, or a project nobody has marked as final). Draft sheets print «BORRADOR · REV A» and «A (borrador)»; final ones just «A»."""
    st = ((project or {}).get("tech_spec") or {}).get("sheet_status") or {}
    draft = bool(st.get("draft", True))
    rev = (st.get("revision") or "A").strip() or "A"
    return {"revision": f"{rev} (borrador)" if draft else rev, "draft": draft}


def title_fields(project: dict | None, blob: dict | None, kind: str) -> dict:
    """The title-block keys every sheet adds to its project dict (they win over the sheet's own defaults)."""
    return {**location_fields(project, blob), "sheet_no": sheet_no(kind), **status_fields(project)}
