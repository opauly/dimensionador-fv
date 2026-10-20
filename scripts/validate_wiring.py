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
check("size_branch PV: conduit trade size", b["conduit"]["trade"], "3/4")

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

print("\n" + ("ALL WIRING CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
