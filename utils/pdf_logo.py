"""The Pauly & Co logo as an image for the engineering sheets (unifilar, plano de taller, plano de techo): one drawing function so every
title block shows the same logo. The file is the one the proposals already use (proposals/assets/Logo_color_v3.png)."""
from __future__ import annotations

from pathlib import Path

LOGO_PATH = Path(__file__).resolve().parent.parent / "proposals" / "assets" / "Logo_color_v3.png"
LOGO_ASPECT = 567 / 139          # visible width / height of the logo artwork (the file has transparent padding below)
_reader = None


def draw_logo(c, x: float, y: float, height: float) -> float:
    """Draw the logo with its lower-left corner at (x, y), `height` points tall. Returns the width used (points)."""
    global _reader
    from reportlab.lib.utils import ImageReader

    if _reader is None:
        _reader = ImageReader(str(LOGO_PATH))
    full_h = height * 156 / 139      # the PNG is 567x156: the artwork fills the top 139 rows
    w = height * LOGO_ASPECT
    c.drawImage(_reader, x, y - (full_h - height), width=w, height=full_h, mask="auto", preserveAspectRatio=True)
    return w
