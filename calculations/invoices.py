"""Invoices sueltos (Finanzas, migration 074). Pure module — plain dicts in,
plain dicts out — so scripts/validate_phase25_invoices.py can check it.

An invoice is in USD or CRC. Its lines are before IVA; one IVA rate applies
to the whole invoice. Payments are in the invoice's currency; the balance
(saldo) is total − payments, and the invoice is "paid" when the balance is 0.
A "linked" invoice's money now lives in the project's payments, so Finanzas
no longer counts it here.
"""
from __future__ import annotations

STATUS_LABELS = {"open": "Pendiente", "paid": "Pagado", "void": "Anulado", "linked": "Ligado a proyecto"}
IVA_RATES = [0, 1, 2, 4, 13]
EPS = 0.005


def _num(v) -> float:
    return float(v) if v not in (None, "") else 0.0


def clean_lines(lines: list[dict]) -> list[dict]:
    """Drop empty rows; a row needs a description and a price."""
    out = []
    for l in lines:
        desc = (l.get("description") or "").strip()
        qty = _num(l.get("quantity") or 1)
        price = _num(l.get("unit_price"))
        if not desc and not price:
            continue
        out.append({"description": desc or "Servicio", "quantity": qty, "unit_price": round(price, 2)})
    return out


def totals(lines: list[dict], iva_rate: float) -> dict:
    subtotal = round(sum(_num(l.get("quantity")) * _num(l.get("unit_price")) for l in lines), 2)
    iva = round(subtotal * _num(iva_rate) / 100, 2)
    return {"subtotal": subtotal, "iva": iva, "total": round(subtotal + iva, 2)}


def balance(invoice: dict, payments: list[dict]) -> dict:
    paid = round(sum(_num(p.get("amount")) for p in payments), 2)
    saldo = round(_num(invoice.get("total")) - paid, 2)
    return {"paid": paid, "saldo": saldo if abs(saldo) >= EPS else 0.0}


def status_after(invoice: dict, payments: list[dict]) -> str:
    """Status once payments change (void and linked stay as they are)."""
    if invoice.get("status") in ("void", "linked"):
        return invoice["status"]
    return "paid" if balance(invoice, payments)["saldo"] <= 0 else "open"


def check_payment(invoice: dict, payments: list[dict], amount: float) -> str | None:
    """Error text, or None when the payment can be recorded."""
    if invoice.get("status") in ("void", "linked"):
        return "Este invoice ya no recibe pagos aquí."
    if amount <= 0:
        return "El monto debe ser mayor que 0."
    saldo = balance(invoice, payments)["saldo"]
    if amount - saldo > 0.009:
        return f"El monto es mayor que el saldo pendiente ({saldo:,.2f})."
    return None


def fmt(amount, currency: str) -> str:
    v = _num(amount)
    sign = "-" if v < 0 else ""
    if currency == "CRC":
        return f"{sign}₡{abs(v):,.2f}"
    return f"{sign}${abs(v):,.2f}"


def label(invoice: dict) -> str:
    return f"Invoice {invoice['number']}"
