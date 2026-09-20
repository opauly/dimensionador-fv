"""Grid Zero Step 8 — Revisión y generación de propuesta. Port of
wizard/grid_zero.py:step8_review().

Per PLAN §1.3, `build_context(blob, vid)` is the one function every route
rendering any part of this step calls. It takes `vid` in addition to `blob`
(a deliberate, disclosed extension of the plan's literal `build_context(blob)`
signature) because three things this step shows live on the
`proposal_versions` ROW, not in the JSONB blob at all: whether the version is
locked, its quote number (needs `proposals.quote_number` + `created_at` +
`version_number`), and its `pdf_path`. Every route below still funnels
through this one function for everything it renders, which is the actual
invariant §1.3 protects against — a partial recompute silently drifting from
the full page.

PLAN §1.8's converge-on-one-path decision is applied here in its strongest
form: rather than re-deriving billing_avg/benefits/technical a THIRD time
(after Streamlit's step8_review() and proposals/generator.py:
build_from_wizard_blob()), this module calls build_from_wizard_blob() itself
and reads the summary panel's numbers straight off its return value. The
on-screen review and the generated PDF are therefore not just "kept in sync
by two people remembering to update both" — they are numerically the same
computation, by construction. This is a deliberate improvement over the
literal Streamlit source (which has its own, separately-maintained copy of
this arithmetic) and follows directly from §1.8's own principle applied one
layer further up.

Do-not-drop items carried from PLAN §1.10 (cited by number at each site
below): 3 (self_consumption_pct), 20/21/22 (lifecycle: transitions, lock,
quote-number formatting), 26 (zero-export disclaimer, carried via
`benefits_notes`).
"""
from __future__ import annotations

_DEFAULT_INTRO_ES = (
    "Esta propuesta se basa en la facturación eléctrica mensual aproximada. "
    "Propone un sistema de energía solar conectado a la red pero sin entrega de "
    "excedentes de energía (grid-zero). El diseño propuesto no incluye sistemas de respaldo de energía."
)
_DEFAULT_INTRO_EN = (
    "This proposal is based on approximate monthly electricity billing. "
    "It proposes a solar energy system connected to the grid without exporting surplus energy (grid-zero). "
    "The proposed design does not include energy backup systems."
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
    generated PDF (see module docstring) — returns (pdf_data, version,
    proposal) so callers needing the row-level fields don't re-fetch them."""
    from proposals.generator import build_from_wizard_blob

    version, proposal = _version_and_proposal(vid)
    quote_str = _quote_str(version, proposal)
    pdf_data = build_from_wizard_blob(blob, proposal, quote_str)
    return pdf_data, version, proposal


# ── intro paragraph (AI) ─────────────────────────────────────────────────


def generate_intro_text(blob: dict, vid: str) -> str:
    """`paso/8/intro/generar`'s core logic — verbatim port of step8_review()'s
    "Generar con IA" button, sourcing its params from the same `pdf_data`
    build_context() itself reads (see module docstring) rather than
    re-deriving sizing/savings a third time."""
    from ai.proposal_writer import generate_intro

    meta = blob.get("meta") or {}
    client = blob.get("client") or {}
    site = blob.get("site") or {}
    equipment = blob.get("equipment") or {}
    language = meta.get("language", "es")

    pdf_data, _version, _proposal = _pdf_data(blob, vid)
    tech = pdf_data["technical"]
    ben = pdf_data["benefits"]
    panel = equipment.get("panel") or {}
    inverter = equipment.get("inverter") or {}

    params = {
        "system_type_key": "grid_zero",
        "system_type": "Grid Zero (sin exportación de excedentes)",
        "client_name": client.get("name", ""),
        "location": client.get("location") or ", ".join(
            p for p in (site.get("city"), site.get("province")) if p
        ),
        "system_kw": tech["system_kw"],
        "panel_count": tech["panel_count"],
        "panel_model": f"{panel.get('brand','')} {panel.get('model','')}".strip(),
        "inverter_model": f"{inverter.get('brand','')} {inverter.get('model','')}".strip(),
        "savings_year1_usd": round(ben["savings_year1_usd"]) if ben["savings_year1_usd"] else 0,
        "pct_savings": round(ben["pct_savings"], 1) if ben["pct_savings"] else 0,
        "roi_years": round(ben["roi_years"], 1) if ben["roi_years"] else 0,
    }
    generated = generate_intro(params, language)
    return generated.get(language, "")


# ── PDF generation + lock (PLAN §1.8 / do-not-drop item 21) ──────────────
# Both delegate to the exact same helpers Step 2's list-page PDF route uses
# (webapp/blueprints/proposals.py:_generate_pdf_bytes(), itself a thin
# wrapper over build_from_wizard_blob() + generate_pdf()) — see that
# module's docstring. Kept as thin pass-throughs in webapp/blueprints/
# wizard.py rather than duplicated here, so there is exactly one PDF-bytes
# code path for this whole app (PLAN §1.8's non-negotiable rule).


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
    b = pdf_data["billing_avg"]
    ben = pdf_data["benefits"]

    panel = equipment.get("panel") or {}
    inverter = equipment.get("inverter") or {}
    panel_sub = f"{panel.get('brand','')} {panel.get('model','')}".strip()
    inverter_sub = f"{inverter.get('brand','')} {inverter.get('model','')}".strip()

    has_billing = bool(b.get("consumption_kwh") or b.get("bill_crc"))
    has_financials = bool(ben.get("savings_year1_usd"))

    cashflow_chart_html = None
    escalation = 0.05
    total_usd = pdf_data["total_usd"]
    savings_year1_usd = ben["savings_year1_usd"]
    if has_financials and total_usd > 0:
        from webapp.figures import cashflow_fig, fig_to_fragment

        cashflow_chart_html = fig_to_fragment(cashflow_fig(total_usd, savings_year1_usd, escalation))

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
        "self_consumption_pct": tech.get("self_consumption_pct"),
        # ── Costos del proyecto ──
        "cost_per_wp": pdf_data["cost_per_wp"],
        "subtotal_usd": pdf_data["subtotal_usd"],
        "iva_usd": pdf_data["iva_usd"],
        "total_usd": total_usd,
        # ── Facturación estimada ──
        "has_billing": has_billing,
        "billing_avg": b,
        "pct_savings": ben.get("pct_savings", 0),
        # ── Proyección financiera ──
        "has_financials": has_financials,
        "savings_year1_usd": savings_year1_usd,
        "savings_25yr_usd": ben.get("savings_25yr_usd", 0),
        "irr_pct": ben.get("irr_pct", 0),
        "roi_years": ben.get("roi_years", 0),
        "cashflow_chart_html": cashflow_chart_html,
        "escalation_pct": round(escalation * 100),
        # ── Intro paragraph ──
        "proposal_text": proposal_text,
        # ── PDF fragment defaults — only paso8_pdf's own response fills
        # these in for real; a plain GET of the step has generated nothing
        # yet. Set explicitly (rather than relying on Jinja's Undefined
        # being falsy) so this context dict is always complete, matching
        # every other step's `ctx.setdefault("error", None)` convention.
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
