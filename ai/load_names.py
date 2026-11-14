"""Translate short equipment/load names (e.g. "Bomba de agua de naciente") into the proposal's language.

The wizard's load names are whatever the engineer typed, usually Spanish; the PDF follows the language picked in Step 2, so an
English quote would otherwise mix languages in the "loads covered" box. One small batched call per quote, cached by
(language, name) for the life of the process. Any failure returns the names unchanged (never blocks the PDF).
"""
from __future__ import annotations

import json

_CACHE: dict[tuple[str, str], str] = {}
_LANG_NAME = {"en": "English", "es": "Spanish (Costa Rica)"}

_PROMPT = """Translate each of these short household/electrical load names into {lang}.

Rules:
- Keep brand names, model names, numbers and units exactly as written (Starlink, MacBook, Breville, 120 V...).
- Translate every common word, even when a brand is inside the name ("Horno Breville Smart Oven Air" -> "Breville Smart Oven Air" in English, since "Horno" means oven and the brand name already says oven; "Bomba de agua" -> "Water pump").
- If a name is already entirely in {lang}, return it unchanged.
- Keep each one short and natural, no extra words, no explanations.
- Return ONLY a JSON array of strings, the same length and order as the input.

Input:
{names}
"""


def translate_names(names: list[str], lang: str) -> list[str]:
    """`names` translated into `lang` ('en'|'es'), same order. Unchanged on any failure or unsupported language."""
    if lang not in _LANG_NAME or not names:
        return list(names)
    missing = sorted({n for n in names if n and (lang, n) not in _CACHE})
    if missing:
        try:
            from ai.client import get_client, MODEL

            resp = get_client().messages.create(
                model=MODEL,
                max_tokens=800,
                messages=[{"role": "user", "content": _PROMPT.format(lang=_LANG_NAME[lang], names=json.dumps(missing, ensure_ascii=False))}],
            )
            text = resp.content[0].text.strip()
            out = json.loads(text[text.index("["): text.rindex("]") + 1])
            if isinstance(out, list) and len(out) == len(missing) and all(isinstance(x, str) and x.strip() for x in out):
                for src, dst in zip(missing, out):
                    _CACHE[(lang, src)] = dst.strip()
        except Exception:                               # noqa: BLE001 — a translation is a nicety, never a blocker
            pass
    return [_CACHE.get((lang, n), n) for n in names]
