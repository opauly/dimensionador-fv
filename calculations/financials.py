"""
Financial projections: IRR, ROI, 25-year savings. Phase 2.

Validation target (María José Castro):
    savings_year1_usd=2798, total_usd=18110
    → IRR=22.92%, ROI=5.48 years, savings_25yr_usd=127873
"""
import numpy_financial as npf


def calculate_irr(total_cost_crc: float, savings_year1_crc: float, years: int = 25, escalation: float = 0.05) -> float:
    """
    Pure IRR via numpy_financial.irr().
    cashflow = [-total_cost_crc] + [savings_year1_crc * (1+escalation)^y for y in range(years)]
    Returns IRR as percentage (e.g. 22.92).
    """
    cashflow = [-total_cost_crc] + [savings_year1_crc * ((1 + escalation) ** y) for y in range(years)]
    result = npf.irr(cashflow)
    return round(result * 100, 2)


def calculate_roi(total_cost_crc: float, savings_year1_crc: float) -> float:
    """Simple payback in years. e.g. 5.48"""
    return round(total_cost_crc / savings_year1_crc, 2)


def calculate_25yr_savings(savings_year1_crc: float, escalation: float = 0.05) -> float:
    """Cumulative savings over 25 years with annual escalation."""
    return sum(savings_year1_crc * ((1 + escalation) ** y) for y in range(25))
