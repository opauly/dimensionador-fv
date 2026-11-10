"""Real-data verdict at Equipos: the equipment the engineer chose, replayed against the fleet's real sun, load patterns (and, for
hybrids, real grid outages). Thin glue over `calculations/fleet_simulation.py`; informational only — it never blocks Equipos.
Off-Grid / Hybrid only. Best-effort: any failure hides the card, and a missing cache shows "preparing" (never blocks the page)."""
from __future__ import annotations

from webapp.wizard_steps import s6_objetivos


def build(blob: dict, facts: dict) -> dict | None:
    """`facts`: system_kw (installed array, kWp) and battery_installed_kwh. None when there is nothing to test."""
    try:
        from calculations import fleet_simulation as fs

        sp = s6_objetivos.sweet_spot(blob)
        if sp is None or sp["system_type"] not in ("off_grid", "hybrid"):
            return None
        kwp, batt = float(facts.get("system_kw") or 0), float(facts.get("battery_installed_kwh") or 0)
        if kwp <= 0 or batt <= 0:
            return None
        ds = fs.get_dataset()
        hybrid = sp["system_type"] == "hybrid"
        if ds is None or (hybrid and "hybrid" not in ds):
            return {"pending": True, "kind": sp["system_type"]}
        if not ds.get("k"):
            return None
        inputs = sp["inputs"]
        daily = float(inputs["critical_daily_kwh"] if hybrid else inputs["daily_kwh"])
        reserve = float(sp["goals"].get("reserve_soc_pct") or (30.0 if hybrid else 35.0))
        compare = {"installed": batt}
        if hybrid:
            res = fs.design_hybrid(ds, daily, kwp, reserve_pct=reserve, compare_batteries=compare)
        else:
            res = fs.design(ds, daily, kwp, reserve_pct=reserve, compare_batteries=compare)
        if res is None:
            return None
        c = res["compare"][0]
        out = {"kind": sp["system_type"], "kwp": kwp, "battery": batt, "daily_kwh": daily, "reserve_pct": res["reserve_pct"],
               "scenarios": res["scenarios"], "days": res["days"], "window": res["window"]}
        if hybrid:
            night_ok = c["nights_ok_pct"] >= fs.NIGHT_TARGET_PCT
            out_ok = c["outage_cover_pct"] is None or c["outage_cover_pct"] >= fs.OUTAGE_TARGET_PCT
            fails = [t for t, ok in (("la noche", night_ok), ("los cortes de red", out_ok)) if not ok]
            out.update(ok=not fails, fails=fails, nights_ok_pct=c["nights_ok_pct"], night_target=fs.NIGHT_TARGET_PCT,
                       outage_cover_pct=c["outage_cover_pct"], outage_target=fs.OUTAGE_TARGET_PCT,
                       import_pct=c["import_pct"], import_pct_adj=c["import_pct_adj"],
                       battery_min_nights=res["battery_min_nights"], battery_min_backup=res["battery_min_backup"],
                       backup_median_h=c["backup_median_h"], backup_p10_h=c["backup_p10_h"], outages_enough=res["outages"]["enough"])
        else:
            days_ok, streak_ok = c["fail_pct_physical"] <= fs.TARGET_FAIL_PCT, c["streak_p90"] <= fs.TARGET_STREAK_DAYS
            fails = [t for t, ok in (("los días con apagón", days_ok), ("el apagón más largo", streak_ok)) if not ok]
            out.update(ok=not fails, fails=fails, fail_pct=c["fail_pct_physical"], fail_target=fs.TARGET_FAIL_PCT,
                       reserve_days_pct=c["fail_pct_reserve"], streak=c["streak_p90"], streak_target=fs.TARGET_STREAK_DAYS,
                       battery_min=res["battery_min_physical"], battery_min_reserve=res["battery_min_reserve"], kwp_min=res.get("kwp_min"))
        return out
    except Exception:                                   # noqa: BLE001 — informational card, never break Equipos
        return None
