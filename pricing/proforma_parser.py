"""Parse a supplier proforma PDF into header + line items.

Layout-based (pdfplumber word positions), not OCR/LLM: the Costa Rican dealer
proformas this tool sees (HCG, Nundi) share one table layout — CANTIDAD | Imp |
DESCRIPCIÓN | PRECIO UNITARIO | PRECIO TOTAL — with per-line tax tags
("EXEV" = exempt, "IVA 13"). Descriptions wrap onto lines above/below the row
that carries the numbers, so text lines are attached to the nearest numeric row.

Everything parsed is only a *proposal*: the import screen shows it for review,
and `validation` tells the user whether the lines add up to the printed
subtotal. Nothing here writes to the database.
"""
from __future__ import annotations

import io
import re
from datetime import date

_NUM = re.compile(r"^-?[\d,]*\.?\d+$")


def _num(text: str) -> float | None:
    t = (text or "").replace("$", "").replace(" ", "")
    if not t or not _NUM.match(t):
        return None
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return None


def _cluster(words: list[dict], tol: float = 2.5) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


def _row_text(row: list[dict]) -> str:
    return " ".join(w["text"] for w in row)


def _join_amount(tokens: list[dict]) -> float | None:
    """Join kerning-split digit runs ("1" + "0,149.50" -> 10,149.50)."""
    return _num("".join(t["text"] for t in tokens if t["text"] != "$"))


def _tax_rate(tag: str) -> tuple[float | None, str]:
    t = (tag or "").upper().replace(" ", "")
    if not t:
        return None, ""
    if t.startswith("EXEV") or t.startswith("EXENT") or t == "EXE":
        return 0.0, "exento"
    m = re.match(r"IVA(\d+(?:\.\d+)?)", t)
    if m:
        return float(m.group(1)) / 100.0, f"IVA {m.group(1)}%"
    return None, tag


def _parse_date(text: str) -> str | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text or "")
    if not m:
        return None
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # d/m vs m/d: whichever is impossible as a month decides; Costa Rica's
    # convention (d/m) wins when both readings are valid — the import screen
    # shows an editable date either way.
    day, month = (a, b) if (a > 12 or b <= 12) else (b, a)
    try:
        return date(y, month, day).isoformat()
    except ValueError:
        return None


