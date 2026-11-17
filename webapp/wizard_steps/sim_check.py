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
        site = blob.get("site") or {}
        if hybrid:
            out_goal, night_goal = sp["goals"].get("outage_cover_pct"), sp["goals"].get("night_cover_pct")
            zone = fs.nearest_zone(ds, site.get("lat"), site.get("lon")) if (out_goal or night_goal) else None
            res = fs.design_hybrid(ds, daily, kwp, reserve_pct=reserve, compare_batteries=compare, zone=zone)
        else:
            res = fs.design(ds, daily, kwp, reserve_pct=reserve, compare_batteries=compare)
        if res is None:
            return None
        c = res["compare"][0]
        out = {"kind": sp["system_type"], "kwp": kwp, "battery": batt, "daily_kwh": daily, "reserve_pct": res["reserve_pct"],
               "scenarios": res["scenarios"], "days": res["days"], "window": res["window"]}
        if hybrid:
            night_t = float(night_goal) if night_goal else fs.NIGHT_TARGET_PCT
            out_t = float(out_goal) if out_goal else fs.OUTAGE_TARGET_PCT
            night_ok = c["nights_ok_pct"] >= night_t
            out_ok = c["outage_cover_pct"] is None or c["outage_cover_pct"] >= out_t
            fails = [t for t, ok in (("la noche", night_ok), ("los cortes de red", out_ok)) if not ok]
            out.update(ok=not fails, fails=fails, nights_ok_pct=c["nights_ok_pct"], night_target=night_t,
                       outage_cover_pct=c["outage_cover_pct"], outage_target=out_t,
                       zone_label=res.get("zone_label") if zone else None, years=res.get("years") if zone else None,
                       import_pct=c["import_pct"], import_pct_adj=c["import_pct_adj"],
                       battery_min_nights=res["battery_min_nights"], battery_min_backup=res["battery_min_backup"],
                       backup_median_h=c["backup_median_h"], backup_p10_h=c["backup_p10_h"], outages_enough=res["outages"]["enough"])
        else:
            days_ok, streak_ok = c["fail_pct_physical"] <= fs.TARGET_FAIL_PCT, c["streak_p90"] <= fs.TARGET_STREAK_DAYS
            fails = [t for t, ok in (("los días con apagón", days_ok), ("el apagón más largo", streak_ok)) if not ok]
            zev = None
            goal_days = sp["goals"].get("max_fail_days_year")
            if goal_days:                               # the zone's 5 real years replace the fleet window as the verdict
                zone = fs.nearest_zone(ds, (blob.get("site") or {}).get("lat"), (blob.get("site") or {}).get("lon"))
                zev = fs.evaluate_zone(ds, zone, daily, kwp, batt) if zone else None
            if zev:
                days_ok = zev["days_year"] <= float(goal_days) + 1e-9
                fails = [] if days_ok else ["los días al año sin cubrir"]
                c = {**c, "soc_typ_pct": zev["soc_typ_pct"]}
                out.update(days_year=zev["days_year"], days_year_worst=zev["days_year_worst"], days_target=float(goal_days),
                           zone_label=zev["zone_label"], years=zev["years"])
            out.update(ok=not fails, fails=fails, fail_pct=c["fail_pct_physical"], fail_target=fs.TARGET_FAIL_PCT,
                       reserve_days_pct=c["fail_pct_reserve"], streak=c["streak_p90"], soc_typ_pct=c.get("soc_typ_pct"),
                       soc_typ_target=sp["goals"].get("typical_min_soc_pct"), streak_target=fs.TARGET_STREAK_DAYS,
                       battery_min=res["battery_min_physical"], battery_min_reserve=res["battery_min_reserve"], kwp_min=res.get("kwp_min"))
        return out
    except Exception:                                   # noqa: BLE001 — informational card, never break Equipos
        return None


def grid_zero_real(blob: dict, kwp: float, inverter_kw: float) -> dict | None:
    """Grid Zero: what the chosen array really avoids buying — the site's load replayed hour by hour against 5 years of the nearest zone's
    sun with zero export and the real DC/AC ratio (`fleet_simulation.grid_zero_reduction`). None when the history, the consumption or the
    coordinates are missing (the caller keeps the monthly-average projection)."""
    try:
        from calculations import fleet_simulation as fs

        ds = fs.get_dataset()
        site = blob.get("site") or {}
        avg = float((blob.get("consumption") or {}).get("avg_kwh") or 0)
        if not ds or not ds.get("k") or kwp <= 0 or avg <= 0:
            return None
        zone = fs.nearest_zone(ds, site.get("lat"), site.get("lon"))
        if not zone:
            return None
        ratio = max(1.0, kwp / inverter_kw) if inverter_kw > 0 else 1.2
        return fs.grid_zero_reduction(ds, zone, avg / 30.4, kwp, ratio)
    except Exception:                                   # noqa: BLE001 — informational, never break Equipos
        return None
