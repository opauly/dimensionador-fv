"""
Base64-encoded logo and signature for embedding in Jinja2 PDF templates.
Run tools/invert_signature.py once after placing firma_white.png in this directory.
"""
import base64
from pathlib import Path

_ASSETS = Path(__file__).parent


def _b64(filename: str) -> str:
    path = _ASSETS / filename
    if not path.exists():
        return ""
    return base64.b64encode(path.read_bytes()).decode()


def get_logo_b64() -> str:
    """Logo color PNG as base64 data URI string."""
    data = _b64("Logo_color_v3.png")
    return f"data:image/png;base64,{data}" if data else ""


def get_signature_b64() -> str:
    """Dark (inverted) signature PNG as base64 data URI string."""
    data = _b64("firma_dark.png")
    return f"data:image/png;base64,{data}" if data else ""
