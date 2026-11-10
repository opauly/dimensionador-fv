"""Checks for the flexible array layouts (calculations/mppt.py: find_array_per_controller, find_array_for_pv_inverter).
Synthetic panel / controller / inverter dicts, no database: a 620 W module (Voc 48.5 V, Imp 15.4 A) on a 250 V / 35 A controller
(5 in series, 2 strings per controller -> 10 panels per controller) and a 2-MPPT string inverter."""
import sys

sys.path.insert(0, ".")
from calculations.mppt import find_array_for_pv_inverter, find_array_per_controller  # noqa: E402

PANEL = {"wp": 620, "voc": 48.5, "vmp": 41.0, "imp": 15.4, "isc": 16.4, "width_m": 1.13, "height_m": 2.38}
CC = {"vin_max": 250.0, "imax_in": 35.0}
PVINV = {"brand": "Fronius", "model": "Primo 10.0-1", "mppt_channels": 2, "vmax": 1000.0, "vmax_mppt": 800.0, "vmin_mppt": 200.0, "imax_mppt": 27.0}
fails = 0


def check(label, cond, detail=""):
    global fails
    print(("  ok   " if cond else "  FAIL ") + label + (f"  [{detail}]" if detail and not cond else ""))
    fails += 0 if cond else 1


def dc(kw):
    return find_array_per_controller(PANEL, CC, kw)


a = dc(3.72)                       # exactly 6 panels
check("6 panels -> one controller, 2 strings of 3", (a["total_panels"], a["charge_controller_qty"], a["panels_per_string"], a["strings"]) == (6, 1, 3, 2), a["layout_text"])
a = dc(4.96)                       # 8 panels
check("8 panels -> 2 strings of 4", (a["total_panels"], a["panels_per_string"], a["strings"]) == (8, 4, 2), a["layout_text"])
a = dc(6.2)                        # 10 panels = the 5 x 2 maximum of one controller
check("10 panels -> 5 x 2 on a single controller", (a["total_panels"], a["charge_controller_qty"], a["panels_per_string"], a["strings"]) == (10, 1, 5, 2))
a = dc(3.1)                        # 5 panels: odd -> 6
check("an odd count rounds up to the next even number", a["total_panels"] == 6, a["total_panels"])
a = dc(6.82)                       # 11 panels -> 12, past the 10-panel limit -> 2 controllers of 6
check("past 10 panels it jumps to a second controller", (a["total_panels"], a["charge_controller_qty"]) == (12, 2), a["layout_text"])
a = dc(16.12)                      # 26 panels shared 10 + 8 + 8
check("26 panels -> 3 controllers, 10 + 8 + 8, exact count", (a["total_panels"], a["charge_controller_qty"], sorted(g["panels"] for g in a["groups"])) == (26, 3, [8, 8, 10]), a["layout_text"])
check("every controller stays within its limits (5 in series, 2 strings)", all(g["series"] <= 5 and g["strings"] <= 2 for g in a["groups"]))
check("total strings = sum over controllers and the longest string is what voltage uses",
      a["strings"] == sum(g["strings"] for g in a["groups"]) and a["panels_per_string"] == max(g["series"] for g in a["groups"]) and a["voc_total"] == round(5 * 48.5, 1))
a = dc(100)
check("a target beyond 4 controllers returns the largest array they can take (40 panels)", (a["total_panels"], a["charge_controller_qty"]) == (40, 4))

# A controller with several independent MPPT trackers (Victron RS 450/200: 4 inputs of 20 A, 450 V): one string per tracker, strings need not be equal.
RS = {"model": "SmartSolar MPPT RS 450/200", "vin_max": 450.0, "imax_in": 20.0}
a = find_array_per_controller(PANEL, RS, 18.6)               # 30 panels
check("RS 450/200: 30 panels fit ONE controller as 8 + 8 + 7 + 7", (a["total_panels"], a["charge_controller_qty"], a["strings"], a["panels_per_string"]) == (30, 1, 4, 8), a["layout_text"])
check("RS 450/200: the group keeps each string's length", a["groups"][0]["lengths"] == [8, 8, 7, 7])
check("RS 450/200: no string longer than the voltage allows (9 x 48.5 V <= 450 V)", all(x <= 9 for g in a["groups"] for x in g["lengths"]))
a = find_array_per_controller(PANEL, RS, 7.44)               # 12 panels
check("RS 450/200: 12 panels -> two strings of 6, still one controller", (a["total_panels"], a["charge_controller_qty"], a["groups"][0]["lengths"]) == (12, 1, [6, 6]))
a = find_array_per_controller(PANEL, RS, 24.8)               # 40 panels: past 4 x 9 = 36 -> second controller
check("RS 450/200: past 36 panels it jumps to a second controller", (a["total_panels"], a["charge_controller_qty"]) == (40, 2))

ac = find_array_for_pv_inverter(PANEL, PVINV, 6.2)
check("AC-coupled: no charge controller, panels go to the MPPT inputs", ac and ac["charge_controller_qty"] == 0 and "pv_inverter" in ac["ac_limits"])
check("AC-coupled: one string per MPPT, equal strings, exact count", (ac["strings"], ac["total_panels"]) == (2, 10), ac["layout_text"])
ac = find_array_for_pv_inverter(PANEL, PVINV, 4.96)
check("AC-coupled: 8 panels -> one string of 8 (2 x 4 would sit under the MPPT's 200 V minimum: 4 x 41 V = 164 V)",
      (ac["strings"], ac["panels_per_string"]) == (1, 8), ac["layout_text"])
check("AC-coupled: a string inverter with no voltage data gives no layout", find_array_for_pv_inverter(PANEL, {"mppt_channels": 2}, 6.0) is None)

print("\nALL ARRAY LAYOUT CHECKS PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
