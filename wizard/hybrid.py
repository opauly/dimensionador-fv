from __future__ import annotations
"""Wizard steps 4–8 for Hybrid proposals. Extends Off-Grid. Phase 5."""
import streamlit as st


def step4_loads() -> dict | None:
    """Same as off_grid.step4_loads with grid connection option."""
    raise NotImplementedError("Phase 5")


def step5_demand() -> dict | None:
    raise NotImplementedError("Phase 5")


def step6_equipment() -> dict | None:
    raise NotImplementedError("Phase 5")


def step7_costs() -> dict | None:
    raise NotImplementedError("Phase 5")


def step8_review(site, loads, equipment, costs, language) -> None:
    """Includes AC coupling note in proposal text."""
    raise NotImplementedError("Phase 5")