def parse_proforma(pdf_bytes: bytes) -> dict:
    """Returns {supplier, doc_number, doc_date, lines[], totals{}, validation{}, warnings[]}."""
    import pdfplumber

    warnings: list[str] = []
    lines: list[dict] = []
    header: dict = {"supplier": "", "doc_number": "", "doc_date": None}
    totals: dict = {}
    bounds: dict | None = None

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pno, page in enumerate(pdf.pages):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            rows = _cluster(words)

            # -- header (first page only) --------------------------------------
            if pno == 0:
                for i, r in enumerate(rows):
                    text = _row_text(r)
                    if not header["doc_number"] and r[0]["text"].lower().startswith("proforma"):
                        pass
                    m = re.search(r"\b([A-Z]{0,2}\d{1,4}-\d{4})\b", text)
                    if m and not header["doc_number"] and r[0]["x0"] > 300 and "-" in m.group(1) and not re.search(r"\d-\d{3}-\d{6}", text):
                        header["doc_number"] = m.group(1)
                # supplier = first meaningful text line left of centre
                for r in rows[:6]:
                    left = [w for w in r if w["x0"] < 300]
                    t = " ".join(w["text"] for w in left).strip()
                    if t and not t.lower().startswith("proforma") and not re.fullmatch(r"[\d-]+", t):
                        header["supplier"] = t
                        break

            # -- column bounds from the table header row -----------------------
            hdr = None
            for r in rows:
                labels = {w["text"].upper(): w for w in r}
                if "CANTIDAD" in labels and "IMP" in {k.upper() for k in labels}:
                    hdr = r
                    break
            if hdr is not None:
                by = {w["text"].upper(): w for w in hdr}
                pu = [w for w in hdr if w["text"].upper() == "PRECIO"]
                if len(pu) >= 2:
                    bounds = {
                        "imp_x0": by["IMP"]["x0"] - 6,
                        "desc_x0": 186.0,
                        "unit_x0": pu[0]["x0"] + 10,
                        "total_x0": pu[1]["x0"] - 8,
                        "hdr_top": hdr[0]["top"],
                    }
                if pno == 0:
                    for i, r in enumerate(rows):
                        if any(w["text"].upper() == "FECHA" for w in r) and i + 1 < len(rows):
                            header["doc_date"] = _parse_date(_row_text(rows[i + 1])) or header["doc_date"]
                        # date row can sit above its label in some layouts
                    if not header["doc_date"]:
                        for r in rows:
                            d = _parse_date(_row_text(r))
                            if d:
                                header["doc_date"] = d
                                break
            if bounds is None:
                warnings.append("No se encontró la tabla de cantidades y precios en el PDF.")
                continue

            # -- totals (labels right of the description column) ----------------
            for r in rows:
                first = r[0]["text"].upper()
                if first in ("SUBTOTAL", "IVA", "DESCUENTO", "TOTAL") and r[0]["x0"] > bounds["unit_x0"] - 40:
                    amt = _join_amount([w for w in r if w["x0"] > bounds["total_x0"] and w["text"] != "$"
                                        and _num(w["text"]) is not None and w is not r[0]])
                    # IVA row is "IVA 13 $ 258.64": drop the "13"
                    if first == "IVA":
                        amt = _join_amount([w for w in r if w["x0"] > bounds["total_x0"] + 20
                                            and _num(w["text"]) is not None])
                    if amt is not None:
                        totals.setdefault(first.lower(), amt)

            # -- numeric (item) rows -------------------------------------------
            item_idx: list[int] = []
            for idx, r in enumerate(rows):
                if r[0]["top"] <= bounds["hdr_top"] + 3:
                    continue
                qty_w = [w for w in r if w["x1"] < bounds["imp_x0"] + 4 and _num(w["text"]) is not None]
                tot_w = [w for w in r if w["x0"] >= bounds["total_x0"] and w["text"] != "$"]
                unit_w = [w for w in r if bounds["unit_x0"] - 14 <= w["x0"] < bounds["total_x0"] and w["text"] != "$"]
                if qty_w and tot_w and unit_w and _join_amount(tot_w) is not None:
                    item_idx.append(idx)

            # ignore the totals block that sits below the table
            table_bottom = None
            for r in rows:
                if r[0]["text"].upper() == "SUBTOTAL":
                    table_bottom = r[0]["top"]
                    break

            items = []
            for idx in item_idx:
                r = rows[idx]
                if table_bottom is not None and r[0]["top"] >= table_bottom - 1:
                    continue
                qty_w = [w for w in r if w["x1"] < bounds["imp_x0"] + 4]
                tag_w = [w for w in r if bounds["imp_x0"] <= w["x0"] < bounds["desc_x0"]]
                unit_w = [w for w in r if bounds["unit_x0"] - 14 <= w["x0"] < bounds["total_x0"] and w["text"] != "$"]
                tot_w = [w for w in r if w["x0"] >= bounds["total_x0"] and w["text"] != "$"]
                rate, tax_label = _tax_rate(" ".join(w["text"] for w in tag_w))
                items.append({
                    "top": r[0]["top"], "qty": _join_amount(qty_w), "tag": " ".join(w["text"] for w in tag_w),
                    "iva_rate": rate, "tax_label": tax_label,
                    "unit_usd": _join_amount(unit_w), "total_usd": _join_amount(tot_w),
                    "desc_rows": [],
                })

            # description text: every row in the table area that is not a numeric row
            if items:
                last_top = table_bottom if table_bottom is not None else page.height
                for idx, r in enumerate(rows):
                    if idx in item_idx or r[0]["top"] <= bounds["hdr_top"] + 3 or r[0]["top"] >= last_top - 1:
                        continue
                    desc = [w for w in r if bounds["desc_x0"] <= w["x0"] < bounds["unit_x0"] - 14]
                    if not desc:
                        continue
                    near = min(items, key=lambda it: abs(it["top"] - r[0]["top"]))
                    near["desc_rows"].append((r[0]["top"], " ".join(w["text"] for w in desc)))

            for it in items:
                # the numeric row's own description words (same cluster)
                row = next((r for r in rows if abs(r[0]["top"] - it["top"]) < 0.5), [])
                own = [w for w in row if bounds["desc_x0"] <= w["x0"] < bounds["unit_x0"] - 14]
                parts = list(it["desc_rows"])
                if own:
                    parts.append((it["top"], " ".join(w["text"] for w in own)))
                parts.sort(key=lambda p: p[0])
                desc = re.sub(r"\s+", " ", " ".join(p[1] for p in parts)).strip()
                desc = re.sub(r"(CK-)\s+(\d)", r"\1\2", desc)
                lines.append({
                    "description": desc, "qty": it["qty"], "unit_usd": it["unit_usd"],
                    "total_usd": it["total_usd"], "iva_rate": it["iva_rate"],
                    "tax_label": it["tax_label"] or "sin indicar",
                })

    sum_lines = round(sum(l["total_usd"] or 0 for l in lines), 2)
    subtotal = totals.get("subtotal")
    validation = {
        "sum_lines": sum_lines,
        "subtotal": subtotal,
        "ok": subtotal is not None and abs(sum_lines - subtotal) < 0.05 and bool(lines),
    }
    if not lines:
        warnings.append("No se reconocieron líneas de artículos.")
    elif subtotal is None:
        warnings.append("No se encontró el subtotal para validar las líneas.")
    elif not validation["ok"]:
        warnings.append(f"Las líneas suman {sum_lines:,.2f} pero el subtotal impreso es {subtotal:,.2f}: revisa la tabla.")
    for l in lines:
        if l["qty"] and l["unit_usd"] and abs(l["qty"] * l["unit_usd"] - (l["total_usd"] or 0)) > 0.05:
            warnings.append(f"«{l['description'][:40]}»: cantidad × unitario no coincide con el total de la línea.")
        if l["iva_rate"] is None:
            warnings.append(f"«{l['description'][:40]}»: sin indicador de IVA — se asume 0 %.")
    return {**header, "lines": lines, "totals": totals, "validation": validation, "warnings": warnings}
