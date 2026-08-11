from __future__ import annotations
"""AI-generated intro paragraph for proposals (ES + EN). Phase 4."""

# Facts the model is allowed to mention, in the order they read naturally in a
# proposal. Keys absent from system_params are simply skipped, which is what
# lets one prompt serve all three wizards: Grid Zero passes savings/ROI and no
# battery; Off-Grid passes battery/autonomy_days and no savings; Hybrid passes
# battery/backup_nights and savings. Anything not listed here is never shown
# to the model, so internal fields can't leak into a client-facing PDF.
#
# autonomy_days and backup_nights are deliberately separate facts, not one
# shared "autonomy" field: they answer different design questions
# (off-grid's battery is sized against full days of zero generation;
# hybrid's is sized against nights of backed-up load while the grid is
# down) and conflating them let a hybrid proposal go out with a
# vague/invented autonomy claim when neither figure was actually available
# to the model (caught 2026-08 on a real client PDF — the model wrote
# "aproximadamente medio día de autonomía" despite the fact not being in
# its list at all, a direct violation of the "NO inventes" rule below).
_FACT_LABELS_ES: list[tuple[str, str]] = [
    ("client_name",           "Cliente"),
    ("location",              "Ubicación"),
    ("system_type",           "Tipo de sistema"),
    ("system_kw",             "Potencia del arreglo (kW)"),
    ("panel_count",           "Cantidad de paneles"),
    ("panel_model",           "Modelo de panel"),
    ("inverter_count",        "Cantidad de inversores"),
    ("inverter_model",        "Modelo de inversor"),
    ("battery_count",         "Cantidad de baterías"),
    ("battery_kwh",           "Capacidad del banco (kWh)"),
    ("autonomy_days",         "Días de autonomía"),
    ("backup_nights",         "Noches de respaldo ante corte de red"),
    ("daily_generation_kwh",  "Generación diaria estimada (kWh/día)"),
    ("daily_consumption_kwh", "Consumo diario estimado (kWh/día)"),
    ("savings_year1_usd",     "Ahorro estimado año 1 (USD)"),
    ("pct_savings",           "Reducción de factura (%)"),
    ("roi_years",             "Retorno de inversión (años)"),
]

_SYSTEM_TYPE_HINTS = {
    "grid_zero": (
        "Sistema conectado a la red SIN exportación de excedentes (grid-zero): reduce la "
        "factura eléctrica, no vende energía a la distribuidora y no incluye respaldo."
    ),
    "off_grid": (
        "Sistema aislado (off-grid): NO está conectado a la red eléctrica; la generación "
        "solar y el banco de baterías cubren el consumo completo del sitio."
    ),
    "hybrid": (
        "Sistema híbrido: conectado a la red y con banco de baterías de respaldo ante cortes."
    ),
}

_PROMPT = """Eres un ingeniero solar de Pauly&Co (Costa Rica) redactando el párrafo introductorio de una cotización real para un cliente.

DATOS VERIFICADOS DEL DISEÑO (única fuente de verdad):
{facts}

CONTEXTO DEL TIPO DE SISTEMA:
{type_hint}

REGLAS ESTRICTAS:
- Escribe 2 a 3 oraciones, en un solo párrafo, sin viñetas ni encabezados. Máximo ~70 palabras en total. Sé conciso y ve directo al punto: menciona el sistema y sus componentes principales, sin repetir la misma cifra dos veces ni explicar de más.
- Empieza directo con el sistema, no con una frase de cortesía. Primera oración con esta forma: "La presente propuesta consiste en un sistema [tipo] de [potencia]..." (o equivalente). NUNCA empieces con "Con mucho gusto le presentamos", "Nos complace presentar", "Es un placer", "It is our pleasure to present" ni frases de cortesía similares.
- Usa ÚNICAMENTE las cifras listadas arriba. NO inventes, NO estimes y NO agregues datos que no aparezcan (nada de precios, plazos, garantías, porcentajes ni ahorros que no estén en la lista).
- Si un dato no está en la lista, simplemente no lo menciones.
- Tono profesional y directo, dirigido al cliente (trato de "usted"). Español de Costa Rica.
- Son estimaciones de diseño: no prometas resultados garantizados.
- Nada de frases de relleno, adornos ni cierres de venta agresivos.

{output_instruction}"""

