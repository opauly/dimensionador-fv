"""Base64-encoded logo for embedding in victron/weekly_report.py's PDF header.

Forked, partial duplicate of proposals/assets/assets.py (Phase 3 of the
Dimensionador/VRM Monitor split) — only get_logo_b64() and the
Logo_color_v3.png it reads are copied here; get_signature_b64()/
get_signature_white_b64()/get_isotipo_white_b64() are Dimensionador
proposal-PDF-only and victron/vrm_api never call them, so they're left out
rather than duplicated unused. Dimensionador keeps using its own
proposals/assets/assets.py unchanged.
"""
import base64
from pathlib import Path

_ASSETS = Path(__file__).parent


def get_logo_b64() -> str:
    """Logo color PNG as base64 data URI string."""
    path = _ASSETS / "Logo_color_v3.png"
    if not path.exists():
        return ""
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/png;base64,{data}"
