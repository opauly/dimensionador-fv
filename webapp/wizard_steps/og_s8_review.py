"""Off-Grid Step 8 — Revisión y generación de propuesta. Port of
wizard/off_grid.py:step8_review().

Per PLAN §1.3, `build_context(blob, vid)` is the one function every route
rendering any part of this step calls — same `vid`-extension precedent as
`gz_s8_review.build_context(blob, vid)` (lock state / quote number / pdf_path
live on the `proposal_versions` ROW, not the JSONB blob).

Same PLAN §1.8 "converge on build_from_wizard_blob()" architecture as
`gz_s8_review.py`, applied here too: this module calls
`build_from_wizard_blob()` itself and reads the summary panel's numbers
straight off its return value, rather than re-deriving them a third time
(after Streamlit's own step8_review() and generator.py). This is also what
makes do-not-drop item 3's requirement — "Aprovechamiento solar" the same
number in Step 6, Step 8 and the PDF — hold *by construction* here: Step 6
(`og_s6_equipment.py`) and `build_from_wizard_blob()` (see
`proposals/generator.py`'s field-diff fix, this same build task) both call
the exact same `calculations/og_coverage.py:og_monthly_coverage_and_sim()`,
so Step 8 reading `pdf_data["technical"]["utilization_pct"]` is reading that
one shared computation's output too — never a fourth copy of it.

Off-Grid's summary panel has a genuinely different section set from Grid
Zero's (verified by reading `wizard/off_grid.py:step8_review()` itself, not
assumed from the Grid Zero build): **Técnico / Generación y autonomía /
(Facturación estimada, Hybrid-only) / Costos del proyecto** — no
"Facturación estimada" (Off-Grid has no utility bill to compare against) and
no "Proyección financiera" (no cash-flow chart either — Off-Grid's PDF has
no such section, so this step's page does not include `_s8_cashflow.html`).

Do-not-drop items carried from PLAN §1.10 (cited by number at each site
below): 3 (Aprovechamiento solar from the real simulation), 16 (hybrid
tier/caption — inert here, wired for the Hybrid follow-up phase), 17
(inverter_qty read directly), 18 (`_MAX_CHARGE_CONTROLLERS`, surfaced via
`pdf_data`'s already-resolved `inverter_count`), 20/21/22 (lifecycle: lock,
quote-number formatting), 24 (no interconnection-permit line), 26
(zero-export-style disclaimer — n/a for pure Off-Grid, present for Hybrid via
`hybrid_savings`'s own note in the template).
"""
from __future__ import annotations

_DEFAULT_INTRO_ES = (
    "Esta propuesta presenta un sistema solar aislado (off-grid) diseñado para cubrir el "
    "consumo diario estimado de la vivienda de forma independiente de la red eléctrica nacional, "
    "incluyendo banco de baterías para autonomía nocturna y de respaldo."
)
_DEFAULT_INTRO_EN = (
    "This proposal presents a standalone (off-grid) solar system designed to cover the site's "
    "estimated daily consumption independently of the national utility grid, including a battery "
    "bank for nighttime and backup autonomy."
)


def _version_and_proposal(vid: str) -> tuple[dict, dict]:
    from database.proposals_db import get_proposal, get_version

    version = get_version(vid) or {}
    proposal_id = version.get("proposal_id")
    proposal = (get_proposal(proposal_id) if proposal_id else None) or {}
    return version, proposal


def _quote_str(version: dict, proposal: dict) -> str:
    from database.proposals_db import format_quote_number

    return format_quote_number(
        proposal.get("quote_number"), proposal.get("created_at", ""), version.get("version_number", 1),
    )


def _pdf_data(blob: dict, vid: str) -> tuple[dict, dict, dict]:
    """The single shared computation behind both the summary panel and the
    generated PDF (see module docstring)."""
    from proposals.generator import build_from_wizard_blob

    version, proposal = _version_and_proposal(vid)
    quote_str = _quote_str(version, proposal)
    pdf_data = build_from_wizard_blob(blob, proposal, quote_str)
    return pdf_data, version, proposal


# ── intro paragraph (AI) ─────────────────────────────────────────────────


