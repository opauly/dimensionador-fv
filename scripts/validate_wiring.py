"""Check calculations/wiring.py against the numbers Oscar's "Dimensionador CCC + FV"
workbook itself produces for its sample inputs (cached values in v0.2).

    python3 scripts/validate_wiring.py

Each assertion cites the workbook cell it reproduces. Where the workbook has a manual
input (the typed-in "Calibre incrementado") the test feeds that same value in.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calculations import wiring as W  # noqa: E402

fails: list[str] = []


def check(name: str, got, want, tol: float = 1e-3) -> None:
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, workbook {want!r}")
    if not ok:
        fails.append(name)


# ── Off-Grid sample: 5 strings x Isc 7.2 A, 24 V, 14.6 m ('CCCs FV (Off-Grid)') ──
i_pv = 7.2 * 5                                    # C26 = 36
design = i_pv * W.CONTINUOUS_FACTOR * W.PV_CONDITIONS_FACTOR
check("OG C44 PV design current (A)", round(design, 2), 56.25)
check("OG C47 initial gauge", W.initial_gauge(design), "6")
check("OG C49 OCPD (A)", W.ocpd_size(design), 60)
check("OG H47 R(6) ohm/km", W.T.T8_R_DC_CU_OHM_KM["6"], 1.671)
check("OG C53 Vd initial (V)", round(W.vdrop_dc("6", i_pv, 14.6), 4), 1.7566, 1e-3)
check("OG C61 EGC initial (UGC 6)", W.T.T250_66_CU["6"], "8")
check("OG C64 EGC after UGC upsized to 3/0", W.egc_gauge("6", "3/0"), "1/0")
check("OG C86 EGC after UGC 8 (batt->inv, EGC from 8)", W.egc_gauge("10", "8"), "4")

# ── Off-Grid AC out: 5000 W / 0.96 / 240 V, 30 m ───────────────────────────────
i_ac = (5000 / 0.96) / 240                         # C96 = 21.70
design_ac = i_ac * W.CONTINUOUS_FACTOR             # C91 = 27.13
check("OG C91 AC design current (A)", round(design_ac, 2), 27.13)
check("OG C92 AC gauge", W.initial_gauge(design_ac), "10")
check("OG C94 AC OCPD (A)", W.ocpd_size(design_ac), 30)
check("OG C97 AC Vd initial (V)", round(W.vdrop_ac("10", i_ac, 30.0), 3), 4.191, 2e-3)

# ── EGC by T250.122 (rating of the protective device), not T250.66 ─────────────
check("T250.122: 25 A breaker -> 10 AWG", W.egc_gauge_ocpd(25, "10", "10"), "10")
check("T250.122: 60 A -> 10 AWG", W.egc_gauge_ocpd(60, "6", "6"), "10")
check("T250.122: 70 A -> 8 AWG", W.egc_gauge_ocpd(70, "4", "4"), "8")
check("T250.122: 90 A -> 8 AWG", W.egc_gauge_ocpd(90, "3", "3"), "8")
check("T250.122: 200 A -> 6 AWG", W.egc_gauge_ocpd(200, "3/0", "3/0"), "6")
check("T250.122(B): phases 10 -> 6 for voltage drop, 60 A (10 AWG ground) grows in proportion", W.egc_gauge_ocpd(60, "10", "6"), "6")
eb = W.size_branch("ac", kind="ac", qty=1, current_a=41.67, factor=1.25, v_ref=240.0, length_m=10.0, hot=2)
check("size_branch AC 60 A: ground 10 AWG (T250.122), not 8 (T250.66)", eb["egc"], "10")
check("size_branch rows carry ampacity and rule", all(r.get("rule") and "ampacity" in r for r in eb["conductors"]), True)
tiny = W.size_branch("tiny", kind="ac", qty=1, current_a=30.0, factor=1.25, v_ref=240.0, length_m=5.0, hot=2, ocpd_override=100)
check("EGC never larger than the phase conductors (250.122(A))", T_i := (W.T.GAUGE_ORDER.index(tiny["egc"]) <= W.T.GAUGE_ORDER.index(tiny["ugc"])), True)

# ── Conduit: RHW-2 UGC 8 AWG + EGC 4 AWG = 98.64 mm2 -> PVC A metric 16 (1/2 in) ──
total = W.conductor_area("8") + W.conductor_area("4")
check("OG E116 conductor total (mm2)", round(total, 2), 98.64)
cond = W.pick_conduit(total, "PVC A")
check("OG C118/E118 conduit", (cond["metric"], cond["trade"]), ("16", "1/2"))

# ── On-Grid sample: 2 strings x Isc 11.65 A, 5 m ('CCCs FV (On-Grid)') ─────────
i_og = 11.65 * 2
d = i_og * W.CONTINUOUS_FACTOR * W.PV_CONDITIONS_FACTOR
check("ON C36 design current (A)", round(d, 5), 36.40625)
check("ON C37 initial gauge", W.initial_gauge(d), "8")
check("ON C39 OCPD (A)", W.ocpd_size(d), 40)
check("ON C42 Vd initial (V)", round(W.vdrop_dc("8", i_og, 5.0), 4), 0.6009, 1e-3)
check("ON C59 AC gauge (27.27 A)", W.initial_gauge(27.268760907504365), "10")

# ── Edge behaviour ─────────────────────────────────────────────────────────────
check("above largest table ampacity -> None", W.initial_gauge(9999.0), None)
check("above 6000 A OCPD -> None", W.ocpd_size(7000), None)
b = W.size_branch("t", kind="dc", qty=1, current_a=31.72, factor=1.5625, v_ref=161.8, length_m=15.0)
check("size_branch PV (2 strings of 600 W panels): UGC", b["ugc"], "8")
check("size_branch PV: conduit trade size (EGC by T250.122: 8 AWG + 10 AWG ground)", b["conduit"]["trade"], "1/2")

# ── BOM assembly (calculations/bom.py) on a hand-checkable branch ──────────────
from calculations import bom as B  # noqa: E402

br = [{"label": "x", "kind": "dc", "qty": 2, "length_m": 10.0, "ocpd_a": 50,
       "conductors": [{"role": "UGC", "gauge": "8", "count": 2}, {"role": "EGC", "gauge": "8", "count": 1}],
       "conduit": {"trade": "3/4"}}]
cr = {r["item"]: r for r in B.conductor_rows(br, "RHW-2")}
check("BOM live 8 AWG metres (2 conductors x 2 runs x 10 m)", cr["Conductor Cu RHW-2 8 AWG — activos / neutro"]["meters"], 40.0)
check("BOM ground 8 AWG metres (1 x 2 x 10 m)", cr["Conductor Cu RHW-2 8 AWG — tierra (EGC)"]["meters"], 20.0)
check("BOM live metres with 10 % waste", cr["Conductor Cu RHW-2 8 AWG — activos / neutro"]["with_waste"], 44)
co = B.conduit_rows(br, "PVC A")[0]
check("BOM conduit run (2 runs x 10 m)", co["meters"], 20.0)
check("BOM conduit 3 m tubes with waste: ceil(22/3)", co["tubes"], 8)
pr = B.protection_rows(br)[0]
check("BOM protection qty + poles", (pr["qty"], "2 polos" in pr["item"]), (2, True))

# ── Conductor counts per branch (2 wires DC; 3 per 120 V inverter on AC) ───────────
nb = W.size_branch("dc", kind="dc", qty=2, current_a=31.72, factor=1.5625, v_ref=161.8, length_m=15.0, egc_included=False)
check("DC branch: 2 conductors, no EGC", [(r["role"], r["count"]) for r in nb["conductors"]], [("UGC", 2)])
check("DC branch: egc field empty when not carried", nb["egc"], None)
ab = W.size_branch("ac", kind="ac", qty=2, current_a=36.75, factor=1.25, v_ref=120.0, length_m=10.0, hot=1, neutral=1)
check("AC 120 V inverter: phase + neutral + ground", [(r["role"], r["count"]) for r in ab["conductors"]], [("UGC", 1), ("Neutro", 1), ("EGC", 1)])
check("AC Vd judged on 120 V (36.75 A, 8 AWG, 10 m) %", ab["vd_pct"], 1.32, 0.01)
meters = B.conductor_rows([nb, ab], "RHW-2")
tot = {r["item"]: r["meters"] for r in meters}
check("BOM: AC 8 AWG live+neutral = 2 inverters x 2 conductors x 10 m + DC pair 2x2x15", tot["Conductor Cu RHW-2 8 AWG — activos / neutro"], 40.0 + 60.0)
check("BOM: AC ground = 2 inverters x 1 x 10 m (DC has none); 50 A breaker -> 10 AWG by T250.122", tot["Conductor Cu RHW-2 10 AWG — tierra (EGC)"], 20.0)

# ── Breaker ceilings and the AC design bases ───────────────────────────────────
check("'95 A or less' -> largest standard size <= 95 A", W.ocpd_size_max(95), 90)
check("115 A rated AC out -> 110 A ceiling", W.ocpd_size_max(115), 110)
ao = W.size_branch("ac out", kind="ac", qty=2, current_a=13250 / 240, factor=1.25, v_ref=120.0, length_m=10.0, hot=1, neutral=1)
check("AC out from connected loads: 55.2 A x 1.25 -> breaker", ao["ocpd_a"], 70)
check("AC out from connected loads: conductor (needs >= 69 A)", ao["ugc"], "4")
ai = W.size_branch("ac in", kind="ac", qty=2, current_a=95.0, factor=1.0, v_ref=120.0, length_m=10.0, hot=1, neutral=1, ocpd_override=W.ocpd_size_max(95))
check("AC in from 95 A pass-through: breaker 90 A, conductor 3 AWG (>= 95 A)", (ai["ocpd_a"], ai["ugc"]), (90, "3"))

# ── Lynx fuses: restricted sizes, and the cable follows the fuse (NEC 240.4(B)) ─────
F = (100, 125, 200, 250)
f1 = W.size_branch("cc->bat", kind="dc", qty=1, current_a=94.51, factor=1.25, v_ref=51.2, length_m=2.0, hot=2, egc_included=False, protection="fuse", ocpd_choices=F)
check("fuse for 118 A design: smallest of 100/125/200/250 that fits", f1["ocpd_a"], 125)
check("125 A fuse on 1 AWG (130 A) is fine", f1["ugc"], "1")
f2 = W.size_branch("bat->inv", kind="dc", qty=1, current_a=101.7, factor=1.25, v_ref=51.2, length_m=2.0, hot=2, egc_included=False, protection="fuse", ocpd_choices=F)
check("fuse for 127 A design jumps to 200 A", f2["ocpd_a"], 200)
check("200 A fuse needs a cable that can carry it: 3/0 AWG (200 A @75 C)", f2["ugc"], "3/0")
f3 = W.size_branch("big", kind="dc", qty=1, current_a=250.0, factor=1.25, v_ref=51.2, length_m=2.0, hot=2, egc_included=False, protection="fuse", ocpd_choices=F)
check("design above the largest fuse -> flagged, no rating", (f3["ocpd_a"], f3["ok"]), (None, False))
rows = B.protection_rows([f1, f2, {**ao, "protection": "breaker"}])
check("BOM fuse label has no poles and names the bus", any("Fusible CC 200 A (barra Lynx Power In)" == r["item"] for r in rows), True)

# ── Datasheet limits and the engineer's manual values ──────────────────────────
from calculations import datasheet_limits as DL  # noqa: E402

mp = DL.multi_limits("MultiPlus-II 48/5000/70-95")
check("MultiPlus-II 48/5000/70-95 datasheet: 4000 W continuous, 9000 W peak, 95 A AC in", (mp["cont_w_25c"], mp["peak_w"], mp["ac_in_a"]), (4000, 9000, 95))
check("Multi AC currents at 120 V: 41.7 A continuous (5000 VA), 75 A peak (9000 W)", (mp["ac_cont_a"], mp["ac_peak_a"]), (41.7, 75.0))
check("Fronius Primo 10.0-1 @240 V: 41.6 A out, 60 A OCPD", tuple(DL.fronius_limits("Primo 10.0-1").values()), (41.6, 60))
check("Fronius Primo 15.0-1 @240 V: 62.5 A out, 80 A OCPD", tuple(DL.fronius_limits("Fronius Primo 15.0-1").values()), (62.5, 80))

base_ac = W.size_branch("fr", kind="ac", qty=1, current_a=41.6, factor=1.25, v_ref=240.0, length_m=10.0, hot=2)
base_ac["max_ocpd_a"] = 60
b1 = W.apply_manual(dict(base_ac), {"ocpd_a": 70})
check("manual 70 A above the Fronius max OCPD (60 A) -> dangerous", (b1["manual"]["ocpd_ok"], b1["manual"]["ok"]), (False, False))
b2 = W.apply_manual(dict(base_ac), {"ocpd_a": 60, "ugc": "4"})
check("manual 60 A on a LARGER gauge than calculated -> safe", (b2["manual"]["ocpd_ok"], b2["manual"]["ugc_ok"]), (True, True))
check("manual ground follows the manual breaker (T250.122, 60 A -> 10 AWG)", b2["egc"], "10")
b3 = W.apply_manual(dict(base_ac), {"ugc": "10"})
check("manual 10 AWG (35 A) under a 52 A design current -> dangerous", b3["manual"]["ugc_ok"], False)
b4 = W.apply_manual(dict(base_ac), {"ocpd_a": 50})
check("manual 50 A below the 52 A design current -> trips on normal load", b4["manual"]["ocpd_ok"], False)
dcb = W.size_branch("bat->inv", kind="dc", qty=1, current_a=81.4, factor=1.25, v_ref=51.2, length_m=2.0, hot=2, egc_included=False, protection="fuse", ocpd_choices=(100, 125, 200, 250))
check("calculated: 81.4 A x 1.25 = 101.7 A -> 125 A fuse on 2 AWG (115 A, 240.4(B))", (dcb["ocpd_a"], dcb["ugc"]), (125, "2"))
b5 = W.apply_manual(dict(dcb), {"ocpd_a": 250, "ugc": "2"})
check("manual 250 A fuse on 2 AWG: more than NEC 240.4(B) lets the cable carry -> dangerous", (b5["manual"]["ocpd_ok"], b5["manual"]["ugc_ok"]), (False, False))
lim = W.size_branch("ac in", kind="ac", qty=2, current_a=95.0, factor=1.0, v_ref=120.0, length_m=10.0, hot=1, neutral=1, ocpd_override=90)
lim["limited"], lim["max_ocpd_a"] = True, 90
b6 = W.apply_manual(dict(lim), {"ocpd_a": 70})
check("manufacturer-limited AC in: a lower breaker (70 A) just caps the input -> safe", b6["manual"]["ocpd_ok"], True)
b7 = W.apply_manual(dict(lim), {"ugc": "4"})
check("AC in: 4 AWG (85 A) with the 90 A breaker is allowed by 240.4(B) -> safe", b7["manual"]["ugc_ok"], True)
check("no manual values -> branch untouched", W.apply_manual(dict(base_ac), {})["ocpd_a"], base_ac["ocpd_a"])

print("\n" + ("ALL WIRING CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
