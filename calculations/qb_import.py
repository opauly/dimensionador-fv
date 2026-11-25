"""QuickBooks Journal import — parsing and suggested classification (fase 25.2).

Pure module (no database): `parse_journal()` reads the rows of the Journal
export, `propose()` turns them into

* jobs  — one per invoice. Each becomes a completed historical project by
  default (Oscar, 2026-11-23: "un proyecto por trabajo facturado").
* items — one per money movement: each client payment (split across invoices
  when it pays more than one) and each expense line (with its share of the
  transaction's IVA, since IVA paid is a cost).

Every item carries a suggested kind (client_payment, project_expense,
company_expense, owner_draw), a project (job_key) when it has one, and a
confidence, so the review page can show the doubtful ones first.

Facts about the export this relies on (checked on the 2026-11-23 export):
one cash account, all USD; invoices have customer + Sales lines whose memo
describes the job; payments name the customer but not the invoice; expenses
never name a customer — the project only shows up in the memo text.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from datetime import date

CASH = "Cash and cash equivalents"
AR = "Accounts Receivable (A/R)"
IVA = "IVA Control"
SALES = "Sales"

# Words that say nothing about which job a memo belongs to.
STOPWORDS = set("""
proyecto proyectos fv sistema solar extra extras de del la las el los y en con para por a al
pago pagos adelanto final parte pt mantenimiento mantenimientos 2019 2020 2021 2022 2023 2024 2025
2026 2027 kw v2 nuevo nueva saldo pendiente varios casa materiales equipo instalacion electrica
electrico remodelacion arreglos mejoras internas cambio sistemas medidor medidores
enero febrero marzo abril mayo junio julio agosto setiembre septiembre octubre noviembre diciembre
usd crc mes
""".split())

# Owner draws: personal card payments, loans, "ayudas", cash for trips…
OWNER_DRAW_WORDS = (
    "visa", "mastercard", "promerica", "tarjeta", "cuota", "ayuda", "ganancia", "prestamo",
    "efectivo", "europa", "las vegas", "cirugia", "bn usd", "bn crc", "personal", "personales", "retiro",
)

RUBRO_WORDS = [
    ("mano_de_obra", ("adelanto", "pago final", "mano de obra", "steven", "cuadrilla", "planilla",
                      "servicios profesionales", "jornal")),
    ("viaticos", ("gasolina", "combustible", "hospedaje", "hotel", "viatico", "peaje", "comida",
                  "almuerzo", "transporte", "flete", "uber", "bus")),
    ("banco", ("comision", "onvo", "transferencia", "sinpe")),
    ("equipo", ("proforma", "oferta", "panel", "inversor", "bateria", "fronius", "pylontech", "victron",
                "enphase", "microinversor", "egauge", "hcg", "cotizacion", "orden", "letra de cambio",
                "estructura", "calentador", "tanque")),
    ("materiales", ("ditesa", "protel", "alco", "maz", "electrocaribe", "ferreteria", "epa", "material",
                    "cable", "breaker", "poste", "tubo")),
]

# QuickBooks account → app category name (company expenses).
ACCOUNT_CATEGORY = {
    "Office expenses": "Oficina",
    "Income tax expense": "Impuestos",
    "Travel expenses - general and admin expenses": "Vehículo y combustible",
    "Shipping and delivery expense": "Otros",
    "Other general and administrative expenses": "Otros",
    "Other selling expenses": "Marketing",
    "Long-Term Investments": "Otros",
}
CATEGORY_WORDS = [
    ("Comisiones bancarias", ("comision", "onvo")),
    ("Software y suscripciones", ("software", "gsuite", "g suite", "licencia", "suscripcion", "google", "microsoft", "adobe",
                                  "autocad", "quickbooks", "pvsyst", "helioscope", "dominio", "hosting")),
    ("Teléfono e internet", ("telefono", "internet", "kolbi", "claro", "liberty", "celular")),
    ("Vehículo y combustible", ("gasolina", "combustible", "kia", "marchamo", "riteve", "taller", "llantas")),
    ("Seguros", ("ins ", "poliza", "seguro")),
    ("Contador y legal", ("contador", "contable", "abogado", "notario", "legal")),
    ("Impuestos", ("impuesto", "iva", "hacienda", "renta", "patente")),
    ("Capacitación", ("curso", "capacitacion", "certificacion", "seminario")),
    ("Herramientas", ("herramienta", "taladro", "multimetro", "escalera")),
    ("Marketing", ("marketing", "publicidad", "facebook", "instagram", "pagina web", "logo")),
]


# ── Text helpers ─────────────────────────────────────────────────────────
def norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def tokens(text) -> set[str]:
    return {t for t in norm(text).split() if len(t) > 2 and t not in STOPWORDS and not t.isdigit()}


def _iso(raw) -> str:
    if isinstance(raw, (date,)):
        return raw.isoformat()[:10]
    m, d, y = str(raw).strip().split("/")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


# ── 1. Parse ─────────────────────────────────────────────────────────────
def parse_journal(rows) -> list[dict]:
    """Rows of the Journal sheet (tuples) → transactions with their lines.

    Finds the header row by its column names, so a leading empty column or a
    few extra title rows don't matter."""
    rows = list(rows)
    hdr_i, cols = None, {}
    for i, r in enumerate(rows[:30]):
        names = [str(c or "").strip().lower() for c in r]
        if "date" in names and "account" in names:
            hdr_i = i
            cols = {n: j for j, n in enumerate(names) if n}
            break
    if hdr_i is None:
        raise ValueError("No encontré los encabezados del Journal (Date, Account, Debit, Credit…).")

    def col(r, name):
        j = cols.get(name)
        return r[j] if j is not None and j < len(r) else None

    txs, cur = [], None
    for r in rows[hdr_i + 1:]:
        d, ty, acct = col(r, "date"), col(r, "transaction type"), col(r, "account")
        if d and ty:
            cur = {"date": _iso(d), "type": str(ty).strip(), "no": col(r, "no."),
                   "name": (col(r, "name") or "") and str(col(r, "name")).strip(),
                   "memo": col(r, "memo/description"), "lines": []}
            if cur["no"] is not None and isinstance(cur["no"], float) and cur["no"].is_integer():
                cur["no"] = int(cur["no"])
            txs.append(cur)
        if cur is not None and acct:
            cur["lines"].append({"acct": str(acct).strip(), "memo": col(r, "memo/description"),
                                 "name": col(r, "name"),
                                 "dr": _num(col(r, "debit")), "cr": _num(col(r, "credit"))})
    return txs


