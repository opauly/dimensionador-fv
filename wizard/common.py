from __future__ import annotations
"""Wizard steps 1–3 shared across all system types. Phase 2."""
import streamlit as st


def step1_system_type() -> str | None:
    """Select system type and language. Returns 'grid_zero' | 'off_grid' | 'hybrid' or None."""
    raise NotImplementedError("Phase 2")


def step2_client() -> dict | None:
    """Client name, phone, email with typeahead autocomplete from clients table."""
    raise NotImplementedError("Phase 2")


def step3_site() -> dict | None:
    """City/province → geocode → PVGIS fetch. Returns site dict with lat, lon, pvgis_data."""
    raise NotImplementedError("Phase 2")
