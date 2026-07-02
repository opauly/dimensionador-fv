from __future__ import annotations
"""CRC and USD formatters used throughout the UI and PDF templates."""


def fmt_crc(amount: float | int | None, decimals: int = 0) -> str:
    """₡1.234.567"""
    if amount is None:
        return "—"
    fmt = f"{amount:,.{decimals}f}"
    # Convert comma thousands separator to period (Costa Rican convention)
    return "₡" + fmt.replace(",", ".")


def fmt_usd(amount: float | int | None, decimals: int = 2) -> str:
    """$18,110.00"""
    if amount is None:
        return "—"
    return f"${amount:,.{decimals}f}"


def fmt_kwh(amount: float | int | None, decimals: int = 0) -> str:
    if amount is None:
        return "—"
    return f"{amount:,.{decimals}f} kWh"


def fmt_kw(amount: float | int | None, decimals: int = 2) -> str:
    if amount is None:
        return "—"
    return f"{amount:,.{decimals}f} kW"


def fmt_pct(amount: float | None, decimals: int = 2) -> str:
    """22.92%"""
    if amount is None:
        return "—"
    return f"{amount:.{decimals}f}%"


def fmt_wp_per_usd(wp: int, cost_usd: float) -> str:
    """$2.08/Wp"""
    if not wp or not cost_usd:
        return "—"
    return f"${cost_usd / wp:.2f}/Wp"


def round_crc(amount: float) -> int:
    """Round to nearest colon (standard for Costa Rican billing)."""
    return round(amount)
