"""Hybrid Step 5 — Perfil de demanda diaria. Port of
wizard/hybrid.py:step5_demand() + `_build_step5_result()`.

Per PLAN §1.3, `build_context(blob)` is the one function every route
rendering any part of this step calls.

Reuses `og_s5_demand.py`'s existing `calculate()`/`recalculate()`/
`generate_hourly_shape()`/`build_context()`/`save_step()` UNCHANGED for
both instances on this page — verified against that module's own docstring,
which was built in Step 7 specifically parameterized (`scratch_key`,
`diversified_used_downstream`, `show_category_chart`, `show_hourly_chart`)
so this step could call it twice:
  - Critical (backup) loads: `og_s5_demand.DEFAULT_SCRATCH_KEY` ("s5og" —
    matches wizard/hybrid.py's own `off_grid._render_demand_profile_block(
    "w5og", ...)` call), `diversified_used_downstream=True`.
  - Main panel (only when `consumption.main_panel.mode == "loads"`):
    scratch key "mp" (matches wizard/hybrid.py's own "w5h_mp"),
    `diversified_used_downstream=True`, `show_category_chart=True`,
    `show_hourly_chart=False` — verbatim to
    `off_grid._render_demand_profile_block("w5h_mp", ..., show_category_chart=True,
    show_hourly_chart=False, diversified_used_downstream=True)`.

GENUINE KEY FINDING vs. the build plan's summary (reported, not silently
patched around): `og_s5_demand.calculate()`/`recalculate()`/`build_context()`
all read the loads list / prior profile from the single, hard-coded
`consumption.get("loads")` / `consumption.get("profile")` keys, regardless
of which `scratch_key` is passed in — correct for Off-Grid's own single
instance, but the wrong source for a SECOND instance whose loads/profile
live nested at `consumption.main_panel.loads` / `.profile` instead. Fixed
the same way `hy_s4_loads.py` fixes the analogous gap for
`og_s4_loads.py`'s `loads_display` fallback: `_mp_blob()` below shims a
blob whose top-level `consumption.loads`/`consumption.profile` are swapped
for the main panel's own nested values before calling any `og_s5_demand`
function for the "mp" instance — zero changes needed to og_s5_demand.py
itself (its OWN scratch reads, keyed by `scratch_key`, are untouched by
the shim and remain fully independent between the two instances).

Do-not-drop items carried from PLAN §1.10 (cited by number at each site
below): 1 (the user_confirmed override rule, inherited unchanged from
og_s5_demand.py for BOTH profile blocks), 19 (critical-loads profile with
diversified_used_downstream=True, main-panel profile with category chart
on / hourly chart off).
"""
from __future__ import annotations

from webapp.wizard_steps import og_s5_demand

CRITICAL_SCRATCH_KEY = og_s5_demand.DEFAULT_SCRATCH_KEY  # "s5og"
MP_SCRATCH_KEY = "mp"


# ── main-panel profile shim (see module docstring's "GENUINE KEY FINDING") ─


def mp_blob(blob: dict) -> dict:
    consumption = blob.get("consumption") or {}
    main_panel = consumption.get("main_panel") or {}
    return {
        **blob,
        "consumption": {
            **consumption,
            "loads": main_panel.get("loads") or [],
            "profile": main_panel.get("profile"),
        },
    }


def mp_calculate(blob: dict) -> dict:
    return og_s5_demand.calculate(mp_blob(blob), MP_SCRATCH_KEY)


def mp_recalculate(blob: dict, form) -> dict:
    return og_s5_demand.recalculate(mp_blob(blob), MP_SCRATCH_KEY, form)


def mp_context(blob: dict) -> dict:
    return og_s5_demand.build_context(
        mp_blob(blob), MP_SCRATCH_KEY,
        diversified_used_downstream=True, show_category_chart=True, show_hourly_chart=False,
    )


def critical_context(blob: dict) -> dict:
    return og_s5_demand.build_context(blob, CRITICAL_SCRATCH_KEY, diversified_used_downstream=True)


# ── Siguiente/Atrás ──────────────────────────────────────────────────────


def save_step(blob: dict) -> dict:
    """Verbatim port of `_build_step5_result()` — the critical-loads profile
    always overwrites `consumption.profile`/`daily_kwh`/`daily_kwh_diversified`
    (og_s5_demand.save_step()'s own contract, reused unchanged); the
    main-panel's `avg_kwh_month`/`avg_kwh_month_diversified` derivation
    (`round(mp_daily_kwh * 30.4, 1)`) is ported here exactly since
    og_s5_demand.py's own save_step() has no reason to know about it."""
    consumption = og_s5_demand.save_step(blob, CRITICAL_SCRATCH_KEY)

    main_panel = consumption.get("main_panel")
    if main_panel and main_panel.get("mode") == "loads":
        mp_scratch = (blob.get("scratch") or {}).get(MP_SCRATCH_KEY) or {}
        mp_profile = mp_scratch.get("profile") or main_panel.get("profile")
        if mp_profile:
            mp_daily_kwh = mp_profile.get("total_kwh_day", 0.0)
            mp_daily_kwh_diversified = mp_profile.get("total_kwh_day_diversified", mp_daily_kwh)
            consumption["main_panel"] = {
                **main_panel,
                "profile": mp_profile,
                "avg_kwh_month": round(mp_daily_kwh * 30.4, 1),
                "avg_kwh_month_diversified": round(mp_daily_kwh_diversified * 30.4, 1),
            }

    return consumption


# ── build_context ────────────────────────────────────────────────────────


def build_context(blob: dict) -> dict:
    blob = blob or {}
    consumption = blob.get("consumption") or {}
    main_panel = consumption.get("main_panel") or {}
    mp_loads_mode = bool(main_panel and main_panel.get("mode") == "loads")

    critical = critical_context(blob)
    mp = mp_context(blob) if mp_loads_mode else None

    can_continue = bool(critical["can_continue"] and (not mp_loads_mode or (mp and mp["can_continue"])))

    return {
        "critical": critical,
        "mp": mp,
        "mp_loads_mode": mp_loads_mode,
        "can_continue": can_continue,
    }
