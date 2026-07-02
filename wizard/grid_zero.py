"""Wizard steps 4–8 for Grid Zero proposals. Phase 2."""
import streamlit as st


def step4_utility() -> dict | None:
    """Distributor, NISE, tariff type selection. Returns utility dict."""
    raise NotImplementedError("Phase 2")


def step5_consumption() -> dict | None:
    """12-month kWh / bill table, manual entry + PDF upload (AI in Phase 4)."""
    raise NotImplementedError("Phase 2")


def step6_equipment() -> dict | None:
    """Panel + inverter selection, MPPT validation, 3 scenarios, scenario selection."""
    raise NotImplementedError("Phase 2")


def step7_costs() -> dict | None:
    """Line items table, IVA toggle, totals. Returns costs dict."""
    raise NotImplementedError("Phase 2")


def step8_review(
    site: dict,
    consumption: dict,
    equipment: dict,
    costs: dict,
    language: str,
) -> None:
    """Summary cards, billing comparison, benefits, intro paragraph, Generate PDF button."""
    raise NotImplementedError("Phase 2")
