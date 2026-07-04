"""
WeasyPrint PDF generator: data dict → Jinja2 HTML → PDF bytes → Supabase Storage. Phase 1.

Templates (proposals/templates/):
    grid_zero_es.html  — Grid Zero, Spanish
    grid_zero_en.html  — Grid Zero, English
    off_grid_es.html   — Off-Grid / Hybrid, Spanish
    off_grid_en.html   — Off-Grid / Hybrid, English
"""
from __future__ import annotations
from pathlib import Path
from datetime import date as dt

import weasyprint
from jinja2 import Environment, FileSystemLoader

from proposals.assets.assets import get_logo_b64, get_signature_b64, get_signature_white_b64, get_isotipo_white_b64

TEMPLATE_DIR = Path(__file__).parent / "templates"


# ── formatters ───────────────────────────────────────────────────────────────

def _crc(v: float) -> str:
    return f"₡{int(round(v)):,}"

def _usd(v: float, d: int = 2) -> str:
    return f"${v:,.{d}f}"

def _kwh(v: float, d: int = 2) -> str:
    return f"{v:,.{d}f}"

def _pct(v: float, d: int = 2) -> str:
    return f"{v:.{d}f}%"


# ── hardcoded reference data (María José Castro — Grid Zero) ─────────────────
# Used for Phase 1 testing. Phase 2 replaces this with live wizard data.

