"""Industrial plan reader: panel schedules (tableros) of a three-phase plant -> the Step 5 loads table.

The residential reader (`tablero_parser.parse_tablero`) sends ONE image/PDF to the model and assumes a house. A plant's electrical
drawing is different: one big sheet holds many panel schedules (TP, TR0..TR3, TT1..), drawn as vectors, too small to read in one go.
So this reader works in two passes, which also makes it versatile (a full sheet, a single board, a photo, several files):

  1. LOCATE  each panel schedule on a page (a low-resolution look at the whole page -> bounding boxes),
  2. EXTRACT each one from a high-resolution crop (board header + every circuit + the printed totals), several in parallel.

Then, in plain Python (deterministic, editable, no AI):
  * circuits that only FEED another board that was also read are dropped (no double counting),
  * every circuit gets an industrial CATEGORY (refrigeration, defrost, door heaters, process, HVAC, lighting...) from keywords,
  * every category gets default hours/day and days/month. These are FIRST-PASS ASSUMPTIONS, not measurements: a drawing gives
    installed watts, never use. The engineer edits them in the Step 5 table, compressors and freezing chambers above all,
  * the sum of each board's circuits is checked against the total printed on the drawing.

Output rows keep the Step 5 table's shape (Descripción, W, Und, h/día, días/mes) plus `Categoría` and `Tablero`.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

MODEL = os.environ.get("PLANO_PARSER_MODEL", os.environ.get("LOADS_PARSER_MODEL", "claude-sonnet-5-5"))
LOCATE_DPI = 100
CROP_TARGET_PX = 2400          # width of a board crop sent for extraction
CROP_MIN_DPI, CROP_MAX_DPI = 100, 300
MAX_WORKERS = 4
TOTAL_TOLERANCE = 0.02         # circuits vs the drawing's printed total

# ── categories: key -> (label, h/día, días/mes, note) ─────────────────────────
# First-pass assumptions. Refrigeration runs around the clock; its real duty depends on the chambers' heat load: estimate it.
CATEGORIES: dict[str, tuple[str, float, int, str]] = {
    "compresores":  ("Compresores / rack",            14.0, 30, "estimar: ciclo real del rack según la carga de las cámaras"),
    "refrigeracion": ("Refrigeración (evaporadores)",  20.0, 30, "ventiladores y controles de cámaras, casi continuo"),
    "deshielo":     ("Deshielo",                        1.5, 30, "unos 3 ciclos de 30 min al día"),
    "puertas":      ("Resistencias de puerta / drenaje", 8.0, 30, "con termostato"),
    "proceso":      ("Proceso / producción",           10.0, 26, "según turnos de producción"),
    "hvac":         ("A/C y climatización",             8.0, 26, ""),
    "ventilacion":  ("Ventilación / extractores",      12.0, 30, ""),
    "bombeo":       ("Bombeo",                         10.0, 30, ""),
    "iluminacion":  ("Iluminación",                    12.0, 30, ""),
    "tomas":        ("Tomacorrientes",                  3.0, 26, "capacidad del circuito, no consumo"),
    "respaldo":     ("UPS / telecom / alarmas",        24.0, 30, ""),
    "otros":        ("Otros",                           8.0, 26, "revisar"),
}

# Order matters: the first rule that matches wins.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("deshielo", ("deshielo", "descongel")),
    ("puertas", ("resistencia de puerta", "resistencias de puerta", "drenaje", "umbral")),
    ("respaldo", (" ups", "ups ", "telecom", "alarma", "detector", "cctv")),
    ("iluminacion", ("ilumin", "luminaria")),
    ("tomas", ("toma general", "tomas general", "tomacorriente", "tomas ", "toma ", "toma de", "tomas de")),
    ("compresores", ("compresor", "rack", "tornillo")),
    ("bombeo", ("bomba", "bombeo", "hidroneumatic")),
    ("ventilacion", ("extractor", "inyector", "ventilador")),
    ("refrigeracion", ("evaporador", "condensador", "camara", "valvula", "controlador", "congelador", "tunel")),
    ("proceso", ("sellad", "vacio", "picadora", "hielo", "skin", "marmita", "cobertor", "balanza", "transformadora", "ceviche",
                 "maquina", "banda", "cortadora", "etiquet", "termoform", "lavad")),
]
_HVAC_BOARD = ("hvac", "climatiz", "aire acondicionado")
_FEEDER = re.compile(r"^\s*tablero\b[\s\-:]*([a-z0-9]+)", re.I)
_SKIP = ("prevista", "reserva", "espacio libre", "disponible")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def categorize(description: str, board_title: str = "") -> str:
    """Industrial category of a circuit from its text; the board's title tips cooling units to HVAC on an HVAC board."""
    d = " " + _norm(description) + " "
    on_hvac = any(k in _norm(board_title) for k in _HVAC_BOARD)
    if on_hvac and any(k in d for k in ("evaporador", "condensador", "unidad", "minisplit", "split")):
        return "hvac"
    if any(k in d for k in ("a/c", "aire acondicionado", "minisplit", "mini split")):
        return "hvac"
    for key, words in _RULES:
        if any(w in d for w in words):
            return key
    return "otros"


