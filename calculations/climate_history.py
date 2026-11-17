"""Multi-year hourly sunlight (GHI) for the reference climate zones: download, store, and report how fresh it is.

Table: public.climate_ghi_history (one row per zone per year, see database/migrations/069). Source: Open-Meteo archive
(`shortwave_radiation`, UTC), the same variable and hour convention as vrm.weather_hourly.ghi_wm2. Only the public reference points
below are sent to the service, never a client's coordinates. Safe to re-run (upsert per zone/year).

Used by scripts/fetch_climate_history.py (command line) and by the wizard's small "Actualizar clima" button (background thread).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date

import requests

log = logging.getLogger(__name__)

FIRST_YEAR = 2021               # the history starts here; a zone/year is only ever added once it is complete

# zone key -> (label, lat, lon). Public reference points, one per climate zone of Costa Rica.
ZONES = {
    "caribe_norte":     ("Caribe norte (Sarapiquí)", 10.46, -84.01),
    "caribe_sur":       ("Caribe sur (Limón)", 9.99, -83.03),
    "zona_norte":       ("Zona norte (San Carlos)", 10.32, -84.43),
    "guanacaste":       ("Guanacaste (Liberia)", 10.63, -85.44),
    "pacifico_central": ("Pacífico central (Jacó)", 9.61, -84.63),
    "pacifico_sur":     ("Pacífico sur (Golfito)", 8.64, -83.17),
    "valle_central":    ("Valle Central (San José)", 9.93, -84.08),
    "altura_turrialba": ("Altura (Turrialba)", 9.90, -83.68),
    "altura_monteverde": ("Altura (Monteverde)", 10.30, -84.82),
}
API = "https://archive-api.open-meteo.com/v1/archive"


def _get(params: dict, tries: int = 5) -> dict:
    """One Open-Meteo call with patience: the free API rate-limits and sometimes times out."""
    for i in range(tries):
        try:
            r = requests.get(API, params=params, timeout=90)
            if r.status_code == 429:
                time.sleep(20 * (i + 1))
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))
    raise RuntimeError("Open-Meteo kept rate-limiting")


def fetch_year(lat: float, lon: float, y: int) -> list[int] | None:
    """Hourly GHI W/m2 (rounded ints) for one calendar year, or None when the year is not complete."""
    h = _get({"latitude": lat, "longitude": lon, "start_date": f"{y}-01-01", "end_date": f"{y}-12-31",
              "hourly": "shortwave_radiation", "timezone": "UTC"})["hourly"]
    vals = [0 if v is None else int(round(v)) for v in h["shortwave_radiation"]]
    return vals if len(vals) in (8760, 8784) else None


def fetch_zone(lat: float, lon: float, y0: int, y1: int) -> dict[int, list[int]]:
    """{year: hourly GHI} for y0..y1 inclusive, one request per year; a year is kept only when it is complete."""
    by_year: dict[int, list[int]] = {}
    for y in range(y0, y1 + 1):
        vals = fetch_year(lat, lon, y)
        if vals:
            by_year[y] = vals
        time.sleep(2.0)
    return by_year


def store_year(db, key: str, y: int, vals: list[int]) -> None:
    label, lat, lon = ZONES[key]
    db.table("climate_ghi_history").upsert(
        {"zone": key, "label": label, "lat": lat, "lon": lon, "year": y, "ghi_wm2": vals}, on_conflict="zone,year").execute()


def last_complete_year(today: date | None = None) -> int:
    """The latest calendar year that has fully passed."""
    return (today or date.today()).year - 1


# ── freshness ────────────────────────────────────────────────────────────

_ST_TTL_S = 60
_st_cache: dict = {"at": 0.0, "val": None}


def loaded_rows() -> list[dict]:
    """[{zone, year, fetched_at}] already stored (no sunlight arrays, so it is light)."""
    from database.supabase_client import get_client

    return get_client().table("climate_ghi_history").select("zone,year,fetched_at").execute().data or []


def missing(rows: list[dict], today: date | None = None) -> dict[str, list[int]]:
    """{zone: [complete years not stored yet]} for the zones that lack some."""
    have: dict[str, set] = {z: set() for z in ZONES}
    for r in rows:
        if r["zone"] in have:
            have[r["zone"]].add(int(r["year"]))
    want = range(FIRST_YEAR, last_complete_year(today) + 1)
    return {z: [y for y in want if y not in have[z]] for z in ZONES if any(y not in have[z] for y in want)}


def status(force: bool = False, today: date | None = None) -> dict:
    """What the wizard shows: years loaded, when the data was last downloaded, and whether a finished year is missing.
    {ok, zones, first_year, last_year, fetched_on (date), age_days, missing_years [..], stale (bool)}; ok False when the table
    cannot be read."""
    if not force and _st_cache["val"] is not None and time.time() - _st_cache["at"] < _ST_TTL_S:
        return _st_cache["val"]
    try:
        rows = loaded_rows()
    except Exception:                                       # noqa: BLE001
        log.warning("climate_history: could not read the status", exc_info=True)
        return {"ok": False, "stale": False}
    today = today or date.today()
    miss = missing(rows, today)
    if rows:
        years = sorted({int(r["year"]) for r in rows})
        fetched = max(str(r["fetched_at"])[:10] for r in rows)
        age = (today - date.fromisoformat(fetched)).days
    else:
        years, fetched, age = [], None, None
    per_zone: dict[str, int] = {}
    for r in rows:
        per_zone[r["zone"]] = per_zone.get(r["zone"], 0) + 1
    val = {"ok": True, "zones": len({r["zone"] for r in rows}), "n_years": max(per_zone.values(), default=0), "first_year": years[0] if years else None,
           "last_year": years[-1] if years else None, "fetched_on": fetched, "age_days": age,
           "missing_years": sorted({y for ys in miss.values() for y in ys}), "stale": bool(miss)}
    _st_cache.update(at=time.time(), val=val)
    return val


def years_text(default: int = 5) -> str:
    """"5 años" / "6 años" for labels: how many years of weather each zone has stored (the default when unreadable)."""
    n = (status() or {}).get("n_years") or default
    return f"{n} años" if n != 1 else "1 año"


# ── background update ────────────────────────────────────────────────────

_lock = threading.Lock()
_job: dict = {"running": False, "done": 0, "total": 0, "error": None, "finished_at": None}


def job_state() -> dict:
    with _lock:
        return dict(_job)


def start_update() -> bool:
    """Download only the finished years that are missing, on a background thread, then rebuild the simulation dataset so it
    picks them up. False when an update is already running."""
    with _lock:
        if _job["running"]:
            return False
        _job.update(running=True, done=0, total=0, error=None, finished_at=None)
    threading.Thread(target=_work, daemon=True, name="climate-update").start()
    return True


def _work() -> None:
    err = None
    try:
        from database.supabase_client import get_client

        db = get_client()
        todo = missing(loaded_rows())
        with _lock:
            _job["total"] = sum(len(v) for v in todo.values())
        for key, years in todo.items():
            _, lat, lon = ZONES[key]
            for y in years:
                vals = fetch_year(lat, lon, y)
                if vals:
                    store_year(db, key, y, vals)
                with _lock:
                    _job["done"] += 1
                time.sleep(2.0)                             # be polite to the free API
        _st_cache["val"] = None
        if todo:
            from calculations import fleet_simulation

            fleet_simulation.refresh(blocking=False)       # reload the weather into the simulation dataset
    except Exception as e:                                  # noqa: BLE001
        log.warning("climate_history: update failed", exc_info=True)
        err = str(e)[:200] or "error"
    finally:
        with _lock:
            _job.update(running=False, error=err, finished_at=time.time())
