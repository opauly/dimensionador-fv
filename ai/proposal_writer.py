"""AI-generated intro paragraph for proposals (ES + EN). Phase 4."""


def generate_intro(system_params: dict, language: str = "both") -> dict:
    """
    Generate a 2–4 sentence intro paragraph describing the solar solution.

    Args:
        system_params: dict with client_name, system_type, system_kw,
                       panel_count, savings_year1_usd, irr_pct, roi_years
        language: 'es' | 'en' | 'both'

    Returns:
        {"es": "Esta propuesta...", "en": "This proposal..."}
        (single key if language != 'both')
    """
    raise NotImplementedError("Phase 4")
