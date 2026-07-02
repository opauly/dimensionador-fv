from __future__ import annotations
"""Wizard steps 4–8 for Off-Grid proposals. Phase 5."""
import streamlit as st


def step4_loads() -> dict | None:
    """Critical loads table: description, watts, qty, hours/day. Autonomy slider."""
    raise NotImplementedError("Phase 5")


def step5_demand() -> dict | None:
    """Tablero upload (AI in Phase 5), 3 scenario buttons, daily kWh estimate."""
    raise NotImplementedError("Phase 5")


def step6_equipment() -> dict | None:
    """Panel + inverter + battery + charge controller selection. MPPT validation."""
    raise NotImplementedError("Phase 5")


def step7_costs() -> dict | None:
    """Line items including battery bank and charge controller. IVA always shown."""
    raise NotImplementedError("Phase 5")


def step8_review(
    site: dict,
    loads: dict,
    equipment: dict,
    costs: dict,
    language: str,
) -> None:
    """Technical summary + costs review + Generate PDF."""
    raise NotImplementedError("Phase 5")
