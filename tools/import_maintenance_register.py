"""
One-time historical import — Registro de mantenimientos FV.xlsx -> maintenance_visits
+ site_credentials (Phase 10).

DRY RUN BY DEFAULT. Prints exactly what it would write and why; writes nothing until
you pass --apply (visits) and/or --apply-credentials (credentials) separately — no
blind import of plaintext WiFi/portal passwords or financial history, per PHASES.md's
own instruction for this step.

Column layout of the "Proyectos FV" sheet, confirmed by direct inspection (2026-09-07),
not assumed from PHASES.md's description:
  A Cliente, B Proyecto, C Ubicación, D Monitoreo, E Credenciales, F Potencia,
  G Paneles, H Inversores, I Baterías, J Fecha instalación,
  K/L/M/N = 2021/2022/2023/2024, each a single "Fecha" (visit happened, no cost
    tracked those years),
  O/P = 2025 Monto/Fecha (a real visit, cost sometimes present),
  Q/R/S/T = 2026 block: Q=Monto, R="12 meses" (a computed next-due date — last visit +
    interval, not itself a visit), S=Realizado (Yes/No, has the 2026 cycle happened),
    T=Fecha (when it happened).

For a handful of rows (Karen Montealegre (Guarda), Lori Pickett) T falls months before
R rather than shortly after it — flagged and confirmed with Oscar (2026-09-07) as real:
S='Yes' + T is the actual completed-visit date regardless of how it compares to R, no
per-row exception needed. R itself is never imported as a visit — only Q (amount, if
present) + T (date) when S='Yes'.

**A real bug, found 2026-09-08 after the first import already ran**: 12 of the 23 rows
have their own `Fecha instalación` (col J) duplicated verbatim into one of the yearly
Fecha columns (K-P) — not a real maintenance visit, just the installation being entered
into that year's slot. Confirmed systematic, not a coincidence: checked every row for
`year_fecha == fecha_instalacion` and found it in exactly the rows where the "visit" had
no amount and no other real visit nearby. `_read_rows()` now skips any yearly Fecha that
exactly equals `Fecha instalación` for that same row — never imported as a visit. The 12
already-written fake visits from the first import were deleted by hand (see git history
for the one-off cleanup); this fix only prevents it from recurring, e.g. after a future
xlsx refresh.

Site mapping: the 9 sites moved into vrm.sites by an unrelated duplicate-site
consolidation (Phase 19) have display names and site_id slugs that no longer match the
xlsx's "Proyecto" text at all (e.g. xlsx "Roberto Villalobos" -> live site "Rancho
DuliLa" / roberto-villalobos-rancho-dulila). Matched by hand against a live query
(2026-09-07), not fuzzy-matched at runtime — a financial import is the wrong place to
guess.

Lori Pickett was mapped after her client_id gap (noted in PHASES.md since 2026-07-18)
was closed 2026-09-08: created as a real `public.clients` row, linked to all 6 of her
site rows (3 monitoring.sites + 3 vrm.sites), and those 6 auto-seeded properties merged
into one ("Lori Pickett - Vista Atenas"). Mapped to one of her monitoring.sites rows
below — any of her 6 would resolve to the same merged property_id.

Usage:
    python -m tools.import_maintenance_register                    # dry run, prints everything
    python -m tools.import_maintenance_register --apply             # writes clean visits (2021-2025)
    python -m tools.import_maintenance_register --apply-credentials # writes the 4 real credential rows
"""
from __future__ import annotations

import argparse
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()

import openpyxl  # noqa: E402

from database.site_properties_db import (  # noqa: E402
    add_visit, list_all_sites_for_maintenance, list_visits, save_credentials,
)

XLSX_PATH = "/Users/oscarpauly/Downloads/Registro de mantenimientos FV.xlsx"
SHEET_NAME = "Proyectos FV"

# xlsx "Proyecto" -> (site_id, schema_name). See module docstring for why this is a
# hand-built mapping, not a runtime name match.
PROYECTO_TO_SITE: dict[str, tuple[str, str]] = {
    "Bryan Gutiérrez":              ("bryan-gutierrez", "monitoring"),
    "Fundación Rahab":              ("fundacion-rahab", "monitoring"),
    "Manuel Mayorga":               ("manuel-mayorga", "monitoring"),
    "Karen Montealegre":            ("karen-montealegre-proyecto-km-ukiyo", "vrm"),
    "Karen Montealegre (Guarda)":   ("karen-montealegre-proyecto-km-ukiyo-guarda", "vrm"),
    "Karen Montealegre (Portón)":   ("karen-montealegre-porton", "vrm"),
    "Hugo Aguilar":                 ("hugo-aguilar", "monitoring"),
    "Apartamento papás KA":         ("apartamento-papas-ka", "monitoring"),
    "Bernal Espinoza":              ("bernal-espinoza", "monitoring"),
    "Kattia Álvarez":               ("kattia-alvarez", "monitoring"),
    "Karol Álvarez (Neily)":        ("karol-alvarez-neily", "monitoring"),
    "Karol Álvarez (Belén)":        ("karol-alvarez-belen", "monitoring"),
    "Asoamazon":                    ("asoamazon", "monitoring"),
    "Hacienda Zurquí":              ("hacienda-zurqui", "monitoring"),
    "The Rainforest Lab":           ("the-rainforest-lab", "monitoring"),
    "Roberto Villalobos":           ("roberto-villalobos-rancho-dulila", "vrm"),
    "Rebeca Ruiz (Casita)":         ("rebeca-ruiz-el-encino-casita", "vrm"),
    "Rebeca Ruiz (Apartamento)":    ("rebeca-ruiz-el-encino-apartamento", "vrm"),
    "Rebeca Ruiz (Casona)":         ("rebeca-ruiz-el-encino-casona", "vrm"),
    "Rebeca Ruiz (Cabaña)":         ("rebeca-ruiz-el-encino-cabana", "vrm"),
    "Rebeca Ruiz (Portón cabaña)":  ("rebeca-ruiz-el-encino-porton-cabana", "vrm"),
    "Isaac Cerdas":                 ("isaac-cerdas", "monitoring"),
    # Her 3 monitoring.sites rows are excluded entirely (database/site_properties_db.py
    # :_EXCLUDED_MONITORING_SITE_IDS) — mapped to one of her 3 real vrm.sites rows
    # instead; any of the 3 resolves to the same merged property_id.
    "Lori Pickett":                 ("vista-atenas-vista-atenas-lp-m1-houses", "vrm"),
}

