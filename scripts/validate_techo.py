"""Plano de techo: geometry, saved shape, fit summary and the PDF. Run: python scripts/validate_techo.py"""
from __future__ import annotations

import io
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from techo import geometry as G, service as S  # noqa: E402

fails = []


def check(label, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'} {label}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(label)


W_, H_, GAP = 1.134, 2.278, 0.02            # SUN600-class module and the mid clamp gap
INFO = {"panel": {"brand": "Sunergy", "model": "SUN600", "wp": 600, "width_m": W_, "height_m": H_}, "counts": [8, 8], "panel_count": 16, "gap_m": GAP}

# block size: 8 modules in a row, portrait -> 8 widths + 7 gaps wide, one module high
b = G.block_layout(8, 1, W_, H_, GAP)
check("8 modules in one row: width = 8 modules + 7 mid-clamp gaps", (round(b["w"], 3), round(b["h"], 3), b["cols"]), (round(8 * W_ + 7 * GAP, 3), H_, 8))
b2 = G.block_layout(8, 2, W_, H_, GAP)
check("8 modules in 2 rows: 4 columns, height = 2 modules + 1 gap", (b2["cols"], round(b2["h"], 3)), (4, round(2 * H_ + GAP, 3)))
check("landscape swaps the module sides", G.module_dims(W_, H_, "landscape"), (H_, W_))

# polygons: first module corner of an unrotated block sits at -W/2, -H/2 around the centre
s = {"id": 1, "count": 8, "rows": 1, "orient": "portrait", "x": 1000.0, "y": 500.0, "rot": 0.0}
ps = G.module_polys(s, W_, H_, GAP, 100.0)
check("8 module quads", len(ps), 8)
check("first quad starts at the block's top-left corner (px)", tuple(round(v, 1) for v in ps[0][0]), (round(1000 - b["w"] / 2 * 100, 1), round(500 - H_ / 2 * 100, 1)))
check("two neighbours are one gap apart (px)", round(ps[1][0][0] - ps[0][1][0], 3), round(GAP * 100, 3))
r = G.module_polys({**s, "rot": 90.0}, W_, H_, GAP, 100.0)
check("a 90 degree turn swaps the block's width and height", (round(max(p[0] for q in r for p in q) - min(p[0] for q in r for p in q), 1), round(max(p[1] for q in r for p in q) - min(p[1] for q in r for p in q), 1)),
      (round(H_ * 100, 1), round(b["w"] * 100, 1)))

# overlap
a, bq = [(0, 0), (10, 0), (10, 10), (0, 10)], [(5, 5), (15, 5), (15, 15), (5, 15)]
check("overlapping squares", G.convex_overlap(a, bq), True)
check("squares that only touch do not overlap", G.convex_overlap(a, [(10, 0), (20, 0), (20, 10), (10, 10)]), False)
check("a rotated square far away does not overlap", G.convex_overlap(a, [(40, 0), (50, 10), (40, 20), (30, 10)]), False)
check("point in polygon", (G.point_in_polygon((5, 5), a), G.point_in_polygon((15, 5), a)), (True, False))

# fit check with a roof outline
two = [{**s, "id": 1, "y": 300.0}, {**s, "id": 2, "y": 700.0}]
c = G.check(two, W_, H_, GAP, 100.0, roof=[(0, 0), (2000, 0), (2000, 1000), (0, 1000)])
check("two strings far apart inside the roof: no overlap, none outside", (c["overlaps"], c["outside"]), ([], {}))
c = G.check([{**s, "id": 1, "y": 300.0}, {**s, "id": 2, "y": 400.0}], W_, H_, GAP, 100.0)
check("two strings 100 px apart overlap (modules are 228 px tall)", c["overlaps"], [(1, 2)])
c = G.check([{**s, "id": 1, "x": 100.0}], W_, H_, GAP, 100.0, roof=[(0, 0), (2000, 0), (2000, 1000), (0, 1000)])
check("a string hanging out of the roof outline: the 4 modules left of x=0 are counted", c["outside"], {1: 4})

# saved shape
plan = S.clean({"scale": {"px_per_m": 50}}, INFO)
check("no saved strings -> the design strings (2 x 8), stacked", ([x["count"] for x in plan["strings"]], plan["strings"][0]["x"] == plan["strings"][1]["x"]), ([8, 8], True))
check("scale 0 or missing is dropped", S.clean({"scale": {"px_per_m": 0}}, INFO)["scale"], None)
check("rotation is kept inside 0-360, rows and count are clamped", (lambda q: (q["rot"], q["rows"], q["count"]))(S.clean({"strings": [{"id": 1, "count": 999, "rows": -3, "rot": -30}]}, INFO)["strings"][0]), (330.0, 1, 200))
check("a roof outline needs 3 points", S.clean({"roof": [[0, 0], [1, 1]]}, INFO)["roof"], [])
good = S.clean({"scale": {"px_per_m": 100}, "strings": [{"id": 1, "count": 8, "x": 1000, "y": 300}, {"id": 2, "count": 8, "x": 1000, "y": 700}]}, INFO)
sm = S.summary(good, INFO)
check("summary: 16 of 16 modules, 9.6 kWp, fits", (sm["placed"], sm["kwp"], sm["ok"]), (16, 9.6, True))
check("without a scale nothing is checked and the plan is not 'ok'", S.summary(S.clean({}, INFO), INFO)["ok"], False)

# the sheet's system text (like the CAD roof sheets: strings -> inverter channels, totals, powers)
INFO_AC = {**INFO, "system": {"mode": "ac", "unit": "Fronius Primo 10.0-1", "qty": 1, "channels": 2, "ac_kw": 10.0, "voltage": "120/240 Vac"}}
lines = S.system_lines(S.clean({}, INFO_AC), INFO_AC)
check("system text: strings go to the inverter channels", lines[1:3], ["1x String de 8 módulos al canal 1 del inversor 1.", "1x String de 8 módulos al canal 2 del inversor 1."])
check("system text: totals and powers", (lines[3], lines[-3:]), ("En total son 16 módulos fotovoltaicos Sunergy SUN600 de 600 W.", ["Potencia DC: 9.6 kW.", "Potencia AC: 10 kW.", "Voltaje 120/240 Vac."]))

# title block: numbering of the set and location fields
from utils import pdf_sheet as PS  # noqa: E402

check("sheet numbers: techo 1/3, unifilar 2/3, taller 3/3", [PS.sheet_no(k) for k in ("techo", "unifilar", "taller")], ["Hoja 1 de 3", "Hoja 2 de 3", "Hoja 3 de 3"])
blob = {"site": {"city": "Carrillo", "province": "Guanacaste"}, "client": {"location": "X, Y"}}
check("location: canton falls back to the city, district empty", PS.location_fields({}, blob), {"province": "Guanacaste", "canton": "Carrillo", "district": ""})
check("location: the project's own sheet data wins over the quote", PS.location_fields({"tech_spec": {"sheet_location": {"district": "Palmira", "canton": "Carrillo"}}}, blob),
      {"province": "Guanacaste", "canton": "Carrillo", "district": "Palmira"})
check("location: a quote with canton and district uses them", PS.location_fields({}, {"site": {"province": "Heredia", "canton": "San Isidro", "district": "San Isidro"}}),
      {"province": "Heredia", "canton": "San Isidro", "district": "San Isidro"})
check("location: only the client's «Ciudad, Provincia» text", PS.location_fields({}, {"client": {"location": "Liberia, Guanacaste"}}), {"province": "Guanacaste", "canton": "Liberia", "district": ""})

# PDF
from PIL import Image  # noqa: E402

from techo import pdf as P  # noqa: E402

img = Image.new("RGB", (1600, 900), (110, 100, 95)); buf = io.BytesIO(); img.save(buf, "JPEG")
plan = S.clean({"photo": {"path": "x", "w": 1600, "h": 900}, "scale": {"px_per_m": 60, "dist_m": 10}, "strings": [{"id": 1, "count": 8, "rows": 2, "x": 700, "y": 300, "rot": 12}, {"id": 2, "count": 8, "x": 800, "y": 600, "rot": 0, "orient": "landscape"}],
                "roof": [[100, 100], [1500, 100], [1500, 800], [100, 800]]}, INFO)
out = io.BytesIO()
P.build({"project": {"name": "Prueba", "client": "X", "location": "Y", "date": "2026-11-23", "revision": "A (borrador)", "draft": True, "responsible": "Ing."}, "plan": plan, "info": INFO_AC, "photo_bytes": buf.getvalue()}, out)
check("PDF renders", out.getvalue()[:4], b"%PDF")
check("the logo of the sheets is the image file", Path("proposals/assets/Logo_color_v3.png").exists(), True)

print("\nALL TECHO CHECKS PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