def journal_totals(txs: list[dict]) -> dict:
    """QuickBooks' own cash figures, for the cuadre."""
    cash_in = sum(l["dr"] for t in txs for l in t["lines"] if l["acct"] == CASH)
    cash_out = sum(l["cr"] for t in txs for l in t["lines"] if l["acct"] == CASH)
    invoiced = sum(l["dr"] - l["cr"] for t in txs if t["type"] == "Invoice" for l in t["lines"] if l["acct"] == AR)
    return {"cash_in": round(cash_in, 2), "cash_out": round(cash_out, 2),
            "net": round(cash_in - cash_out, 2), "invoiced": round(invoiced, 2),
            "transactions": len(txs),
            "first_date": min((t["date"] for t in txs), default=None),
            "last_date": max((t["date"] for t in txs), default=None)}


def _ref(*parts) -> str:
    return "qb:" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


# ── 2. Jobs (one per invoice) ────────────────────────────────────────────
def build_jobs(txs: list[dict]) -> list[dict]:
    jobs = []
    seen = defaultdict(int)
    for t in txs:
        if t["type"] != "Invoice":
            continue
        total = sum(l["dr"] - l["cr"] for l in t["lines"] if l["acct"] == AR)
        iva = sum(l["cr"] - l["dr"] for l in t["lines"] if l["acct"] == IVA)
        desc = " | ".join(str(l["memo"]).strip() for l in t["lines"] if l["acct"] == SALES and l["memo"])
        base = f"{t['date']}|{t['no']}|{t['name']}|{round(total, 2)}"
        seen[base] += 1
        jobs.append({
            "job_key": _ref("inv", base, seen[base]),
            "invoice_no": str(t["no"]) if t["no"] is not None else None,
            "invoice_date": t["date"], "customer": t["name"] or "Sin cliente",
            "description": desc, "total_usd": round(total, 2), "iva_usd": round(max(iva, 0), 2),
            "action": "project", "existing_project_id": None,
            "title": desc.split(" | ")[0][:80] if desc else (f"Factura {t['no']}" if t["no"] else "Trabajo"),
        })
    return jobs