# ── rendering / cropping ─────────────────────────────────────────────────────


def _is_pdf(media_type: str) -> bool:
    return "pdf" in (media_type or "").lower()


def _png_b64(png: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(png).decode()}}


def _pdftoppm(file_bytes: bytes, index: int, dpi: int) -> bytes:
    """One PDF page as PNG through poppler's `pdftoppm` (the fallback when PyMuPDF is not installed)."""
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "in.pdf"
        src.write_bytes(file_bytes)
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(index + 1), "-l", str(index + 1), "-singlefile", str(src), str(Path(d) / "out")],
                       check=True, capture_output=True, timeout=120)
        return (Path(d) / "out.png").read_bytes()


def _pdf_page_count(file_bytes: bytes) -> int:
    import subprocess
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "in.pdf"
        src.write_bytes(file_bytes)
        out = subprocess.run(["pdfinfo", str(src)], check=True, capture_output=True, text=True, timeout=60).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 1


def _pages(file_bytes: bytes, media_type: str) -> list:
    """One 'page' object per PDF page or image. kind: 'fitz' (PyMuPDF), 'poppler' (pdftoppm fallback) or 'img'."""
    if _is_pdf(media_type):
        try:
            import fitz
        except ImportError:
            from PIL import Image

            n = _pdf_page_count(file_bytes)
            pages = []
            for i in range(n):
                png = _pdftoppm(file_bytes, i, LOCATE_DPI)
                w, h = Image.open(io.BytesIO(png)).size
                pages.append({"kind": "poppler", "bytes": file_bytes, "index": i, "locate_png": png, "w_pt": w * 72.0 / LOCATE_DPI, "h_pt": h * 72.0 / LOCATE_DPI})
            return pages
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        return [{"kind": "fitz", "doc": doc, "index": i} for i in range(len(doc))]
    from PIL import Image

    return [{"kind": "img", "img": Image.open(io.BytesIO(file_bytes)).convert("RGB"), "index": 0}]


def _page_png(page: dict, dpi: int = LOCATE_DPI) -> bytes:
    if page["kind"] == "fitz":
        return page["doc"][page["index"]].get_pixmap(dpi=dpi).tobytes("png")
    if page["kind"] == "poppler":
        return page["locate_png"]
    img = page["img"].copy()
    img.thumbnail((2000, 2000))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _crop_png(page: dict, bbox: list[float]) -> bytes:
    """High-resolution crop of a board; `bbox` = [x0, y0, x1, y1] as fractions of the page, grown by a small margin."""
    x0, y0, x1, y1 = (max(0.0, min(1.0, v)) for v in bbox)
    x0, y0, x1, y1 = max(0.0, x0 - 0.008), max(0.0, y0 - 0.008), min(1.0, x1 + 0.008), min(1.0, y1 + 0.008)
    from PIL import Image

    if page["kind"] == "fitz":
        import fitz

        p = page["doc"][page["index"]]
        r = p.rect
        clip = fitz.Rect(r.x0 + x0 * r.width, r.y0 + y0 * r.height, r.x0 + x1 * r.width, r.y0 + y1 * r.height)
        dpi = max(CROP_MIN_DPI, min(CROP_MAX_DPI, int(CROP_TARGET_PX / max(clip.width / 72.0, 0.1))))
        return p.get_pixmap(dpi=dpi, clip=clip).tobytes("png")
    if page["kind"] == "poppler":
        width_in = (x1 - x0) * page["w_pt"] / 72.0
        dpi = max(CROP_MIN_DPI, min(CROP_MAX_DPI, int(CROP_TARGET_PX / max(width_in, 0.1))))
        img = Image.open(io.BytesIO(_pdftoppm(page["bytes"], page["index"], dpi))).convert("RGB")
    else:
        img = page["img"]
    W, H = img.size
    c = img.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
    if page["kind"] == "img" and c.width < CROP_TARGET_PX:
        scale = min(3.0, CROP_TARGET_PX / max(c.width, 1))
        c = c.resize((int(c.width * scale), int(c.height * scale)), Image.LANCZOS)
    out = io.BytesIO()
    c.save(out, "PNG")
    return out.getvalue()


