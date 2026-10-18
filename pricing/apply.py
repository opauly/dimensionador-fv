"""Apply a reviewed proforma import to the catalog / service defaults.

Pure data in, DB writes out; the Flask layer in `webapp/blueprints/pricing.py`
does the form parsing. Every write stamps `price_updated_at` (the proforma's own
date — the date the price is valid for, not the day it was typed in) and
`price_source`, and the whole import is logged in `price_imports`.
"""
from __future__ import annotations

import re
import uuid

from pricing.matching import SERVICE_ACCESSORIES, SERVICE_MOUNTING, SKIP, TABLE_LABELS

CATALOG_TABLES = tuple(TABLE_LABELS)
MOUNTING_ITEM = "Estructura de montaje"
ACCESSORIES_ITEM = "Accesorios"
BUCKET = "solar-tool"


def load_catalog() -> dict[str, list[dict]]:
    from database.supabase_client import get_client

    c = get_client()
    out = {}
    for t in CATALOG_TABLES:
        cols = "id, brand, model, cost_usd, cost_iva_rate, price_updated_at, price_source"
        if t == "panels":
            cols += ", wp"
        out[t] = c.table(t).select(cols).order("brand").execute().data or []
    return out


def load_services() -> dict[str, dict]:
    from database.supabase_client import get_client

    rows = (get_client().table("service_defaults")
            .select("id, item, unit_cost_usd, cost_per_wp, iva_pct, price_updated_at, price_source")
            .execute().data or [])
    return {r["item"]: r for r in rows}


def target_options(catalog: dict[str, list[dict]]) -> list[tuple[str, str]]:
    """[(value, label)] for the per-line <select>."""
    opts: list[tuple[str, str]] = [(SKIP, "— No importar —"),
                                   (SERVICE_MOUNTING, "Estructura de montaje ($/Wp)"),
                                   (SERVICE_ACCESSORIES, "Accesorios (por sistema)")]
    for t, rows in catalog.items():
        for r in rows:
            opts.append((f"{t}:{r['id']}", f"{TABLE_LABELS[t]} · {r['brand']} {r['model']}"))
    return opts


def stage_pdf(pdf_bytes: bytes, filename: str, doc_date: str | None) -> str | None:
    """Upload the original PDF so the import has an audit trail. Best effort:
    a storage failure must not block reviewing the prices."""
    try:
        from database.supabase_client import get_client

        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename or "proforma.pdf")
        folder = (doc_date or "sin-fecha")[:7]
        path = f"proformas/{folder}/{uuid.uuid4().hex[:8]}-{safe}"
        get_client().storage.from_(BUCKET).upload(
            path, pdf_bytes, {"content-type": "application/pdf", "upsert": "true"})
        return path
    except Exception:
        return None


def discount_factor(totals: dict) -> float:
    sub, disc = totals.get("subtotal"), totals.get("descuento")
    if sub and disc and 0 < disc < sub:
        return 1.0 - disc / sub
    return 1.0


def _weighted_iva(lines: list[dict]) -> float:
    taxed = sum(l["total"] for l in lines if (l.get("iva_rate") or 0) > 0)
    all_ = sum(l["total"] for l in lines)
    return 0.13 if all_ and taxed / all_ > 0.5 else 0.0


def apply_import(*, supplier: str, doc_number: str, doc_date: str | None, filename: str,
                 storage_path: str | None, lines: list[dict], kwp: float | None,
                 apply_discount: bool, totals: dict) -> dict:
    """`lines`: [{description, qty, unit_usd, total_usd, iva_rate, target}].
    Returns {"changes": [...], "errors": [...]}; nothing is written when there
    are errors (mounting lines without a kWp to divide by)."""
    from database.supabase_client import get_client

    c = get_client()
    factor = discount_factor(totals) if apply_discount else 1.0
    source = f"{supplier} proforma {doc_number}".strip() if doc_number else supplier
    stamp = doc_date or None
    changes: list[dict] = []
    errors: list[str] = []

    catalog = load_catalog()
    by_id = {(t, r["id"]): r for t, rows in catalog.items() for r in rows}
    services = load_services()

    mounting = [{"total": (l["total_usd"] or 0) * factor, "iva_rate": l.get("iva_rate")}
                for l in lines if l["target"] == SERVICE_MOUNTING]
    accessories = [{"total": (l["total_usd"] or 0) * factor, "iva_rate": l.get("iva_rate")}
                   for l in lines if l["target"] == SERVICE_ACCESSORIES]

    # kWp: explicit input wins; otherwise the panels on this very proforma.
    if not kwp:
        kwp = sum((l["qty"] or 0) * float(by_id[("panels", l["target"].split(":", 1)[1])].get("wp") or 0)
                  for l in lines if l["target"].startswith("panels:")
                  and ("panels", l["target"].split(":", 1)[1]) in by_id) / 1000.0
    if mounting and not kwp:
        errors.append("Las líneas de estructura necesitan los kWp del proyecto para calcular el costo por Wp.")
    if mounting and MOUNTING_ITEM not in services:
        errors.append(f"No existe el servicio «{MOUNTING_ITEM}» en Admin → Servicios.")
    if accessories and ACCESSORIES_ITEM not in services:
        errors.append(f"No existe el servicio «{ACCESSORIES_ITEM}» en Admin → Servicios.")
    if errors:
        return {"changes": [], "errors": errors}

    for l in lines:
        t = l["target"]
        if t in (SKIP, SERVICE_MOUNTING, SERVICE_ACCESSORIES) or ":" not in t:
            continue
        table, rid = t.split(":", 1)
        old = by_id.get((table, rid))
        if old is None:
            continue
        new_cost = round((l["unit_usd"] or 0) * factor, 2)
        new_iva = float(l.get("iva_rate") or 0)
        c.table(table).update({
            "cost_usd": new_cost, "cost_iva_rate": new_iva,
            "price_updated_at": stamp, "price_source": source,
        }).eq("id", rid).execute()
        changes.append({"label": f"{old['brand']} {old['model']}", "old": old.get("cost_usd"),
                        "new": new_cost, "iva": new_iva})

    if mounting:
        rate = round(sum(m["total"] for m in mounting) / (kwp * 1000.0), 6)
        row = services[MOUNTING_ITEM]
        iva = _weighted_iva(mounting)
        c.table("service_defaults").update({
            "cost_per_wp": rate, "iva_pct": iva, "price_updated_at": stamp,
            "price_source": f"{source} ({kwp:.2f} kWp)",
        }).eq("id", row["id"]).execute()
        changes.append({"label": f"{MOUNTING_ITEM} ($/Wp)", "old": row.get("cost_per_wp"),
                        "new": rate, "iva": iva})
    if accessories:
        total = round(sum(a["total"] for a in accessories), 2)
        row = services[ACCESSORIES_ITEM]
        iva = _weighted_iva(accessories)
        c.table("service_defaults").update({
            "unit_cost_usd": total, "iva_pct": iva, "price_updated_at": stamp, "price_source": source,
        }).eq("id", row["id"]).execute()
        changes.append({"label": f"{ACCESSORIES_ITEM} (por sistema)", "old": row.get("unit_cost_usd"),
                        "new": total, "iva": iva})

    c.table("price_imports").insert({
        "supplier": supplier, "doc_number": doc_number, "doc_date": stamp, "filename": filename,
        "storage_path": storage_path, "kwp": kwp or None, "discount_applied": bool(apply_discount and factor < 1),
        "lines": lines, "summary": {"changes": changes, "discount_factor": round(factor, 6)},
    }).execute()
    return {"changes": changes, "errors": []}
