"""Current transformers ("donas") of an energy meter that needs them (Fronius Smart Meter WR 100-600 V-3).

One transformer per phase: split-phase (240 V, two hot lines) takes 2, three-phase takes 3. The size (100 / 250 / 400 A,
all 333 mV) is not decided by the tool: the list marks it «POR VERIFICAR TAMAÑO»."""
from __future__ import annotations

CT_MODEL_HINT = "wr 100-600"        # fallback for a design saved before the catalog had the `uses_cts` column


def uses_cts(monitoring: dict | None) -> bool:
    m = monitoring or {}
    return bool(m.get("uses_cts")) or CT_MODEL_HINT in (m.get("model") or "").lower()


def phases(inverter: dict | None) -> int:
    ph = str((inverter or {}).get("phase") or "").lower()
    return 3 if ph.startswith(("3", "three", "tri")) else 2


def ct_count(monitoring: dict | None, inverter: dict | None) -> int:
    return phases(inverter) if uses_cts(monitoring) else 0