def link_existing(jobs: list[dict], projects: list[dict]) -> None:
    """Mark the invoice of a project that already lives in the app (same
    contract total, and the app client's name in the invoice text or customer)
    so its money is not imported twice."""
    for p in projects:
        name = norm(p.get("client_name"))
        total = round(_num(p.get("contract_usd")), 2)
        for j in jobs:
            text = norm(f"{j['customer']} {j['description']}")
            if abs(j["total_usd"] - total) < 0.01 and name and name in text:
                j["action"], j["existing_project_id"] = "existing", p["id"]


# ── 3. Payments → invoices (oldest invoice first) ────────────────────────
def allocate_payments(txs: list[dict], jobs: list[dict], app_payments: list[dict] | None = None) -> list[dict]:
    """Split each customer's payments across that customer's invoices, oldest
    first. Payments already recorded in the app for a linked project (same
    amount, within 5 days) are taken out first and marked skip."""
    by_cust = defaultdict(list)
    for j in sorted(jobs, key=lambda j: (j["invoice_date"], j["invoice_no"] or "")):
        if j["action"] != "existing":
            by_cust[j["customer"]].append({"job": j, "open": j["total_usd"]})
    existing_jobs = {j["existing_project_id"]: j for j in jobs if j["action"] == "existing"}
    app_left = [dict(p) for p in (app_payments or []) if p.get("project_id") in existing_jobs and p.get("paid")]

    items, seen = [], defaultdict(int)
    payments = sorted((t for t in txs if t["type"] == "Payment"), key=lambda t: t["date"])
    for t in payments:
        amount = round(sum(l["dr"] - l["cr"] for l in t["lines"] if l["acct"] == CASH), 2)
        if abs(amount) < 0.005:
            continue
        base = f"pay|{t['date']}|{t['name']}|{amount}"
        seen[base] += 1
        common = {"tx_date": t["date"], "qb_type": "Payment", "qb_account": CASH, "payee": t["name"],
                  "memo": (t["memo"] or "").strip() or None, "rubro": None, "category_id": None}

        match = next((p for p in app_left if abs(_num(p["amount_usd"]) - amount) < 0.01
                      and p.get("paid_date") and abs(_days(p["paid_date"], t["date"])) <= 5
                      and existing_jobs[p["project_id"]]["customer"] == t["name"]), None)
        if match:
            app_left.remove(match)
            items.append({**common, "external_ref": _ref(base, seen[base]), "amount_usd": amount,
                          "kind": "skip", "job_key": existing_jobs[match["project_id"]]["job_key"],
                          "confidence": "alta", "reason": "Ya está registrado en el proyecto de la app"})
            continue

        left, part = amount, 0
        queue = by_cust.get(t["name"], [])
        for slot in queue:
            if left < 0.005:
                break
            if slot["open"] < 0.005:
                continue
            take = round(min(left, slot["open"]), 2)
            slot["open"] = round(slot["open"] - take, 2)
            left = round(left - take, 2)
            part += 1
            items.append({**common, "external_ref": _ref(base, seen[base], part), "amount_usd": take,
                          "kind": "client_payment", "job_key": slot["job"]["job_key"], "confidence": "alta",
                          "reason": "Factura más antigua pendiente del cliente"
                                    + (" (pago repartido)" if part > 1 or left > 0.005 else "")})
        if left > 0.005:
            # Paid more than was invoiced: keep it on the customer's last invoice.
            target = queue[-1]["job"]["job_key"] if queue else None
            part += 1
            items.append({**common, "external_ref": _ref(base, seen[base], part), "amount_usd": left,
                          "kind": "client_payment" if target else "other_income", "job_key": target,
                          "confidence": "baja",
                          "reason": "Pagó más de lo facturado; se suma al último trabajo" if target
                                    else "Pago sin factura del cliente"})
    return items


