"""Checks for the workshop plan (plano/layout.py, plano/design.py, plano/service.py, plano/generate_plano.py).

    python3 scripts/validate_plano.py

No database: sizes are injected. The rules under test are Oscar's (see plano/layout.py)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plano import design, generate_plano, service  # noqa: E402
from plano import layout as L  # noqa: E402

fails: list[str] = []


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


MP5 = (330, 676, 164); PRIMO = (511, 724, 226); GAB = (400, 500, 200); CHINT = (184, 136, 108); LYNX = (288, 168.8, 77.5); FIDUS = (638, 370, 137)
US5 = (442, 161, 420)


def hybrid(n_v=2, n_fid=4, fronius=True, extra=None):
    s = L.Spec(system="hybrid", victron=L.part("v", "MultiPlus-II 48/5000", MP5, n_v), gabinete=L.part("g", "Gabinete", GAB, 1),
               chint=L.part("c", "Caja Chint DC", CHINT, 1), lynx=L.part("l", "Lynx Power In", LYNX, 2), fidus=L.part("b", "Fidus", FIDUS, n_fid))
    if fronius:
        s.fronius = L.part("f", "Primo 10.0-1", PRIMO, 1)
    for k, v in (extra or {}).items():
        setattr(s, k, v)
    return s


R = lambda lay, kind: [r for r in lay.rects if r.kind == kind]  # noqa: E731

# ── Layout rules ──
lay = L.place(hybrid())
v, g, ch, fr = R(lay, "victron"), R(lay, "gabinete")[0], R(lay, "chint")[0], R(lay, "fronius")[0]
check("row 1 order left to right: Victron, Victron, gabinete, Chint, Fronius", [r.x for r in v] == sorted(r.x for r in v) and v[1].x < g.x < ch.x < fr.x, True)
check("Victron units sit side by side with the inverter gap", v[1].x - (v[0].x + v[0].w), L.GAP_INVERTERS)
check("gabinete is aligned by the TOP with the Victron units", round(g.y + g.h, 3), round(v[0].y + v[0].h, 3))
check("the AC-coupled Fronius is aligned by its BASE with the Victron units", round(fr.y, 3), round(v[0].y, 3))
check("the taller Fronius sets the top of the equipment", round(lay.height, 3), round(fr.y + fr.h, 3))
check("the duct is 4x4 in, as long as row 1, under it", (round(lay.duct.h, 1), round(lay.duct.w, 3), lay.duct.y + lay.duct.h < v[0].y), (101.6, round(lay.row1_w, 3), True))
check("duct length = equipment + gabinete (row 1 only, not the batteries)", round(lay.row1_w, 3), round(fr.x + fr.w, 3))
fid = R(lay, "fidus")
check("Fidus hang under the duct, two per column, lying flat (638 wide x 370 high)", (len(fid), {(r.w, r.h) for r in fid}, fid[0].x == fid[1].x, fid[1].y > fid[0].y), (4, {(638, 370)}, True, True))
check("Fidus columns side by side", fid[2].x - (fid[0].x + fid[0].w), L.GAP_ROW2)
check("lowest battery is FLOOR_GAP above the floor", min(r.y for r in fid), L.FLOOR_GAP)
lyn = R(lay, "lynx")
check("Lynx lie horizontally side by side under the duct, left of the batteries", (len(lyn), lyn[0].x < lyn[1].x < fid[0].x, lyn[0].y + lyn[0].h < lay.duct.y), (2, True, True))
check("nothing overlaps", all(not (a is not b and a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h) for a in lay.rects for b in lay.rects), True)
need = lay.needed()
check("minimum wall = equipment + margin on both sides and on top", (round(need[0]), round(need[1])), (round(lay.width + 2 * L.MARGIN), round(lay.height + L.MARGIN)))

# ── DC-coupled: controllers take the Fronius's place ──
dc = hybrid(fronius=False, extra={"controllers": L.part("cc", "MPPT 250/100", (295, 216, 103), 2)})
ld = L.place(dc)
cc = R(ld, "controller")
check("DC-coupled: two controllers after the Chint box, aligned by the top, no Fronius", (len(cc), cc[0].x > R(ld, "chint")[0].x, round(cc[0].y + cc[0].h, 3) == round(R(ld, "victron")[0].y + R(ld, "victron")[0].h, 3), bool(R(ld, "fronius"))), (2, True, True, False))

# ── Grid Zero: Fronius only ──
gz = L.Spec(system="grid_zero", fronius=L.part("f", "Primo 10.0-1", PRIMO, 2), gabinete=L.part("g", "Gabinete", GAB, 1), chint=L.part("c", "Chint", CHINT, 1),
            centers=[L.center_part(8, 1)])
lg = L.place(gz)
check("Grid Zero: 2 Fronius in the row, the load center under the duct, no Victron", (len(R(lg, "fronius")), len(R(lg, "center")), bool(R(lg, "victron"))), (2, 1, False))
check("Grid Zero: the Fronius are aligned by the top with the gabinete", round(R(lg, "fronius")[0].y + R(lg, "fronius")[0].h, 3), round(max(r.y + r.h for r in lg.rects if r.kind != "center"), 3))

# ── Rack batteries on stands ──
rk = hybrid(n_fid=0, extra={"fidus": None, "rack": L.part("r", "US5000", US5, 7)})
lr = L.place(rk)
st = R(lr, "stand")
check("US5000 x7 -> 2 stands on the floor (6 + 1), not hanging", (len(st), [s.y for s in st], bool(R(lr, "fidus"))), (2, [0, 0], False))

# ── Many Victron: one row, two rows when the wall is narrow ──
many = L.Spec(system="hybrid", victron=L.part("v", "MP", MP5, 4), gabinete=L.part("g", "G", GAB, 1))
w_single = L.place(many, "single").needed()[0]
check("4 Victron: one row first", L.choose(many, None, None)[0].mode, "single")
check("4 Victron on a wall too narrow for one row -> two rows", L.choose(many, w_single - 300, 3000)[0].mode, "double")
check("4 Victron on a wide wall stay in one row", L.choose(many, w_single + 100, 3000)[0].mode, "single")
check("two rows are narrower and taller", (L.place(many, "double").width < L.place(many, "single").width, L.place(many, "double").height > L.place(many, "single").height), (True, True))

# ── Check against the wall ──
chk = L.check(lay, 3000, 2400)
check("fits a big wall, with the slack", (chk["fits"], chk["slack_w"] > 0, chk["slack_h"] > 0), (True, True, True))
chk2 = L.check(lay, round(need[0]) - 10, 3000)
check("does not fit 10 mm short in width", (chk2["fits"], chk2["slack_w"]), (False, -10))
check("no wall -> no verdict, only the minimum", (L.check(lay, None, None)["fits"], L.check(lay, None, None)["need_w"] > 0), (None, True))
check("exactly the needed size fits", L.check(lay, need[0], need[1])["fits"], True)

# ── Missing sizes are flagged, never silently real ──
miss = L.part("x", "Equipo sin ficha", None, 1)
check("a part without sizes gets a placeholder flagged as missing", (miss.missing, miss.real), (True, False))
check("a part with sizes is real", L.part("x", "E", (100, 200, 50), 1).real, True)

# ── Design -> spec ──
FIX = {"gabinete_50x40x20": (400, 500, 200), "chint_dc_5": (184, 136, 108), "lynx_power_in": (288, 168.8, 77.5)}
DIMS = {"mp": MP5, "fr": PRIMO, "fid": FIDUS, "us5": US5}
dims = lambda table, id_: DIMS.get(id_)  # noqa: E731
proj = {"system_type": "hybrid"}
d = {"eq": {"inverter": {"id": "mp", "brand": "Victron Energy", "model": "MultiPlus-II 48/5000/70-95"}, "inverter_qty": 2,
            "battery": {"id": "fid", "brand": "Pylontech", "model": "Fidus"}, "battery_bank": {"battery_count": 4}},
     "wiring": {"coupling": {"ac": True, "qty": 1, "pv_inverter": {"id": "fr", "brand": "Fronius", "model": "Primo 10.0-1"}}}}
lines = [{"name": "Centro de carga Chint DC 5 espacios", "qty": 1}, {"name": "Lynx Power In", "qty": 2},
         {"name": "Tablero NEMA 3R 4 espacios, marca CH/ SD, barras de 125A, Monofasico", "qty": 1}]
sp = design.build_spec(proj, d, lines, dims=dims, fixed=FIX)
check("spec from the design: 2 Victron, AC-coupled Fronius, 4 Fidus on the wall, Chint, Lynx, one 4-space center, gabinete",
      (sp.victron.qty, sp.fronius.qty, sp.fidus.qty, sp.rack, sp.chint.qty, sp.lynx.qty, [(c.qty, c.w) for c in sp.centers], sp.gabinete.w),
      (2, 1, 4, None, 1, 2, [(1, 200.0)], 400.0))
check("short names: the MultiPlus drops the AC-in / AC-out part", (sp.victron.label, sp.fronius.label), ("MultiPlus-II 48/5000", "Primo 10.0-1"))
check("gabinete and Chint are flagged as nominal / to confirm, the datasheet ones are real", (sp.gabinete.real, sp.chint.real, sp.victron.real, sp.lynx.real), (False, False, True, True))
d2 = {**d, "eq": {**d["eq"], "battery": {"id": "us5", "brand": "Pylontech", "model": "US5000"}, "battery_bank": {"battery_count": 4}}}
check("US5000 goes to the stand, not the wall", (design.build_spec(proj, d2, lines, dims=dims, fixed=FIX).fidus, design.build_spec(proj, d2, lines, dims=dims, fixed=FIX).rack.qty), (None, 4))
gzp = {"system_type": "grid_zero"}
dg = {"eq": {"inverter": {"id": "fr", "brand": "Fronius", "model": "Primo 10.0-1"}, "inverter_qty": 2}, "wiring": {}}
sg = design.build_spec(gzp, dg, [], dims=dims, fixed=FIX)
check("Grid Zero spec: 2 Fronius, no Victron, no batteries", (sg.fronius.qty, sg.victron, sg.fidus, sg.rack), (2, None, None, None))
nodims = design.build_spec(proj, d, lines, dims=lambda t, i: None, fixed={})
check("no sizes in the catalog -> missing parts are flagged", (nodims.victron.missing, nodims.gabinete.missing), (True, True))

# ── Service + PDF ──
check("answers: metres, junk -> None, default margin", (service.clean_answers({"wall_w_m": "3,2", "wall_h_m": "abc"}), service.clean_answers({})["margin_mm"]),
      ({"wall_w_m": 3.2, "wall_h_m": None, "margin_mm": L.MARGIN}, L.MARGIN))
comp = service.compute(proj, {"blob": {}}, [], service.clean_answers({"wall_w_m": 3, "wall_h_m": 2.4}), spec=sp)
check("service: fits a 3 x 2.4 m wall", comp["check"]["fits"], True)
comp_no = service.compute(proj, {"blob": {}}, [], service.clean_answers({"wall_w_m": 1.5, "wall_h_m": 2.4}), spec=sp)
check("service: a 1.5 m wall does not fit a 2.3 m row", comp_no["check"]["fits"], False)
for name, cp in (("fits", comp), ("does not fit", comp_no), ("no wall", service.compute(proj, {"blob": {}}, [], service.clean_answers({}), spec=sp))):
    buf = io.BytesIO()
    generate_plano.build(service.pdf_data(proj, {"blob": {}}, cp), buf)
    check(f"PDF renders ({name})", buf.getvalue()[:4], b"%PDF")

print("\n" + ("ALL PLANO CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
