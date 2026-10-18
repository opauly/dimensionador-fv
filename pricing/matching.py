"""Suggest where each proforma line belongs: a catalog item, the mounting
structure rate, the accessories line, or nothing.

Targets are strings so they round-trip through an HTML <select>:
    "<table>:<uuid>"   panels | inverters | batteries | charge_controllers | monitoring_devices
    "service:estructura" | "service:accesorios"
    "skip"
Suggestions are only suggestions — the import screen lets the user change each.
"""
from __future__ import annotations

import re

SERVICE_MOUNTING = "service:estructura"
SERVICE_ACCESSORIES = "service:accesorios"
SKIP = "skip"

TABLE_LABELS = {
    "panels": "Panel",
    "inverters": "Inversor",
    "batteries": "Batería",
    "charge_controllers": "Controlador",
    "monitoring_devices": "Monitoreo",
}

# Keyword -> which catalog table a line most likely belongs to. Order matters:
# the first hit wins. Meters/cables/fuses/busbars are deliberately NOT here —
# they are accessories, not catalog equipment.
_TABLE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("panels", ("PANEL SOLAR", "MODULO SOLAR", "MÓDULO SOLAR", "PV MODULE", "BIFACIAL")),
    ("batteries", ("BATERIA", "BATERÍA", "BATTERY", "PYLONTECH", "LIFEPO4")),
    ("charge_controllers", ("CONTROLADOR", "MPPT", "SMARTSOLAR", "CHARGE CONTROLLER")),
    ("inverters", ("INVERSOR", "MULTIPLUS", "QUATTRO", "FRONIUS", "INVERTER")),
    ("monitoring_devices", ("EKRANO", "CERBO", " GX", "SMART METER")),
]
_MOUNTING_KEYWORDS = (
    "RIEL", "RAIL", "CLAMP", "CONECTOR T", "CONECTOR Z", "FIJADOR", "L-FOOT",
    "UNION PARA RIEL", "TERMINAL DE TIERRA", "GROUNDING", "ESTRUCTURA", "SOPORTE",
)


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^A-Z0-9]+", (s or "").upper()) if t}


def guess_table(description: str) -> str | None:
    d = " " + (description or "").upper()
    if any(k in d for k in _MOUNTING_KEYWORDS):
        return None
    for table, keys in _TABLE_KEYWORDS:
        if any(k in d for k in keys):
            return table
    return None


def score_model(description: str, model: str) -> float:
    """1.0 if the whole model string appears in the description (ignoring
    punctuation); otherwise the fraction of the model's tokens present. Dealers
    mistype ('PRIMO 10.01-1' for 'Primo 10.0-1'), so token overlap is the
    fallback — but series numbers like 48/3000 vs 48/5000 must not cross-match,
    which the 0.6 floor in `suggest()` guards against."""
    if _norm(model) and _norm(model) in _norm(description):
        return 1.0
    mt = _tokens(model)
    if not mt:
        return 0.0
    return len(mt & _tokens(description)) / len(mt)


def suggest(description: str, catalog: dict[str, list[dict]]) -> tuple[str, float]:
    """(target, confidence). `catalog` maps table name -> rows with id/brand/model."""
    table = guess_table(description)
    if table:
        best, best_score = None, 0.0
        for row in catalog.get(table, []):
            s = score_model(description, row.get("model", ""))
            if s > best_score:
                best, best_score = row, s
        if best is not None and best_score >= 0.6:
            return f"{table}:{best['id']}", best_score
        return SKIP, 0.0   # equipment-looking line with no catalog twin
    d = (description or "").upper()
    if any(k in d for k in _MOUNTING_KEYWORDS):
        return SERVICE_MOUNTING, 0.9
    return SERVICE_ACCESSORIES, 0.5
