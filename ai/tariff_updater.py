"""AI-assisted CNFL tariff refresh from PDF. Phase 7."""


def refresh_cnfl_tariffs(pdf_bytes: bytes) -> dict:
    """
    Fetch CNFL tariff PDF → send to Claude → return extracted tariff table as JSON.
    Engineer reviews diff before confirming update to DB.

    Returns:
        {
          "access_charge_crc": 3100,
          "tiers": [
            {"from_kwh": 0, "to_kwh": 200, "rate_crc": 79.28},
            ...
          ],
          "effective_date": "2026-01-01"
        }
    """
    raise NotImplementedError("Phase 7")
