"""Load an eGauge CSV export into the vrm.egauge_* tables (migration 070). Idempotent: re-running upserts the same rows.

    python3 scripts/load_egauge.py CSV --site-id mar-profundo-planta-actual --name "Mar Profundo - planta actual" \
        [--company "Mar Profundo"] [--phases 3] [--v-ll 208] [--tz America/Costa_Rica] [--dry-run]

Expected columns (eGauge "Date & Time" export, 15-minute rows, any order):
  "Date & Time", "Usage [kW]", "Generation [kW]", "L1 [V]" "L2 [V]" "L3 [V]", "L1-L2 [V]" "L2-L3 [V]" "L3-L1 [V]",
  and any number of "<meter name> [kW]" columns (boards, chambers, machines): these go, as hourly means, to egauge_circuits_hourly.
Timestamps are the plant's local time; they are stored as UTC (the stamp's interval edge is as eGauge exported it).
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BATCH = 2000
SAMPLE_COLS = {"Usage [kW]": "usage_kw", "Generation [kW]": "generation_kw", "L1 [V]": "v_l1", "L2 [V]": "v_l2", "L3 [V]": "v_l3",
               "L1-L2 [V]": "v_l12", "L2-L3 [V]": "v_l23", "L3-L1 [V]": "v_l31"}


def _clean(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def read(csv: Path, tz: str) -> pd.DataFrame:
    df = pd.read_csv(csv, parse_dates=["Date & Time"]).sort_values("Date & Time").drop_duplicates("Date & Time")
    df["ts"] = df["Date & Time"].dt.tz_localize(tz).dt.tz_convert("UTC")
    return df.set_index("ts").drop(columns=["Date & Time"])


def sample_rows(df: pd.DataFrame, site_id: str) -> list[dict]:
    cols = [c for c in SAMPLE_COLS if c in df.columns]
    out = df[cols].rename(columns=SAMPLE_COLS).round(4)
    return [{"site_id": site_id, "ts": ts.isoformat(), **{k: _clean(float(v)) for k, v in row.items()}} for ts, row in out.iterrows()]


def circuit_rows(df: pd.DataFrame, site_id: str) -> list[dict]:
    meters = [c for c in df.columns if c.endswith("[kW]") and c not in SAMPLE_COLS]
    hourly = df[meters].resample("1h").mean().dropna(how="all")
    names = {c: re.sub(r"\s*\[kW\]$", "", c).strip() for c in meters}
    return [{"site_id": site_id, "ts": ts.isoformat(), "kw": {names[c]: round(float(v), 3) for c, v in row.items() if not math.isnan(v)}}
            for ts, row in hourly.iterrows()]


def push(table: str, rows: list[dict], on_conflict: str = "site_id,ts") -> None:
    from database.supabase_client import get_client

    t = get_client().schema("vrm").table(table)
    for i in range(0, len(rows), BATCH):
        t.upsert(rows[i:i + BATCH], on_conflict=on_conflict).execute()
        print(f"  {table}: {min(i + BATCH, len(rows)):,}/{len(rows):,}", end="\r")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--site-id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--company")
    ap.add_argument("--phases", type=int, default=3)
    ap.add_argument("--v-ll", type=float, default=208.0)
    ap.add_argument("--tz", default="America/Costa_Rica")
    ap.add_argument("--notes")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    df = read(a.csv, a.tz)
    samples, circuits = sample_rows(df, a.site_id), circuit_rows(df, a.site_id)
    has_pv = bool("Generation [kW]" in df and df["Generation [kW]"].max() > 0.05)
    print(f"{len(df):,} readings {df.index.min()} -> {df.index.max()}; {len(circuits):,} hourly circuit rows; PV on site: {has_pv}")
    if a.dry_run:
        return
    site = {"site_id": a.site_id, "name": a.name, "company": a.company, "phases": a.phases, "nominal_v_ll": a.v_ll, "timezone": a.tz,
            "has_pv": has_pv, "first_ts": df.index.min().isoformat(), "last_ts": df.index.max().isoformat(), "notes": a.notes}
    from database.supabase_client import get_client

    get_client().schema("vrm").table("egauge_sites").upsert(site, on_conflict="site_id").execute()
    push("egauge_samples", samples)
    push("egauge_circuits_hourly", circuits)


if __name__ == "__main__":
    main()
