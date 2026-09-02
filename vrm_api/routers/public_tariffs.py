from __future__ import annotations
"""
Read-only, public-facing ARESEP tariff lookup — the one deliberate exception
to `main.py`'s "exactly one caller" design (see that file's module docstring
and `deps.py`'s docstring for `require_public_tariff_key`).

Exists so a maintenance report built in an external tool (Claude Design) can
pull a distributor's current tariff live instead of a human copying tier
numbers out of this project by hand into a text box each time — the previous
workflow, and the reason this route exists at all: rates drift whenever
ARESEP revises them, and a hand-copied number has no way to notice that.

Kept deliberately narrow to match what "public" should mean here:
- Read-only (no route in this file can create, update, or delete anything).
- Tariff data only — distributor names/abbreviations and ARESEP rate
  structures, which are public utility filings, not anything about a
  customer, a site, or this project's own metering data.
- Gated by `PUBLIC_TARIFF_API_KEY`, a secret distinct from `PIPELINE_API_KEY`
  (`deps.py`), so holding it proves nothing about any other route.
"""
from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError

from database import tariffs_db
from vrm_api.deps import require_public_tariff_key
from vrm_api.schemas import DistributorOut, TariffInfoOut

router = APIRouter(
    prefix="/public/tariffs",
    tags=["public-tariffs"],
    dependencies=[Depends(require_public_tariff_key)],
)


@router.get("/distributors", response_model=list[DistributorOut])
def list_distributors() -> list[DistributorOut]:
    """Every seeded CR distributor — lets a caller resolve "Belén, Heredia"
    to an abbreviation without this project hand-maintaining that mapping
    anywhere else."""
    return [DistributorOut(**d) for d in tariffs_db.list_distributors()]


@router.get("/{abbreviation}", response_model=TariffInfoOut)
def get_tariff(abbreviation: str, code: str = "T-RE") -> TariffInfoOut:
    """Current tariff block for one distributor + tariff code (defaults to
    `T-RE`, the residential tariff every savings-table use case so far has
    needed). `tariff_types` is upserted in place (`tariffs_db.py`'s
    `upsert_tariff_type_row` — one row per distributor+code, no history
    table), so this is always the latest block; `last_updated` is how a
    caller confirms that rather than trusting it silently."""
    try:
        info = tariffs_db.get_tariff_info(abbreviation.upper(), code)
    except APIError as exc:
        # tariffs_db.get_tariff_info's `.single().execute()` calls raise
        # postgrest's APIError (code PGRST116, "0 rows") on a miss rather
        # than returning data=None despite the `dict | None` return type —
        # a pre-existing quirk in that shared helper, not something this
        # route can fix without touching every other caller. Translate it
        # here so an unknown abbreviation/code reaches an external caller as
        # a clean 404 instead of a 500.
        if exc.code == "PGRST116":
            info = None
        else:
            raise
    if not info:
        raise HTTPException(status_code=404, detail="tariff not found")

    return TariffInfoOut(
        distributor_abbreviation=info["distributor"]["abbreviation"],
        distributor_name=info["distributor"]["name"],
        code=info["code"],
        name=info["name"],
        access_charge_crc=info["access_charge_crc"],
        bomberos_pct=info["bomberos_pct"],
        iva_threshold_kwh=info["iva_threshold_kwh"],
        alumbrado_publico_rate_crc=info.get("alumbrado_publico_rate_crc") or 0.0,
        ios_monthly_crc=info.get("ios_monthly_crc") or 0.0,
        coa_monthly_crc=info.get("coa_monthly_crc") or 0.0,
        cvg_monthly_crc=info.get("cvg_monthly_crc") or 0.0,
        last_updated=str(info["last_updated"]) if info.get("last_updated") else None,
        tiers=info["tiers"],
    )
