"""Pre-fill Labor / Electrical materials / Mounting structure from what past projects really cost.

Each project's size is measured in "effort points": panels, inverters and installed batteries, each worth a number of
points per line (labor weighs inverters and batteries heavily, the mounting structure only counts panels). The learned
rate is the median of  (real paid expense / project points)  over the projects that have that expense paid, and a new
quote pre-fills  rate x this design's points.

With no paid history for a line, nothing is learned and `service_rates.service_unit_cost` keeps using the per-Wp
rate (or flat cost) on the service default. Weights can be edited in `app_settings.cost_effort_points`
(JSON: {"Mano de obra": {"panel": 1, "inverter": 8, "battery": 3}, ...}); missing entries use DEFAULT_POINTS.
Everything here is best-effort: any DB failure just means "nothing learned".
"""
from __future__ import annotations

import statistics
import time

LEARNED_ITEMS = ("Mano de obra", "Materiales eléctricos", "Estructura de montaje")

DEFAULT_POINTS: dict[str, dict[str, float]] = {
    "Mano de obra": {"panel": 1.0, "inverter": 8.0, "battery": 3.0},
    "Materiales eléctricos": {"panel": 1.0, "inverter": 6.0, "battery": 2.0},
    "Estructura de montaje": {"panel": 1.0, "inverter": 0.0, "battery": 0.0},
}
SETTINGS_KEY = "cost_effort_points"
_TTL_S = 600
_cache: dict = {}


def size_from_blob(blob: dict | None) -> dict:
    """{"panels", "inverters", "batteries"} of a draft / saved proposal version (any system type)."""
    eq = (blob or {}).get("equipment") or {}
    chosen = eq.get("chosen_scenario") or {}

    def num(*vals) -> float:
        for v in vals:
            try:
                if v not in (None, ""):
                    return float(v)
            except (TypeError, ValueError):
                continue
        return 0.0

    panels = num(eq.get("panel_count"), chosen.get("total_panels"))
    inverters = num(eq.get("inverter_qty"), chosen.get("inverter_qty"), 1.0 if (eq.get("inverter") or chosen) else 0.0)
    batteries = num((eq.get("battery_bank") or {}).get("battery_count"))
    return {"panels": panels, "inverters": inverters, "batteries": batteries}


def _weights(item: str) -> dict[str, float]:
    w = dict(DEFAULT_POINTS.get(item, {}))
    try:
        from database.supabase_client import get_client

        row = get_client().table("app_settings").select("value").eq("key", SETTINGS_KEY).execute().data
        custom = ((row or [{}])[0].get("value") or {}).get(item) or {}
        for k in ("panel", "inverter", "battery"):
            if custom.get(k) is not None:
                w[k] = float(custom[k])
    except Exception:                                   # noqa: BLE001 — defaults are fine
        pass
    return w


def points(item: str, size: dict) -> float:
    w = _weights(item)
    return (size.get("panels", 0) * w.get("panel", 0) + size.get("inverters", 0) * w.get("inverter", 0)
            + size.get("batteries", 0) * w.get("battery", 0))


def _history() -> dict[str, list[tuple[str, float, dict]]]:
    """{item: [(project_id, real paid amount USD, project size)]} — one entry per project and item."""
    from database.supabase_client import get_client

    c = get_client()
    exp = (c.table("project_expenses").select("project_id,description,amount_usd")
           .in_("description", list(LEARNED_ITEMS)).eq("paid", True).gt("amount_usd", 0).execute().data) or []
    if not exp:
        return {}
    pids = sorted({e["project_id"] for e in exp})
    projs = c.table("projects").select("id,version_id").in_("id", pids).execute().data or []
    vids = [p["version_id"] for p in projs if p.get("version_id")]
    vers = c.table("proposal_versions").select("id,data").in_("id", vids).execute().data if vids else []
    size_by_version = {v["id"]: size_from_blob(v.get("data")) for v in (vers or [])}
    size_by_project = {p["id"]: size_by_version.get(p.get("version_id")) for p in projs}

    totals: dict[tuple[str, str], float] = {}
    for e in exp:
        key = (e["description"], e["project_id"])
        totals[key] = totals.get(key, 0.0) + float(e["amount_usd"] or 0)
    out: dict[str, list] = {}
    for (item, pid), amount in totals.items():
        size = size_by_project.get(pid)
        if size:
            out.setdefault(item, []).append((pid, amount, size))
    return out


def learned_rate(item: str) -> tuple[float, int] | None:
    """(USD per effort point, number of projects it comes from) or None when no paid history exists."""
    if item not in LEARNED_ITEMS:
        return None
    hit = _cache.get("hist")
    if not hit or time.time() - hit[0] > _TTL_S:
        try:
            _cache["hist"] = hit = (time.time(), _history())
        except Exception:                               # noqa: BLE001 — informational
            _cache["hist"] = hit = (time.time(), {})
    rates = []
    for _pid, amount, size in hit[1].get(item, []):
        pts = points(item, size)
        if pts > 0:
            rates.append(amount / pts)
    if not rates:
        return None
    return statistics.median(rates), len(rates)


def learned_cost(item: str, size: dict | None) -> tuple[float, str] | None:
    """(pre-fill cost USD, tooltip text) for this design, or None to fall back to the per-Wp rate."""
    if not size:
        return None
    got = learned_rate(item)
    pts = points(item, size) if got else 0.0
    if not got or pts <= 0:
        return None
    rate, n = got
    return round(rate * pts, 2), (f"Estimado con {n} proyecto{'s' if n != 1 else ''} real{'es' if n != 1 else ''}: "
                                  f"${rate:,.2f} por punto de esfuerzo × {pts:,.0f} puntos")


def clear_cache() -> None:
    _cache.clear()
