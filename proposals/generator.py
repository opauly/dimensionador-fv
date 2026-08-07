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

def _qty(v) -> str:
    """
    Format a cost-line quantity for display.

    Off-Grid stores quantities as floats while Grid Zero stores ints, so a
    plain str() rendered "4.0 paneles" on one system type and "5" on the
    other. Integral values always render without a decimal; a genuinely
    fractional quantity keeps it.
    """
    if v is None:
        return "–"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else f"{f:g}"


def _site_location(site: dict) -> str:
    """"City, Province" from a wizard site dict, skipping whichever is missing."""
    parts = [str(site.get(k) or "").strip() for k in ("city", "province")]
    return ", ".join(p for p in parts if p)


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
        "No se considera la entrega de excedentes de energía a la red eléctrica."
    ),
    "benefits_notes_en": (
        "Excess energy delivered to the grid is not considered."
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
    # subtotal_usd/iva_usd pinned to total_usd/0 — total_usd is the validated
    # María José Castro reference figure (CONTEXT.md), not derived math here.
    "subtotal_usd": 18110.00,
    "iva_usd": 0.0,
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


# ── hardcoded reference data (Jorge Ramírez — Off-Grid) ──────────────────────
# Used for the sample-PDF test panel (Cotizaciones page). Matches the
# validation reference numbers in CONTEXT.md ("Off-Grid — Jorge Ramírez").

JORGE_RAMIREZ_DATA: dict = {
    "date": "1/7/2026",
    "client": {
        "name": "Jorge Ramírez",
        "location": "Guanacaste, Costa Rica",
        "nise": "N/A",
    },
    "system_type_label": "Off-Grid",
    "intro_lines": [
        (
            "Esta propuesta presenta un sistema solar aislado (off-grid) diseñado para "
            "cubrir el consumo diario estimado de la vivienda de forma independiente de "
            "la red eléctrica nacional, incluyendo banco de baterías para autonomía "
            "nocturna y de respaldo."
        ),
    ],
    "cost_items": [
        {"item": "Paneles solares",              "item_en": "Solar panels",              "qty": 8, "specs": "JA Solar 620 W",                     "total": 1840.00},
        {"item": "Inversor/cargador",             "item_en": "Inverter/charger",          "qty": 1, "specs": "Victron MultiPlus-II 48/5000/70-50", "total": 2400.00},
        {"item": "Baterías",                      "item_en": "Batteries",                 "qty": 2, "specs": "Pylontech US5000C 4.8 kWh",          "total": 3200.00},
        {"item": "Controlador de carga",          "item_en": "Charge controller",         "qty": 1, "specs": "Victron SmartSolar MPPT 250/100",    "total": 650.00},
        {"item": "Estructura de montaje",         "item_en": "Mounting structure",        "qty": None, "specs": "Estructura para techo",            "specs_en": "Roof mounting structure", "total": 500.00},
        {"item": "Materiales eléctricos",         "item_en": "Electrical materials",      "qty": None, "specs": "Cableado, protecciones y BOS",     "specs_en": "Wiring, protection devices and BOS", "total": 700.00},
        {"item": "Mano de obra",                  "item_en": "Labor",                     "qty": None, "specs": "Instalación y costos relacionados con la obra", "specs_en": "Installation and related project costs", "total": 800.00},
        {"item": "Diseño y gestión",               "item_en": "Design & management",       "qty": None, "specs": "Estudios preliminares y gestión del proyecto", "specs_en": "Preliminary studies and project management", "total": 230.00},
    ],
    # subtotal_usd/iva_usd pinned to total_usd/0 — total_usd is the validated
    # Jorge Ramírez reference figure (CONTEXT.md), not derived math here.
    "subtotal_usd": 10320.00,
    "iva_usd": 0.0,
    "total_usd": 10320.00,
    "technical": {
        "system_kw": 5.0,
        "area_m2": 16,
        "daily_generation_kwh": 6.38,
        "battery_kwh": 9.60,
        "discharge_pct": 66.46,
    },
    "cost_per_wp": 2.06,
    "warranty_inverter_years": "5 años",
    "warranty_inverter_years_en": "5 years",
    "warranty_battery_years": "10 años",
    "warranty_battery_years_en": "10 years",
    "payment_notes_es": [
        "Solicitamos un pago inicial del 70% por adelantado y el 30% restante contra entrega del proyecto",
        "Duración estimada: 15 días después del pago inicial",
        "Se entrega factura electrónica por el monto total",
        "Los pagos se realizan mediante transferencia bancaria a la siguiente cuenta:",
    ],
    "payment_notes_en": [
        "We request an initial payment of 70% in advance and the remaining 30% upon project delivery",
        "Estimated duration: 15 days after initial payment",
        "An electronic invoice is provided for the full amount",
        "Payments are made via bank transfer to the following account:",
    ],
    "bank_local_lines": MARIA_JOSE_DATA["bank_local_lines"],
    "bank_intl_lines": MARIA_JOSE_DATA["bank_intl_lines"],
    "bank_local_lines_en": MARIA_JOSE_DATA["bank_local_lines_en"],
    "bank_intl_lines_en": MARIA_JOSE_DATA["bank_intl_lines_en"],
    "company": MARIA_JOSE_DATA["company"],
    "validity_days": 15,
}


# ── hardcoded reference data (Hybrid variant of Jorge Ramírez) ───────────────
# Same off_grid template/context shape; only the label and intro copy differ.

HYBRID_DATA: dict = {
    **JORGE_RAMIREZ_DATA,
    "client": {
        "name": "Jorge Ramírez (Híbrido)",
        "location": "Guanacaste, Costa Rica",
        "nise": "N/A",
    },
    "system_type_label": "Híbrido",
    "intro_lines": [
        (
            "Esta propuesta presenta un sistema solar híbrido: conectado a la red "
            "eléctrica nacional para uso normal, con banco de baterías de respaldo "
            "para continuar operando durante interrupciones del suministro."
        ),
    ],
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
            "qty":   _qty(ci.get("qty")),
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
        "subtotal_usd":  _usd(data.get("subtotal_usd", data["total_usd"])),
        "iva_usd":       _usd(data.get("iva_usd", 0)),
        "total_usd":     _usd(data["total_usd"]),
        "technical": {
            "system_kw":      f"{tech['system_kw']:.2f}",
            "area_m2":        str(tech["area_m2"]),
            "panel_count":    str(tech["panel_count"]),
            "inverter_count": str(tech["inverter_count"]),
            # AI-estimated (daytime consumption fraction), not simulated like
            # Off-Grid's — see wizard/grid_zero.py: _scenario_projection().
            # None when never calculated (draft never ran "Calcular MPPT").
            "self_consumption_pct": _pct(tech["self_consumption_pct"], 0) if tech.get("self_consumption_pct") is not None else "—",
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


def _build_context_off_grid(data: dict, language: str) -> dict:
    """
    Flatten and format Off-Grid/Hybrid wizard data into Jinja2 template context.

    No billing_avg/benefits (no utility bill or grid-savings model for a
    system with no — or, for Hybrid, only partial — grid dependency) —
    replaced by battery/discharge/autonomy technical fields instead.
    """
    es = (language == "es")
    tech = data["technical"]
    co = data["company"]
    hybrid_savings = data.get("hybrid_savings")

    cost_items_fmt = []
    for ci in data["cost_items"]:
        cost_items_fmt.append({
            "item":  ci["item"]    if es else ci.get("item_en", ci["item"]),
            "qty":   _qty(ci.get("qty")),
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
        "cost_items":    cost_items_fmt,
        "subtotal_usd":  _usd(data.get("subtotal_usd", data["total_usd"])),
        "iva_usd":       _usd(data.get("iva_usd", 0)),
        "total_usd":     _usd(data["total_usd"]),
        "technical": {
            "system_kw":              f"{tech['system_kw']:.2f}",
            "area_m2":                 str(tech["area_m2"]),
            "daily_generation_kwh":    _kwh(tech.get("daily_generation_kwh", 0)),
            "battery_kwh":             _kwh(tech.get("battery_kwh", 0)),
            "discharge_pct":           _pct(tech.get("discharge_pct", 0)),
            # None when the draft has no real daily PVGIS series to simulate
            # against (see wizard/off_grid.py: _og_monthly_coverage_and_sim()).
            "utilization_pct":        _pct(tech["utilization_pct"], 0) if tech.get("utilization_pct") is not None else "—",
        },
        # Hybrid only — Off-Grid has no grid bill to compare against, so this
        # stays None there (guarded in the template with {% if hybrid_savings %}).
        "hybrid_savings": {
            "old_bill_crc":  _crc(hybrid_savings["old_bill_crc"]),
            "new_bill_crc":  _crc(hybrid_savings["new_bill_crc"]),
            "savings_crc":   _crc(hybrid_savings["savings_crc"]),
            "savings_pct":   _pct(hybrid_savings["savings_pct"], 0),
        } if hybrid_savings else None,
        "cost_per_wp":            f"{data['cost_per_wp']:.2f}",
        "warranty_inverter_years": data.get("warranty_inverter_years" if es else "warranty_inverter_years_en", "5 años"),
        "warranty_battery_years":  data.get("warranty_battery_years" if es else "warranty_battery_years_en", "10 años"),
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


# ── wizard blob → data dict ──────────────────────────────────────────────────

def build_from_wizard_blob(
    blob: dict,
    proposal: dict,
    quote_str: str,
    version_date: str | None = None,
) -> dict:
    """Convert a saved version JSONB blob into the data dict expected by generate_pdf()."""
    from wizard.state import get_company_info, get_bank_info
    from datetime import date as _dt

    meta        = blob.get("meta", {})
    client_data = blob.get("client", {})
    site        = blob.get("site", {})
    utility     = blob.get("utility", {})
    consumption = blob.get("consumption", {})
    equipment   = blob.get("equipment", {})
    costs       = blob.get("costs", {})

    language    = meta.get("language", "es")
    panel       = equipment.get("panel", {})
    inverter    = equipment.get("inverter", {})
    system_type = proposal.get("system_type", "grid_zero")
    is_off_grid = system_type != "grid_zero"

    # The two wizards store their sizing result under different keys: Grid Zero
    # writes equipment.chosen_scenario, Off-Grid/Hybrid write equipment.array
    # (plus equipment.battery_bank). This function only ever read
    # chosen_scenario, so every Off-Grid PDF generated from the Cotizaciones
    # list came out with 0.00 kW / 0.0 m² / 0.00 kWh in DETALLES TÉCNICOS and
    # $0.00/Wp. The wizard's own Step 8 was unaffected — it builds its data
    # dict directly instead of going through here.
    chosen       = equipment.get("chosen_scenario", {}) or {}
    array        = equipment.get("array", {}) or {}
    battery_bank = equipment.get("battery_bank", {}) or {}

    if is_off_grid:
        panel_count = int(array.get("panel_count") or equipment.get("panel_count") or 0)
        system_kw   = float(array.get("array_kw") or 0)
    else:
        panel_count = int(chosen.get("total_panels") or 0)
        system_kw   = float(chosen.get("system_kw") or 0)

    # ── Cost items ────────────────────────────────────────────────────────────
    inv_qty    = 1
    cost_items = []
    for li in costs.get("line_items", []):
        qty     = li.get("qty")
        iva_pct = float(li.get("iva_pct") or 0)
        # The wizard already stores a computed `total` per line; prefer it.
        # Recomputing here read "unit_cost_usd", a key the wizard has never
        # written (it writes "unit_cost"), so every line total silently came
        # out $0.00 while the Total row — which comes from costs.total_usd,
        # not from summing these — stayed correct. That only affected PDFs
        # generated from the Cotizaciones list, since the wizard's own Step 8
        # builds its data dict directly rather than going through here.
        if li.get("total") is not None:
            total = round(float(li["total"]), 2)
        else:
            unit  = float(li.get("unit_cost") or li.get("unit_cost_usd") or 0)
            total = round((float(qty) if qty is not None else 1) * unit * (1 + iva_pct), 2)
        if li.get("item") == "Inversores" and qty:
            inv_qty = int(float(qty))
        cost_items.append({
            "item":     li.get("item", ""),
            "item_en":  li.get("item_en") or li.get("item", ""),
            "qty":      qty,
            "specs":    li.get("specs", ""),
            "specs_en": li.get("specs_en") or li.get("specs", ""),
            "total":    total,
        })

    total_usd    = float(costs.get("total_usd") or 0)
    subtotal_usd = float(costs.get("subtotal_usd") or total_usd)
    iva_usd      = float(costs.get("iva_usd") or 0)
    cost_per_wp = round(total_usd / (system_kw * 1000), 2) if system_kw else 0.0
    # Off-Grid's sizing step already stored the array area; only fall back to
    # deriving it from panel dimensions when it isn't there (Grid Zero).
    area_m2 = float(array.get("area_m2") or 0) or round(
        panel_count * float(panel.get("width_m") or 1.134) * float(panel.get("height_m") or 2.278), 1
    )
    if is_off_grid and equipment.get("inverter_qty"):
        inv_qty = int(float(equipment["inverter_qty"]))

    # ── Billing / financials (best-effort recompute) ──────────────────────────
    billing_avg = {
        "consumption_kwh": 0.0, "bill_crc": 0.0,
        "generation_kwh": 0.0, "new_consumption_kwh": 0.0,
        "new_bill_crc": 0.0, "savings_crc": 0.0,
    }
    benefits = {
        "savings_year1_usd": 0.0, "savings_25yr_usd": 0.0,
        "irr_pct": 0.0, "roi_years": 0.0,
        "avg_monthly_savings_usd": 0.0, "pct_savings": 0.0,
    }
    try:
        from calculations.sizing_grid_zero import size_system, compute_avg_billing
        from calculations.financials import calculate_irr, calculate_roi, calculate_25yr_savings
        from database.tariffs_db import get_tariff_tiers, list_tariff_types
        from utils.currency import get_exchange_rate

        xr             = get_exchange_rate()
        avg_kwh        = float(consumption.get("avg_kwh") or 0)
        pvgis_monthly  = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp", [])
        monthly_kwh    = [m["kwh"] for m in consumption.get("months_data", [])] or [avg_kwh] * 12
        tariff_type_id = utility.get("tariff_type_id")

        if pvgis_monthly and tariff_type_id and avg_kwh and panel_count:
            tiers       = get_tariff_tiers(tariff_type_id)
            tt_list     = list_tariff_types(utility.get("distributor_id", ""))
            tariff_type = next((t for t in tt_list if t["id"] == tariff_type_id), {})

            sizing = size_system(avg_kwh, pvgis_monthly, float(panel.get("wp") or 620), panel_count)
            avg_b  = compute_avg_billing(monthly_kwh, sizing["monthly_generation"], tariff_type, tiers, xr)

            sc = float(avg_b.get("savings_crc") or 0)
            billing_avg = {
                "consumption_kwh":     float(avg_b["consumption_kwh"]),
                "bill_crc":            float(avg_b["bill_crc"]),
                "generation_kwh":      float(sizing["avg_generation_kwh"]),
                "new_consumption_kwh": float(avg_b["new_consumption_kwh"]),
                "new_bill_crc":        float(avg_b["new_bill_crc"]),
                "savings_crc":         sc,
            }

            yr1_usd = round(sc * 12 / xr, 2) if xr else 0.0
            tc      = total_usd * xr
            benefits = {
                "savings_year1_usd":     yr1_usd,
                "savings_25yr_usd":      round(calculate_25yr_savings(sc * 12) / xr, 2) if xr else 0.0,
                "irr_pct":               calculate_irr(tc, sc * 12) if sc and tc else 0.0,
                "roi_years":             calculate_roi(tc, sc * 12) if sc and tc else 0.0,
                "avg_monthly_savings_usd": round(yr1_usd / 12, 2),
                "pct_savings":           float(avg_b.get("pct_savings") or 0),
            }
    except Exception:
        pass

    company = get_company_info()
    bank    = get_bank_info()
    inv_warranty = inverter.get("warranty_yr", 5)
    sys_labels   = {"grid_zero": "Grid Zero", "off_grid": "Off-Grid", "hybrid": "Híbrido"}

    return {
        "date":              version_date or _dt.today().strftime("%d/%m/%Y"),
        "quote_number":      quote_str,
        "client": {
            "name":     client_data.get("name") or proposal.get("client_name", ""),
            # site never carries an "address" key — wizard/common.py's site step
            # writes city/province — so this used to fall through to "" and the
            # UBICACIÓN row rendered blank on any proposal whose client record
            # had no address of its own. `or` (not .get(default)) throughout:
            # these keys routinely exist holding an empty string.
            "location": (client_data.get("address")
                         or site.get("address")
                         or _site_location(site)),
            "nise":     client_data.get("nise") or "N/A",
        },
        "system_type_label": sys_labels.get(proposal.get("system_type", "grid_zero"), "Grid Zero"),
        "intro_lines":       [blob.get("proposal_text", "")] if blob.get("proposal_text") else [],
        "billing_avg":       billing_avg,
        "benefits":          benefits,
        "benefits_notes_es": "No se considera la entrega de excedentes de energía a la red eléctrica.",
        "benefits_notes_en": "Excess energy delivered to the grid is not considered",
        "cost_items":        cost_items,
        "subtotal_usd":      subtotal_usd,
        "iva_usd":           iva_usd,
        "total_usd":         total_usd,
        "technical": {
            "system_kw":      system_kw,
            "area_m2":        area_m2,
            "panel_count":    panel_count,
            "inverter_count": inv_qty,
            # Off-Grid/Hybrid columns — read by _build_context_off_grid(), which
            # renders a different set of metrics than Grid Zero. Absent (and
            # unused) on a Grid Zero blob, where battery_bank/array are empty.
            "daily_generation_kwh": float(array.get("daily_generation_kwh") or 0),
            "battery_kwh":          float(battery_bank.get("total_kwh_installed") or 0),
            "discharge_pct":        float(battery_bank.get("discharge_pct") or 0),
            # None (not 0) when never simulated, so the template renders "—"
            # rather than claiming a real 0% utilization.
            "utilization_pct":      battery_bank.get("utilization_pct"),
            # Grid Zero's solar-utilization figure, stored by the Step 6
            # projection. None (not 0) when a draft never ran "Calcular MPPT",
            # so the template renders "—" instead of a fake 0%.
            "self_consumption_pct": (equipment.get("projection") or {}).get("self_consumption_pct"),
        },
        # Hybrid only — set by wizard/off_grid.py Step 6 when grid-connected
        # with a known tariff; None (and unused) for Off-Grid/Grid Zero.
        "hybrid_savings": equipment.get("hybrid_savings"),
        "cost_per_wp":               cost_per_wp,
        "warranty_inverter_years":   f"{inv_warranty} años",
        "warranty_inverter_years_en": f"{inv_warranty} years",
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
        "bank_local_lines":    bank["bank_local_lines"],
        "bank_intl_lines":     bank["bank_intl_lines"],
        "bank_local_lines_en": bank["bank_local_lines_en"],
        "bank_intl_lines_en":  bank["bank_intl_lines_en"],
        "company":       company,
        "validity_days": 15,
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
    # Hybrid shares the off_grid template file — same technical shape
    # (array + battery + discharge), just a different system_type_label.
    template_key = "grid_zero" if system_type == "grid_zero" else "off_grid"
    template = env.get_template(f"{template_key}_{language}.html")
    context = _build_context(data, language) if system_type == "grid_zero" else _build_context_off_grid(data, language)

    # Monthly-coverage chart. Built here rather than in each wizard so both
    # system types and both languages share one implementation, and so a
    # proposal without usable 12-month data simply renders no chart section
    # (monthly_coverage_svg returns "") instead of raising.
    from proposals.charts import monthly_coverage_svg

    _coverage = data.get("monthly_coverage") or {}
    context["coverage_chart_svg"] = monthly_coverage_svg(
        _coverage.get("generation"),
        _coverage.get("consumption"),
        language,
        # Grid Zero intentionally generates less than total consumption (it
        # covers daytime use only, the grid covers the rest), so months below
        # the line are normal there and must not be flagged. Off-Grid/Hybrid
        # have no grid to fall back on, so a shortfall is a real finding.
        flag_shortfall=(system_type != "grid_zero"),
        # Grid Zero has no battery — recharge_kwh stays None there and the
        # chart falls back to its original plain consumption bar.
        recharge_kwh=_coverage.get("recharge"),
    )

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