# ── 4. Expenses ──────────────────────────────────────────────────────────
class JobMatcher:
    """Scores each invoice against an expense memo: distinctive words of the
    customer name and invoice description, weighted by how rare they are,
    plus closeness in time."""

    def __init__(self, jobs: list[dict], projects: list[dict] | None = None):
        self.jobs = jobs
        self.words = {j["job_key"]: tokens(f"{j['customer']} {j['description']}") for j in jobs}
        self.cust = {j["job_key"]: norm(j["customer"]) for j in jobs}
        df = defaultdict(int)
        for ws in self.words.values():
            for w in ws:
                df[w] += 1
        self.weight = {w: 1.0 / n for w, n in df.items()}
        # names of projects that live in the app → their linked job
        self.app_names = []
        for p in projects or []:
            j = next((j for j in jobs if j.get("existing_project_id") == p["id"]), None)
            if j and norm(p.get("client_name")):
                self.app_names.append((norm(p["client_name"]), j))

    def match(self, text: str, when: str):
        t = norm(text)
        for name, j in self.app_names:
            if name in t:
                if t.count("proyecto") >= 2:  # "Proyecto FV A … Proyecto FV B": shared invoice line
                    return j, "baja", (f"El memo nombra a {name.title()} y también a otro trabajo; "
                                       "revise si hay que dividirlo")
                return j, "alta", f"El memo nombra a {name.title()}"
        tw = tokens(text)
        best, best_score = None, 0.0
        for j in self.jobs:
            shared = tw & self.words[j["job_key"]]
            if not shared:
                continue
            score = sum(self.weight[w] for w in shared)
            if self.cust[j["job_key"]] and self.cust[j["job_key"]] in t:
                score += 2.0
            gap = _days(when, j["invoice_date"])
            # costs usually fall from a few months before the invoice to a few after
            if -240 <= gap <= 150:
                score += 0.5
            score -= min(abs(gap), 1500) / 1500.0
            if score > best_score:
                best, best_score = j, score
        if not best or best_score < 0.35:
            return None, "ninguna", ""
        conf = "alta" if best_score >= 1.2 else "baja"
        return best, conf, "Memo parecido a: " + (best["customer"] + " · " + (best["title"] or "")).strip(" ·")


def _rubro(text: str, payee: str) -> str:
    t = f" {norm(text)} {norm(payee)} "
    for rubro, words in RUBRO_WORDS:
        if any(f" {w}" in t for w in words):
            return rubro
    return "extras"


def _company_category(text: str, account: str, categories: dict[str, str]) -> str | None:
    t = f" {norm(text)} "
    for name, words in CATEGORY_WORDS:
        if any(f" {w}" in t for w in words):
            return categories.get(name)
    return categories.get(ACCOUNT_CATEGORY.get(account, "Otros")) or categories.get("Otros")


