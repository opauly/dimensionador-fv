"""
WeasyPrint PDF generator: data dict → Jinja2 HTML → PDF bytes → Supabase Storage. Phase 1.

Templates (proposals/templates/):
    grid_zero_es.html  — Grid Zero, Spanish
    grid_zero_en.html  — Grid Zero, English
    off_grid_es.html   — Off-Grid / Hybrid, Spanish
    off_grid_en.html   — Off-Grid / Hybrid, English
"""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_pdf(data: dict, system_type: str, language: str) -> bytes:
    """
    Render proposal to PDF.

    Args:
        data: Full wizard data dict (mirrors proposal_versions.data JSON structure).
        system_type: 'grid_zero' | 'off_grid' | 'hybrid'
        language: 'es' | 'en'

    Returns PDF bytes ready for download or Supabase Storage upload.
    """
    raise NotImplementedError("Phase 1")


def upload_pdf(pdf_bytes: bytes, proposal_id: str, version_number: int, client_name: str) -> str:
    """
    Upload PDF to Supabase Storage.
    Path: proposals/{proposal_id}/v{n}_{client}_{date}.pdf
    Returns the storage path string.
    """
    raise NotImplementedError("Phase 1")