def generate_intro_text(blob: dict, vid: str) -> str:
    """`paso/8/intro/generar`'s core logic — verbatim port of
    step8_review()'s "Generar con IA" button (`wizard/off_grid.py`
    L2190-2229), sourcing its params from the same `pdf_data`
    `build_context()` itself reads, plus the raw `equipment`/`consumption`
    fields the AI params need that `pdf_data["technical"]` doesn't carry
    (`battery_count`, `autonomy_days`/`backup_nights` — see
    `ai/proposal_writer.py`'s own `_FACT_LABELS_ES` docstring for why those
    two are kept separate facts, not merged)."""
    from ai.proposal_writer import generate_intro

    meta = blob.get("meta") or {}
    client = blob.get("client") or {}
    site = blob.get("site") or {}
    consumption = blob.get("consumption") or {}
    equipment = blob.get("equipment") or {}
    language = meta.get("language", "es")
    system_type = meta.get("system_type", "off_grid")

    pdf_data, _version, _proposal = _pdf_data(blob, vid)
    tech = pdf_data["technical"]
    panel = equipment.get("panel") or {}
    inverter = equipment.get("inverter") or {}
    battery_bank = equipment.get("battery_bank") or {}

    from proposals.generator import _site_location

    params = {
        "system_type_key": system_type,
        "system_type": "Off-Grid (sistema aislado)" if system_type == "off_grid" else "Híbrido (red + respaldo)",
        "client_name": client.get("name", ""),
        "location": client.get("location") or _site_location(site),
        "system_kw": tech["system_kw"],
        "panel_count": tech["panel_count"],
        "panel_model": f"{panel.get('brand','')} {panel.get('model','')}".strip(),
        "inverter_count": tech["inverter_count"],
        "inverter_model": f"{inverter.get('brand','')} {inverter.get('model','')}".strip(),
        "battery_count": battery_bank.get("battery_count", 0),
        "battery_kwh": tech.get("battery_kwh", 0),
        "autonomy_days": consumption.get("autonomy_days", 0) if system_type == "off_grid" else 0,
        "backup_nights": battery_bank.get("backup_nights", 0) if system_type != "off_grid" else 0,
        "daily_generation_kwh": tech.get("daily_generation_kwh", 0),
        "daily_consumption_kwh": consumption.get("daily_kwh", 0),
    }
    generated = generate_intro(params, language)
    return generated.get(language, "")


# ── PDF generation + lock (PLAN §1.8 / do-not-drop item 21) ──────────────
# Both delegate to the exact same helpers Step 2's list-page PDF route and
# gz_s8_review.py use (webapp/blueprints/proposals.py:_generate_pdf_bytes()),
# kept as thin pass-throughs in webapp/blueprints/wizard.py — see that
# module's docstring. Exactly one PDF-bytes code path for this whole app.


# ── build_context ────────────────────────────────────────────────────────


def build_context(blob: dict, vid: str) -> dict:
    blob = blob or {}
    meta = blob.get("meta") or {}
    equipment = blob.get("equipment") or {}
    language = meta.get("language", "es")

    version, proposal = _version_and_proposal(vid)
    quote_str = _quote_str(version, proposal)

    from proposals.generator import build_from_wizard_blob

    pdf_data = build_from_wizard_blob(blob, proposal, quote_str)
    tech = pdf_data["technical"]

    panel = equipment.get("panel") or {}
    inverter = equipment.get("inverter") or {}
    battery = equipment.get("battery") or {}
    cc = equipment.get("charge_controller") or {}
    battery_bank = equipment.get("battery_bank") or {}
    split_phase = equipment.get("split_phase") or {}

    panel_sub = f"{panel.get('brand','')} {panel.get('model','')}".strip()
    inverter_sub = f"{inverter.get('brand','')} {inverter.get('model','')}".strip()
    battery_sub = f"{battery.get('brand','')} {battery.get('model','')}".strip()
    cc_sub = f"{cc.get('brand','')} {cc.get('model','')}".strip()

    hybrid_savings = pdf_data.get("hybrid_savings")
    proposal_text = blob.get("proposal_text") or (
        _DEFAULT_INTRO_ES if language == "es" else _DEFAULT_INTRO_EN
    )

    return {
        "language": language,
        # ── Técnico ──
        "system_kw": tech["system_kw"],
        "panel_count": tech["panel_count"],
        "panel_sub": panel_sub,
        "inv_qty": tech["inverter_count"],
        "inverter_sub": inverter_sub,
        "area_m2": tech["area_m2"],
        "cc_qty": equipment.get("charge_controller_qty", 1),
        "cc_sub": cc_sub,
        "battery_count": battery_bank.get("battery_count", 0),
        "battery_sub": battery_sub,
        # ── Generación y autonomía ──
        "daily_generation_kwh": tech.get("daily_generation_kwh", 0),
        "battery_kwh": tech.get("battery_kwh", 0),
        "discharge_pct": tech.get("discharge_pct", 0),
        "utilization_pct": tech.get("utilization_pct"),
        # ── Facturación estimada (Hybrid only) ──
        "hybrid_savings": hybrid_savings,
        # ── Costos del proyecto ──
        "cost_per_wp": pdf_data["cost_per_wp"],
        "subtotal_usd": pdf_data["subtotal_usd"],
        "iva_usd": pdf_data["iva_usd"],
        "total_usd": pdf_data["total_usd"],
        # ── Split-phase warning ──
        "split_phase_warning": (
            split_phase.get("warning_message") if split_phase.get("requires_split_phase") else None
        ),
        # ── Intro paragraph ──
        "proposal_text": proposal_text,
        # ── PDF fragment defaults — see gz_s8_review.py's own comment on
        # this exact pattern for why these are always set explicitly.
        "pdf_error": None,
        "pdf_ready": False,
        "pdf_lang_label": "ES" if language == "es" else "EN",
        # ── Lock block / post-lock actions (do-not-drop items 20-22) ──
        "pid": version.get("proposal_id"),
        "locked": bool(version.get("locked")),
        "sent": bool(version.get("sent_to_client")),
        "quote_str": quote_str,
        "lock_error": None,
    }
