"""Load the QuickBooks supplier list into fin_vendors (Phase 25, migration 073).

    .venv/bin/python scripts/seed_fin_vendors.py "<path>/Suppliers.xlsx"

Skips QuickBooks' catch-all names (Materiales, Viáticos, Otros…), which were
used as categories, not real suppliers. Safe to run again: existing names
are left alone.
"""
from __future__ import annotations

import os
import sys
import warnings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

GENERIC = {"ajustes", "comidas", "extras", "materiales", "otros", "transporte de equipo", "viáticos", "viaticos"}


def main(path: str) -> None:
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    from database.finance_db import add_vendors

    warnings.filterwarnings("ignore")
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    names, col = [], None
    for row in ws.iter_rows(values_only=True):
        cells = [str(c).strip() if c is not None else "" for c in row]
        if col is None:
            if "Supplier" in cells:
                col = cells.index("Supplier")
            continue
        name = cells[col] if col < len(cells) else ""
        if name and name.lower() not in GENERIC:
            names.append(name)
    added = add_vendors(names, source="quickbooks")
    print(f"{len(names)} proveedores en el archivo, {added} nuevos agregados.")


if __name__ == "__main__":
    main(sys.argv[1])