def classify_expenses(txs: list[dict], jobs: list[dict], categories: list[dict],
                      projects: list[dict] | None = None) -> list[dict]:
    """One item per expense line; IVA lines are spread over the other lines in
    proportion to their amount (IVA paid is a cost)."""
    matcher = JobMatcher([j for j in jobs if j["action"] != "skip"], projects)
    cat_by = {c["name"]: c["id"] for c in categories if c["kind"] == "company_expense"}
    draw_cat = next((c["id"] for c in categories if c["kind"] == "owner_draw"
                     and c["name"] == "Retiro personal"), None)
    card_cat = next((c["id"] for c in categories if c["kind"] == "owner_draw"
                     and c["name"] == "Pago de tarjetas"), draw_cat)

    items, seen = [], defaultdict(int)
    for t in txs:
        if t["type"] in ("Invoice", "Payment"):
            continue
        cash = round(sum(l["cr"] - l["dr"] for l in t["lines"] if l["acct"] == CASH), 2)
        lines = [l for l in t["lines"] if l["acct"] not in (CASH, IVA)]
        iva = sum(l["dr"] - l["cr"] for l in t["lines"] if l["acct"] == IVA)
        if not lines:  # an IVA-only payment (e.g. paying Hacienda)
            lines = [{"acct": IVA, "memo": t["memo"] or "Pago de IVA", "dr": iva, "cr": 0}]
            iva = 0
        base_sum = sum(l["dr"] - l["cr"] for l in lines) or 1.0
        amounts = [round((l["dr"] - l["cr"]) * (1 + iva / base_sum), 2) for l in lines]
        if amounts:  # rounding remainder onto the biggest line, so the transaction adds up to the cash paid
            k = max(range(len(amounts)), key=lambda i: abs(amounts[i]))
            amounts[k] = round(amounts[k] + (cash - sum(amounts)), 2)

        for idx, (l, amount) in enumerate(zip(lines, amounts)):
            if abs(amount) < 0.005:
                continue
            memo = " · ".join(x for x in (str(t["memo"] or "").strip(), str(l["memo"] or "").strip()) if x)
            if str(t["memo"] or "").strip() == str(l["memo"] or "").strip():
                memo = str(l["memo"] or "").strip()
            text = f"{memo} {t['name']}"
            base = f"exp|{t['date']}|{t['type']}|{t['name']}|{cash}|{idx}|{l['acct']}|{amount}"
            seen[base] += 1
            item = {"external_ref": _ref(base, seen[base]), "tx_date": t["date"], "qb_type": t["type"],
                    "qb_account": l["acct"], "payee": t["name"], "memo": memo or None,
                    "amount_usd": amount, "job_key": None, "rubro": None, "category_id": None}
            nt = f" {norm(text)} "
            is_draw = any(f" {w} " in nt for w in OWNER_DRAW_WORDS)
            job, conf, why = matcher.match(text, t["date"])

            if is_draw and not (job and conf == "alta" and "proyecto" in nt):
                cards = any(w in nt for w in ("visa", "mastercard", "promerica", "tarjeta", "bn usd", "bn crc"))
                item.update(kind="owner_draw", category_id=card_cat if cards else draw_cat,
                            confidence="alta" if norm(t["name"]) == "oscar pauly" else "baja",
                            reason="Pago de tarjeta / gasto personal" if cards else "Parece retiro personal")
            elif job:
                if job["action"] == "existing":
                    item.update(kind="skip", job_key=job["job_key"], confidence=conf,
                                reason="Proyecto que ya está en la app — " + why)
                else:
                    item.update(kind="project_expense", job_key=job["job_key"], rubro=_rubro(text, t["name"]),
                                confidence=conf, reason=why)
            elif l["acct"] == "Cost of sales":
                item.update(kind="project_expense", rubro=_rubro(text, t["name"]), confidence="ninguna",
                            reason="Costo de ventas sin proyecto reconocible")
            else:
                item.update(kind="company_expense", category_id=_company_category(text, l["acct"], cat_by),
                            confidence="alta" if l["acct"] in ACCOUNT_CATEGORY or l["acct"] == IVA else "baja",
                            reason=f"Cuenta de QuickBooks: {l['acct']}")
            items.append(item)
    return items


def propose(txs, categories, projects=None, app_payments=None) -> dict:
    jobs = build_jobs(txs)
    link_existing(jobs, projects or [])
    items = allocate_payments(txs, jobs, app_payments) + classify_expenses(txs, jobs, categories, projects)
    return {"jobs": jobs, "items": items, "totals": journal_totals(txs)}


# ── 5. Cuadre ────────────────────────────────────────────────────────────
def reconcile(items: list[dict], totals: dict) -> dict:
    """Staged money vs QuickBooks' cash. Every peso is either imported or
    explicitly skipped, so in + skipped must equal QuickBooks."""
    # Movements added from the bank statement (qb_type "Banco") were never in
    # QuickBooks, so they are reported apart and kept out of the QB comparison.
    qb_items = [i for i in items if i["qb_type"] != "Banco"]
    money_in = sum(i["amount_usd"] for i in qb_items if i["qb_type"] == "Payment")
    money_out = sum(i["amount_usd"] for i in qb_items if i["qb_type"] != "Payment")
    skipped_in = sum(i["amount_usd"] for i in qb_items if i["qb_type"] == "Payment" and i["kind"] == "skip")
    skipped_out = sum(i["amount_usd"] for i in qb_items if i["qb_type"] != "Payment" and i["kind"] == "skip")
    bank = [i for i in items if i["qb_type"] == "Banco"]
    return {
        "qb_in": totals.get("cash_in", 0), "qb_out": totals.get("cash_out", 0),
        "staged_in": round(money_in, 2), "staged_out": round(money_out, 2),
        "skipped_in": round(skipped_in, 2), "skipped_out": round(skipped_out, 2),
        "bank_count": len(bank), "bank_out": round(sum(i["amount_usd"] for i in bank), 2),
        "ok": abs(money_in - totals.get("cash_in", 0)) < 0.05 and abs(money_out - totals.get("cash_out", 0)) < 0.05,
    }