# ── the two model passes ─────────────────────────────────────────────────────

_LOCATE_PROMPT = """This is a page of an electrical drawing (plano eléctrico) from Costa Rica. Find every PANEL SCHEDULE TABLE (tablero: a table
with a title bar like "TR1  TABLERO DE EQUIPOS DE REFRIGERACION", the header FASES / VOLTAJE / INTERRUPTOR PRINCIPAL, a list of numbered
circuits, and totals rows like CARGA TOTAL / DEMANDA MAXIMA / CORRIENTE DE LINEA).

Return ONLY JSON: {"boards": [{"id": "TR1", "title": "TABLERO DE EQUIPOS DE REFRIGERACION - SECTOR 1", "bbox": [x0, y0, x1, y1]}]}
bbox = fractions (0 to 1) of the image width / height, from the top-left corner of the title bar to the bottom-right corner of the totals rows,
enclosing the WHOLE table. Do not include one-line diagrams, symbol legends, notes, or summary tables of the project.
If the image is itself a single panel schedule (or a photo of one), return one board with bbox [0, 0, 1, 1]. If there are none, return {"boards": []}."""

_EXTRACT_PROMPT = """This is one electrical PANEL SCHEDULE (tablero) from a Costa Rican plant drawing. Read it exactly as printed.

Return ONLY JSON:
{"board": "TR1", "name": "TABLERO DE EQUIPOS DE REFRIGERACION - SECTOR 1 - NIVEL 1", "phases": 3, "voltage": 208, "main_breaker_a": 200,
 "total_w": 58800, "reserved_w": 0, "demand_w": 58800, "demand_factor": 1,
 "circuits": [{"ckt": "1,3", "description": "EVAPORADORAS Y CONTROLADORES (CAMARA - INYECCION)", "poles": 2, "amps": 20, "volts": 208, "load_w": 1200}]}

Rules:
- One entry per CIRCUIT. A multi-pole circuit spans several rows (one per leg, each with its own watts and phase A/B/C) and its description is
  printed once: load_w is the SUM of all its legs' watts (a 2-pole circuit with 600 + 600 W is load_w 1200; a 3-pole with 2400 x 3 is 7200).
- Keep the description as printed (Spanish), with the area in parentheses.
- Skip empty circuit rows and "Carga Prevista" (spare/future); do not invent anything that is not printed.
- total_w / demand_w / demand_factor are the board's printed CARGA TOTAL (W), DEMANDA MAXIMA (W), FACTOR DE DEMANDA; null if absent.
- reserved_w is the number printed next to "Carga Prevista" at the bottom of the circuit list (future load already counted in CARGA TOTAL); 0 if none.
- If a circuit's watts are unreadable, set load_w to null and keep the circuit."""


def _first_text(response) -> str:
    return next(b.text for b in response.content if getattr(b, "type", "") == "text").strip()


def _json(text: str):
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise


def _ask(client, png: bytes, prompt: str, max_tokens: int) -> dict:
    r = client.messages.create(model=MODEL, max_tokens=max_tokens,
                               messages=[{"role": "user", "content": [_png_b64(png), {"type": "text", "text": prompt}]}])
    return _json(_first_text(r))


def locate_boards(client, page: dict) -> list[dict]:
    data = _ask(client, _page_png(page), _LOCATE_PROMPT, 4000)
    out = []
    for b in data.get("boards") or []:
        bb = b.get("bbox")
        if isinstance(bb, list) and len(bb) == 4 and bb[2] > bb[0] and bb[3] > bb[1]:
            out.append({"id": str(b.get("id") or "").strip(), "title": str(b.get("title") or "").strip(), "bbox": [float(v) for v in bb]})
    return out


def extract_board(client, page: dict, bbox: list[float]) -> dict:
    return _ask(client, _crop_png(page, bbox), _EXTRACT_PROMPT, 12000)


