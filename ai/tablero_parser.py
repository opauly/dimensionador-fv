"""Extract circuit schedule from electrical panel tablero (PDF or image). Phase 5."""


def parse_tablero(file_bytes: bytes, mime_type: str = "application/pdf") -> dict:
    """
    Send tablero document to Claude, extract circuit list.

    Returns:
        {
          "circuits": [{"name": "A/C sala", "kva": 1.5, "qty": 1}, ...],
          "total_kva": 18.4,
          "demand_factor_estimated": 0.55,
          "notes": "..."
        }
    """
    raise NotImplementedError("Phase 5")