# (xlsx column index, calendar year) for the unambiguous single-Fecha years.
_SIMPLE_YEAR_COLS = [(10, 2021), (11, 2022), (12, 2023), (13, 2024)]
# 2025: Monto at 14, Fecha at 15.
_YEAR_2025_COLS = (14, 15)
# 2026 block: Monto=16, due-date=17 (not a visit), Realizado=18, Fecha=19.
_YEAR_2026_BLOCK = (16, 17, 18, 19)


def _to_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def _read_rows() -> list[dict]:
    wb = openpyxl.load_workbook(XLSX_PATH, data_only=True)
    ws = wb[SHEET_NAME]
    rows = []
    for r in ws.iter_rows(min_row=3, values_only=True):
        if not r[0] and not r[1]:
            continue
        fecha_instalacion = _to_date(r[9])
        monto_2026, _due_2026, realizado_2026, fecha_2026 = (
            r[_YEAR_2026_BLOCK[0]], _to_date(r[_YEAR_2026_BLOCK[1]]),
            r[_YEAR_2026_BLOCK[2]], _to_date(r[_YEAR_2026_BLOCK[3]]),
        )
        visits = [
            (year, _to_date(r[col]), None) for col, year in _SIMPLE_YEAR_COLS if r[col]
        ]
        if r[_YEAR_2025_COLS[1]]:
            visits.append((2025, _to_date(r[_YEAR_2025_COLS[1]]), r[_YEAR_2025_COLS[0]]))
        if realizado_2026 == "Yes" and fecha_2026:
            visits.append((2026, fecha_2026, monto_2026))

        # Drop any "visit" that's actually just the installation date duplicated into
        # a yearly Fecha column, not a real maintenance visit (see module docstring).
        visits = [v for v in visits if v[1] != fecha_instalacion]

        rows.append({
            "cliente": r[0], "proyecto": r[1], "ubicacion": r[2],
            "credenciales": r[4], "visits": visits,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write the 2021-2025 visits (dry run otherwise).")
    parser.add_argument("--apply-credentials", action="store_true", help="Write the real credential rows found.")
    args = parser.parse_args()

    rows = _read_rows()
    sites_by_key = {(s["site_id"], s["schema_name"]): s for s in list_all_sites_for_maintenance()}

    print(f"Read {len(rows)} rows from {XLSX_PATH}\n")

    visits_written = visits_skipped_existing = visits_skipped_no_property = 0
    creds_written = 0
    unmapped = []

    for row in rows:
        proyecto = row["proyecto"]
        mapping = PROYECTO_TO_SITE.get(proyecto)
        if not mapping:
            unmapped.append(proyecto)
            continue

        site_id, schema_name = mapping
        site = sites_by_key.get((site_id, schema_name))
        if not site:
            print(f"⚠️  {proyecto}: mapped to {schema_name}.{site_id}, but that site no longer exists — skipping.")
            continue

        property_id = site.get("property_id")
        print(f"— {proyecto} ({schema_name}.{site_id})")
        if not property_id:
            print("   ⚠️  not linked to a property yet — run 'Configurar propiedades' first, skipping.")
            visits_skipped_no_property += len(row["visits"])
            continue

        existing_dates = {v["visit_date"] for v in list_visits(property_id)}

        for year, visit_date, amount in row["visits"]:
            if visit_date is None:
                continue
            if visit_date.isoformat() in existing_dates:
                print(f"   {year}: {visit_date} — already logged, skipping")
                visits_skipped_existing += 1
                continue
            print(f"   {year}: {visit_date}" + (f", ${amount:.2f}" if amount else ""))
            if args.apply:
                add_visit(property_id, visit_date.isoformat(), amount_usd=amount)
                visits_written += 1

        if row["credenciales"]:
            preview = row["credenciales"].replace("\n", " / ")[:60]
            print(f"   🔑 credentials found: {preview}...")
            if args.apply_credentials:
                save_credentials(site_id, schema_name, row["credenciales"])
                creds_written += 1

        print()

    if unmapped:
        print(f"Unmapped rows (no site match — see PROYECTO_TO_SITE): {', '.join(unmapped)}\n")

    print("── Summary ──")
    print(f"Visits written:              {visits_written}" + ("" if args.apply else " (dry run — pass --apply to write)"))
    print(f"Visits already present:      {visits_skipped_existing}")
    print(f"Visits skipped (no property): {visits_skipped_no_property}")
    print(f"Credentials written:         {creds_written}" + ("" if args.apply_credentials else " (dry run — pass --apply-credentials to write)"))


if __name__ == "__main__":
    main()