# ── assembling the loads table (pure, testable) ──────────────────────────────


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_loads(boards: list[dict]) -> dict:
    """Extracted boards -> {"loads": rows, "boards": summaries, "notes": [...]}. Pure function over the model's JSON."""
    ids = {_norm(b.get("board") or "").replace(" ", "") for b in boards if b.get("board")}
    rows: list[dict] = []
    summaries: list[dict] = []
    notes: list[str] = []
    for b in boards:
        bid = str(b.get("board") or "?").strip()
        title = str(b.get("name") or "")
        kept_w, listed_w, skipped_feeders, spare_w = 0.0, 0.0, [], 0.0
        for c in b.get("circuits") or []:
            desc = str(c.get("description") or "").strip()
            w = _num(c.get("load_w"))
            if not desc:
                continue
            if _norm(desc).strip().startswith(_SKIP):
                spare_w += w or 0.0                             # future load: not installed, so not consumption
                continue
            if w is None or w <= 0:
                notes.append(f"{bid}: «{desc}» sin potencia legible; se omitió.")
                continue
            listed_w += w
            m = _FEEDER.match(desc)
            if m and _norm(m.group(1)).replace(" ", "") in ids and _norm(m.group(1)) != _norm(bid):
                skipped_feeders.append(m.group(1).upper())          # it feeds a board that is read on its own
                continue
            cat = categorize(desc, title)
            label, h, d, _ = CATEGORIES[cat]
            rows.append({"Descripción": f"{bid} · {desc}", "W": round(w), "Und": 1, "h/día": h, "días/mes": d, "Categoría": label, "Tablero": bid})
            kept_w += w
        total = _num(b.get("total_w"))
        reserved = (_num(b.get("reserved_w")) or 0.0) + spare_w
        if total and (listed_w or reserved):
            diff = abs(listed_w + reserved - total) / total
            if diff > TOTAL_TOLERANCE:
                notes.append(f"{bid}: los circuitos suman {listed_w:,.0f} W (+ {reserved:,.0f} W previstos) y el plano dice {total:,.0f} W "
                             f"({diff * 100:.1f} % de diferencia): revisar.")
        if reserved:
            notes.append(f"{bid}: {reserved:,.0f} W son carga prevista (futura) y no se cuentan como consumo.")
        if skipped_feeders:
            notes.append(f"{bid}: se omitieron las líneas que alimentan otros tableros ya leídos ({', '.join(skipped_feeders)}) para no contarlas dos veces.")
        summaries.append({"board": bid, "name": title, "phases": b.get("phases"), "voltage": b.get("voltage"),
                          "circuits_w": round(listed_w), "reserved_w": round(reserved), "printed_total_w": total, "demand_w": _num(b.get("demand_w")), "counted_w": round(kept_w)})
    return {"loads": rows, "boards": summaries, "notes": notes}


def parse_planos(files: list[tuple[bytes, str]], log=None) -> dict:
    """Read one or more plan files (PDF pages or images) and return the loads table. Raises ValueError when no panel schedule is found."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    jobs, notes = [], []
    for fi, (data, mt) in enumerate(files):
        for page in _pages(data, mt):
            try:
                found = locate_boards(client, page)
            except Exception as exc:                    # noqa: BLE001 — a page that fails to locate must not sink the other pages
                notes.append(f"Archivo {fi + 1}, página {page['index'] + 1}: no se pudo ubicar tableros ({exc}).")
                continue
            if not found:
                notes.append(f"Archivo {fi + 1}, página {page['index'] + 1}: sin tableros (se omitió).")
            jobs += [(page, b) for b in found]
    if not jobs:
        raise ValueError("No se encontró ningún tablero en los planos. " + " ".join(notes))

    def run(job):
        page, b = job
        try:
            out = extract_board(client, page, b["bbox"])
            out.setdefault("board", b["id"])
            return out
        except Exception as exc:                        # noqa: BLE001
            notes.append(f"{b['id'] or 'tablero'}: no se pudo leer ({exc}).")
            return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        boards = [x for x in pool.map(run, jobs) if x]
    res = build_loads(boards)
    res["notes"] = notes + res["notes"]
    if not res["loads"]:
        raise ValueError("Se leyeron los tableros pero no se encontraron cargas. " + " ".join(res["notes"]))
    return res