MARIA_JOSE_DATA: dict = {
    "date": "1/7/2026",
    "client": {
        "name": "María José Castro",
        "location": "Atenas, Alajuela",
        "nise": "N/A",
    },
    "system_type_label": "Grid Zero",
    "intro_lines": [
        (
            "Esta propuesta se basa en la facturación eléctrica mensual aproximada según el "
            "detalle de cargas de los planos eléctricos. Propone un sistema de energía solar "
            "conectado a la red pero sin entrega de excedentes de energía (grid-zero). "
            "El diseño propuesto no incluye sistemas de respaldo de energía."
        ),
    ],
    "billing_avg": {
        "consumption_kwh": 1475.00,
        "bill_crc": 157874.0,
        "generation_kwh": 1262.08,
        "new_consumption_kwh": 520.86,
        "new_bill_crc": 51681.0,
        "savings_crc": 106192.0,
    },
    "benefits": {
        "savings_year1_usd": 2798.81,
        "savings_25yr_usd": 127873.25,
        "irr_pct": 22.92,
        "roi_years": 5.48,
        "avg_monthly_savings_usd": 233.23,
        "pct_savings": 67.26,
    },
    "benefits_notes_es": (
        "No se considera la entrega de excedentes de energía a la red eléctrica nacional"
    ),
    "benefits_notes_en": (
        "Excess energy delivered to the national grid is not considered"
    ),
    "cost_items": [
        {"item": "Paneles solares",               "item_en": "Solar panels",               "qty": 16,   "specs": "JA Solar 620 W",                                                                    "total": 1760.00},
        {"item": "Inversores",                     "item_en": "Inverters",                  "qty": 1,    "specs": "Fronius Primo 10.0-1 US",                                                           "total": 3000.00},
        {"item": "Permiso de Interconexión",       "item_en": "Interconnection Permit",     "qty": None, "specs": "Requerido por el Reglamento de Generación Distribuida",                             "specs_en": "Required by the Distributed Generation Regulation",       "total": 1000.00},
        {"item": "Diseño Eléctrico y Administración", "item_en": "Electrical Design & Management", "qty": None, "specs": "Estudios preliminares, diseño eléctrico, inspección del sitio y gestión",  "specs_en": "Preliminary studies, electrical design, site inspection and management", "total": 4350.00},
        {"item": "Mano de obra",                   "item_en": "Labor",                      "qty": None, "specs": "Instalación y costos relacionados con la obra",                                     "specs_en": "Installation and costs related to the project",            "total": 2500.00},
        {"item": "Materiales eléctricos",          "item_en": "Electrical materials",       "qty": None, "specs": "Materiales eléctricos y montaje solar",                                            "specs_en": "Electrical materials and solar mounting",                  "total": 2900.00},
        {"item": "Costos de hospedaje",            "item_en": "Accommodation costs",        "qty": None, "specs": "2 semanas de mano de obra",                                                        "specs_en": "2 weeks of labor",                                         "total": 1500.00},
        {"item": "Transporte de equipo",           "item_en": "Equipment transport",        "qty": None, "specs": "San José - Guanacaste",                                                            "specs_en": "San José - Guanacaste",                                    "total": 500.00},
        {"item": "Sistema de monitoreo remoto",    "item_en": "Remote monitoring system",   "qty": 1,    "specs": "Fronius Smart Meter",                                                               "total": 600.00},
    ],
    "total_usd": 18110.00,
    "technical": {
        "system_kw": 9.92,
        "area_m2": 32,
        "panel_count": 16,
        "inverter_count": 1,
    },
    "cost_per_wp": 1.81,
    "warranty_inverter_years": "5 años",
    "warranty_inverter_years_en": "5 years",
    "payment_notes_es": [
        "Solicitamos un pago inicial del 70% por adelantado y el 30% restante contra entrega del proyecto",
        "Duración estimada: 21 días después del pago inicial",
        "Se entrega factura electrónica por el monto total",
        "Los pagos se realizan mediante transferencia bancaria a la siguiente cuenta:",
    ],
    "payment_notes_en": [
        "We request an initial payment of 70% in advance and the remaining 30% upon project delivery",
        "Estimated duration: 21 days after initial payment",
        "An electronic invoice is provided for the full amount",
        "Payments are made via bank transfer to the following account:",
    ],
    "bank_local_lines": [
        "Banco: BAC San José (USD)",
        "Beneficiario: Pauly y Compañía Ingenieros y Arquitectos S.A.",
        "IBAN: CR94010200009461058148",
        "Cédula Jurídica: 3-101-798034",
        "Correo: facturas@paulyco.com",
    ],
    "bank_intl_lines": [
        "Formato: MT103",
        "Campo: 57",
        "Transferir a: Banco BAC San José",
        "Swift: BSNJCRSJ",
        "Dirección: Calle 0 Avenidas 3 y 5, San José, Costa Rica",
        "Nombre Completo del Beneficiario: Pauly y Compañía Ingenieros y Arquitectos",
        "IBAN del Beneficiario: CR94010200009461058148",
    ],
    "bank_local_lines_en": [
        "Bank: BAC San José (USD)",
        "Beneficiary: Pauly y Compañía Ingenieros y Arquitectos S.A.",
        "IBAN: CR94010200009461058148",
        "Tax ID: 3-101-798034",
        "Email: facturas@paulyco.com",
    ],
    "bank_intl_lines_en": [
        "Format: MT103",
        "Field: 57",
        "Transfer to: Banco BAC San José",
        "Swift: BSNJCRSJ",
        "Address: Calle 0 Avenidas 3 y 5, San José, Costa Rica",
        "Full Beneficiary Name: Pauly y Compañía Ingenieros y Arquitectos",
        "Beneficiary IBAN: CR94010200009461058148",
    ],
    "company": {
        "contact_name": "Ing. Oscar Pauly Calvo",
        "contact_title": "Gerente de Proyecto",
        "contact_title_en": "Project Manager",
        "license": "IE-30111",
        "phone": "+506 7104-8046",
        "email": "info@paulyco.com",
        "website": "www.paulyco.com",
    },
    "validity_days": 15,
}


# ── context builder ──────────────────────────────────────────────────────────

