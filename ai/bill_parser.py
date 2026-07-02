"""Extract monthly kWh and ₡ amounts from electricity bill PDFs. Phase 4."""


def parse_bill(pdf_bytes: bytes) -> list[dict]:
    """
    Send bill PDF to Claude, extract monthly consumption data.

    Returns list of dicts:
        [{"month": "Enero 2025", "kwh": 1475, "amount_crc": 157874}, ...]
    Engineer reviews and confirms before data is written to wizard state.
    """
    raise NotImplementedError("Phase 4")
