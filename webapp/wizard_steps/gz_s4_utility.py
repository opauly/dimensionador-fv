"""Grid Zero Step 4 — Distribuidora. Port of wizard/grid_zero.py:step4_utility().

Per PLAN §1.3, `build_context(blob)` is the one function every route
rendering any part of this step calls — the full-page GET, the
`Siguiente`/`Atrás` persist-and-redirect POSTs, and the distributor-change
`hx-get` fragment (`_s4_tarifa.html`) alike.

Do-not-drop item 26 (PLAN §1.10): the fixed-charge caption below carries the
*exact* Spanish disclaimer text from `wizard/grid_zero.py` L68-73 verbatim —
`new_bill` (used from Step 6 onward) is energy + access charge only, no
bomberos/alumbrado/IVA/Generación Distribuida. Do not paraphrase it.
"""
from __future__ import annotations

# Verbatim from wizard/grid_zero.py:step4_utility() L69-73 — do not paraphrase
# (PLAN §1.10 item 26). Rendered next to the selected tariff's access charge.
FIXED_CHARGE_DISCLAIMER = (
    "la factura estimada solo incluye cargo por energía + cargo fijo; "
    "no incluye bomberos, alumbrado público, IVA ni cargos de "
    "Generación Distribuida"
)


def _distributors() -> list[dict]:
    from database.tariffs_db import list_distributors

    return list_distributors()


def _tariff_types(distributor_id: str | None) -> list[dict]:
    if not distributor_id:
        return []
    from database.tariffs_db import list_tariff_types

    return list_tariff_types(distributor_id)


def _utility_for(distributor_id: str | None, tariff_type_id: str | None) -> dict:
    """Distributor + tariff rate fields, verbatim shape of step4_utility()'s
    return dict minus `nise` (callers that shouldn't touch the saved NISE —
    e.g. the distributor-change fragment — merge this via draft.patch()
    without a `nise` key so the existing value survives untouched)."""
    distributors = _distributors()
    selected_dist = next((d for d in distributors if d["id"] == distributor_id), None)
    if not selected_dist:
        selected_dist = distributors[0] if distributors else None
    if not selected_dist:
        return {}

    tariff_types = _tariff_types(selected_dist["id"])
    selected_tariff = next((t for t in tariff_types if t["id"] == tariff_type_id), None)
    if not selected_tariff:
        selected_tariff = tariff_types[0] if tariff_types else None

    result = {
        "distributor_id": selected_dist["id"],
        "distributor_name": selected_dist["name"],
        "distributor_abbrev": selected_dist["abbreviation"],
    }
    if selected_tariff:
        result.update({
            "tariff_type_id": selected_tariff["id"],
            "tariff_code": selected_tariff["code"],
            "tariff_name": selected_tariff["name"],
            # Carried into `utility` so Step 5 can estimate bills without an
            # extra DB call (PLAN's Step 4 build note).
            "access_charge_crc": selected_tariff.get("access_charge_crc", 0),
            "bomberos_pct": selected_tariff.get("bomberos_pct", 0.0175),
            "iva_threshold_kwh": selected_tariff.get("iva_threshold_kwh", 280),
        })
    else:
        for key in ("tariff_type_id", "tariff_code", "tariff_name",
                    "access_charge_crc", "bomberos_pct", "iva_threshold_kwh"):
            result.pop(key, None)
    return result


def select_distributor(distributor_id: str | None) -> dict:
    """The distributor `<select>`'s `hx-get` action — PLAN's "repopulates a
    tariff-type <select> when the distributor changes". Resets the tariff to
    that distributor's first tariff (mirrors Streamlit's own
    `default_tariff_idx` fallback-to-0 the moment the distributor changes).
    No `nise` key, so patching this into `utility` never blanks it."""
    return _utility_for(distributor_id, None)


def save_step(form) -> dict:
    """`Siguiente`/`Atrás`'s persisted fields — verbatim port of
    step4_utility()'s own return dict (distributor/tariff identity + the
    tariff's rate fields + NISE, defaulting to "N/A")."""
    distributor_id = (form.get("distributor_id") or "").strip() or None
    tariff_type_id = (form.get("tariff_type_id") or "").strip() or None
    nise = (form.get("nise") or "").strip() or "N/A"
    return {**_utility_for(distributor_id, tariff_type_id), "nise": nise}


def build_context(blob: dict) -> dict:
    blob = blob or {}
    utility = blob.get("utility") or {}
    client = blob.get("client") or {}

    distributors = _distributors()
    selected_dist_id = utility.get("distributor_id")
    if not any(d["id"] == selected_dist_id for d in distributors):
        selected_dist_id = distributors[0]["id"] if distributors else None

    tariff_types = _tariff_types(selected_dist_id)
    selected_tariff_id = utility.get("tariff_type_id")
    if not any(t["id"] == selected_tariff_id for t in tariff_types):
        selected_tariff_id = tariff_types[0]["id"] if tariff_types else None
    selected_tariff = next((t for t in tariff_types if t["id"] == selected_tariff_id), None)

    return {
        "distributors": distributors,
        "selected_dist_id": selected_dist_id,
        "tariff_types": tariff_types,
        "selected_tariff_id": selected_tariff_id,
        "selected_tariff": selected_tariff,
        "nise": utility.get("nise") or client.get("nise") or "N/A",
        "fixed_charge_disclaimer": FIXED_CHARGE_DISCLAIMER,
        "can_continue": selected_tariff is not None,
    }