def _build_context(data: dict, language: str) -> dict:
    """Flatten and format wizard data dict into Jinja2 template context."""
    es = (language == "es")
    b = data["billing_avg"]
    ben = data["benefits"]
    tech = data["technical"]
    co = data["company"]

    cost_items_fmt = []
    for ci in data["cost_items"]:
        cost_items_fmt.append({
            "item":  ci["item"]    if es else ci.get("item_en", ci["item"]),
            "qty":   str(ci["qty"]) if ci.get("qty") is not None else "–",
            "specs": ci["specs"]   if es else ci.get("specs_en", ci["specs"]),
            "total": _usd(ci["total"]),
        })

    return {
        "logo_b64":            get_logo_b64(),
        "signature_b64":       get_signature_b64(),
        "signature_white_b64": get_signature_white_b64(),
        "isotipo_white_b64":   get_isotipo_white_b64(),
        "date":           data["date"],
        "quote_number":   data.get("quote_number", ""),
        "client":         data["client"],
        "system_type_label": data["system_type_label"],
        "intro_lines":    data["intro_lines"],
        "billing_avg": {
            "consumption_kwh":     _kwh(b["consumption_kwh"]),
            "bill_crc":            _crc(b["bill_crc"]),
            "generation_kwh":      _kwh(b["generation_kwh"]),
            "new_consumption_kwh": _kwh(b["new_consumption_kwh"]),
            "new_bill_crc":        _crc(b["new_bill_crc"]),
            "savings_crc":         _crc(b["savings_crc"]),
        },
        "benefits": {
            "savings_year1":        _usd(ben["savings_year1_usd"]),
            "savings_25yr":         _usd(ben["savings_25yr_usd"]),
            "irr":                  _pct(ben["irr_pct"]),
            "roi":                  f"{ben['roi_years']:.2f}",
            "avg_monthly_savings":  _usd(ben["avg_monthly_savings_usd"]),
            "pct_savings":          _pct(ben["pct_savings"]),
            "notes":                data.get("benefits_notes_es" if es else "benefits_notes_en", ""),
        },
        "cost_items":    cost_items_fmt,
        "total_usd":     _usd(data["total_usd"]),
        "technical": {
            "system_kw":      f"{tech['system_kw']:.2f}",
            "area_m2":        str(tech["area_m2"]),
            "panel_count":    str(tech["panel_count"]),
            "inverter_count": str(tech["inverter_count"]),
        },
        "cost_per_wp":            f"{data['cost_per_wp']:.2f}",
        "warranty_inverter_years": data.get("warranty_inverter_years" if es else "warranty_inverter_years_en", "5 años"),
        "payment_notes":  data.get("payment_notes_es" if es else "payment_notes_en", []),
        "bank_local_lines":  data.get("bank_local_lines"    if es else "bank_local_lines_en",  []),
        "bank_intl_lines":   data.get("bank_intl_lines"     if es else "bank_intl_lines_en",   []),
        "company": {
            "contact_name":  co.get("contact_name", ""),
            "contact_title": co.get("contact_title", "") if es else co.get("contact_title_en", co.get("contact_title", "")),
            "license":       co.get("license", ""),
            "phone":         co.get("phone", ""),
            "email":         co.get("email", ""),
            "website":       co.get("website", ""),
        },
        "validity_days": data.get("validity_days", 15),
    }


# ── public API ───────────────────────────────────────────────────────────────

def generate_pdf(data: dict, system_type: str, language: str) -> bytes:
    """
    Render proposal to PDF bytes.

    Args:
        data: Wizard data dict (see MARIA_JOSE_DATA for shape).
        system_type: 'grid_zero' | 'off_grid' | 'hybrid'
        language: 'es' | 'en'

    Returns PDF bytes ready for download or Supabase Storage upload.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template(f"{system_type}_{language}.html")
    context = _build_context(data, language)
    html_str = template.render(**context)

    pdf = weasyprint.HTML(
        string=html_str,
        base_url=str(TEMPLATE_DIR),
    ).write_pdf()
    return pdf


def upload_pdf(pdf_bytes: bytes, proposal_id: str, version_number: int, client_name: str) -> str:
    """
    Upload PDF to Supabase Storage.
    Path: proposals/{proposal_id}/v{n}_{date}_{client}.pdf
    Returns the storage path string.
    """
    from database.supabase_client import get_client
    today = dt.today().strftime("%Y-%m-%d")
    safe_name = client_name.replace(" ", "_")
    path = f"proposals/{proposal_id}/v{version_number}_{today}_{safe_name}.pdf"

    client = get_client()
    client.storage.from_("solar-tool").upload(
        path=path,
        file=pdf_bytes,
        file_options={"content-type": "application/pdf"},
    )
    return path
