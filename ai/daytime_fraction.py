from __future__ import annotations
"""Grid Zero's daytime-consumption-fraction estimator. Phase 20 Step 5
(PLAN_PHASE20_PROPOSALS_JINJA.md §1.7's AI-entry-point table) — moved
**verbatim** out of `wizard/grid_zero.py` (previously `_estimate_daytime_fraction_ai()`,
a module-private function that built its own `anthropic.Anthropic` client
inline), because that was the one AI prompt left living outside `ai/` and a
Flask blueprint must never hold a prompt directly.

This is a *move*, not a rewrite: the body is unchanged (same prompt, same
model, same fallback, same clamping) so `main`'s Streamlit behaviour is
identical — `wizard/grid_zero.py` now imports this function under its old
private name instead of defining it. Deliberately does NOT route through
`ai/client.py`'s shared singleton (`ai.client.get_client()`/`MODEL`): that
singleton is pinned to `claude-sonnet-4-6` for `ai/proposal_writer.py`'s
intro-paragraph prompt, whereas this function has always used
`claude-haiku-4-5-20251001` for a much smaller bounded-classification task.
Verbatim means verbatim, not "verbatim except quietly switched to a shared
client/model" — that would be a behaviour change dressed up as a move.
"""


def estimate_daytime_fraction_ai(loads: list[dict], location: str) -> tuple[float, str]:
    """
    Call Claude Haiku to estimate the fraction of daily consumption that
    occurs during solar-production hours (roughly 7 am – 5 pm).

    Returns (daytime_fraction, explanatory_note).
    Falls back to 0.45 if the AI call fails.
    """
    import os, json
    try:
        import anthropic
        loads_text = json.dumps(loads, ensure_ascii=False) if loads else "No hay datos de cargas disponibles."
        prompt = (
            "Eres un ingeniero solar en Costa Rica. Analiza el perfil de cargas eléctricas de este proyecto "
            f"y estima qué fracción del consumo total ocurre durante las horas de producción solar (7:00–17:00).\n\n"
            f"Ubicación: {location}\n"
            f"Cargas instaladas (JSON):\n{loads_text}\n\n"
            "Considera: uso diurno de electrodomésticos, AC, bombas de agua, iluminación, etc. "
            "Considera que la noche, la madrugada y días nublados también consumen energía de la red.\n\n"
            "Responde SOLO con JSON (sin markdown):\n"
            '{"daytime_fraction": 0.48, "note": "El perfil tiene uso significativo de AC y bomba de agua durante el día..."}'
        )
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
        data = json.loads(text)
        fraction = float(data.get("daytime_fraction") or 0.45)
        fraction = max(0.1, min(0.9, fraction))
        note = str(data.get("note") or "")
        return fraction, note
    except Exception:
        return 0.45, ""
