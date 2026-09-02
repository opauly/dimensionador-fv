"""One-off: back up every monitoring.* row for a given set of site_ids to
local JSON files, one file per table, before any decision to archive/remove
them. Read-only against Supabase — writes only to the local filesystem.

Usage:
    python -m tools.backup_monitoring_site_data
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client  # noqa: E402

SITE_IDS = ["vista-atenas-lp-m1", "vista-atenas-lp-m2", "vista-atenas-lp-m3"]
TABLES = [
    "sites", "energy_daily", "daily_health", "ac_input_events",
    "alarm_events", "grid_events", "mppt_snapshots", "flow_logs",
]

OUT_DIR = Path("backups") / f"monitoring_lori_pickett_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


PAGE_SIZE = 1000  # PostgREST's own default response cap — must page past it
# explicitly or a table like mppt_snapshots (~4900 rows for one site) would
# silently truncate to the first 1000.


def _fetch_all(query_fn, page_size: int = PAGE_SIZE) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        page = query_fn().range(start, start + page_size - 1).execute().data
        rows.extend(page)
        if len(page) < page_size:
            break
        start += page_size
    return rows


def main() -> None:
    c = get_client()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Backing up to {OUT_DIR}/\n")

    for table in TABLES:
        rows = _fetch_all(lambda t=table: c.schema("monitoring").table(t).select("*").in_("site_id", SITE_IDS))
        path = OUT_DIR / f"{table}.json"
        path.write_text(json.dumps(rows, indent=2, default=str))
        print(f"  {table}: {len(rows)} row(s) -> {path}")

    print(f"\nDone. {OUT_DIR}/ contains a full snapshot of monitoring.* for {SITE_IDS}.")


if __name__ == "__main__":
    main()