# The instruction has to be written IN the target language, not merely name it.
# A Spanish prompt ending "responde en inglés" reliably came back in Spanish
# during testing — the surrounding language dominates. Stating the requirement
# in English fixes it.
_LANG_INSTRUCTION = {
    "es": "Responde ÚNICAMENTE con el párrafo en español, sin comillas ni texto adicional.",
    "en": (
        "IMPORTANT — LANGUAGE: Write your answer in ENGLISH, not Spanish. The design data "
        "above is in Spanish for reference only; the paragraph you produce must be in English.\n"
        "Respond with ONLY the paragraph itself — no quotes, no preamble, no extra text."
    ),
}


def _format_facts(system_params: dict) -> str:
    lines = []
    for key, label in _FACT_LABELS_ES:
        value = system_params.get(key)
        if value in (None, "", 0):
            continue
        lines.append(f"- {label}: {value}")
    return "\n".join(lines) if lines else "- (sin datos técnicos disponibles)"


def _fallback(system_params: dict, lang: str) -> str:
    """Deterministic text used when the AI call fails — never blocks the wizard."""
    stype = system_params.get("system_type_key", "")
    kw = system_params.get("system_kw")
    if lang == "en":
        base = (
            f"This proposal presents a {kw} kW solar energy system designed for the site's "
            "estimated consumption."
            if kw else
            "This proposal presents a solar energy system designed for the site's estimated consumption."
        )
        if stype == "off_grid":
            return base + " It is a standalone off-grid system with battery storage, not connected to the utility grid."
        if stype == "hybrid":
            return base + " It is a hybrid system with battery backup for utility outages."
        return base + " It is a grid-tied system without surplus export (grid-zero)."

    base = (
        f"Esta propuesta presenta un sistema de energía solar de {kw} kW dimensionado según el "
        "consumo estimado del sitio."
        if kw else
        "Esta propuesta presenta un sistema de energía solar dimensionado según el consumo estimado del sitio."
    )
    if stype == "off_grid":
        return base + " Es un sistema aislado con banco de baterías, sin conexión a la red eléctrica."
    if stype == "hybrid":
        return base + " Es un sistema híbrido con banco de baterías de respaldo ante cortes de la red."
    return base + " Es un sistema conectado a la red sin exportación de excedentes (grid-zero)."


def _generate_one(system_params: dict, lang: str) -> str:
    from ai.client import get_client, MODEL

    prompt = _PROMPT.format(
        facts=_format_facts(system_params),
        type_hint=_SYSTEM_TYPE_HINTS.get(system_params.get("system_type_key", ""), ""),
        output_instruction=_LANG_INSTRUCTION.get(lang, _LANG_INSTRUCTION["es"]),
    )
    try:
        resp = get_client().messages.create(
            model=MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip().strip('"').strip()
        # A blank or absurdly short reply is treated as a failure rather than
        # written into a client-facing PDF.
        return text if len(text) >= 40 else _fallback(system_params, lang)
    except Exception:
        return _fallback(system_params, lang)


def generate_intro(system_params: dict, language: str = "both") -> dict:
    """
    Generate a 2–4 sentence intro paragraph describing the solar solution.

    Args:
        system_params: dict of verified design figures. Recognized keys are
                       listed in _FACT_LABELS_ES, plus "system_type_key"
                       (grid_zero | off_grid | hybrid) used to pick the
                       system-type hint and the fallback wording. Missing keys
                       are skipped, so the same prompt serves both wizards —
                       Grid Zero passes savings/ROI, Off-Grid passes
                       battery/autonomy. The model is explicitly forbidden from
                       introducing any figure not present here, because this
                       text goes straight into a client-facing PDF.
        language: 'es' | 'en' | 'both'

    Returns:
        {"es": "Esta propuesta...", "en": "This proposal..."}
        (single key if language != 'both')

    Never raises: on any API failure it returns a deterministic fallback
    paragraph built from the same figures, so PDF generation can't be blocked
    by a network hiccup.
    """
    langs = ["es", "en"] if language == "both" else [language]
    return {lang: _generate_one(system_params, lang) for lang in langs}
