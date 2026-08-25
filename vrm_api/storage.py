from __future__ import annotations
"""
Supabase Storage access for `vrm_api` (PLAN_PHASE14.md §1.5, §2 Step 5).

The browser never uploads through this API or through Next.js at all — it
`PUT`s straight to a Supabase Storage signed URL Next.js hands it (Step 6;
Vercel's 4.5 MB request-body cap rules out routing the file through a Next.js
route handler). This module implements the other half: once the browser
posts the object's *path* back, `vrm_api` downloads it here to parse it, and
uploads the rendered report PDF here too. The upload-signing half (deciding
the `uploads/{customer_id}/{uuid}.csv` convention, calling
`createSignedUploadUrl()`) is Step 6's — this module only needs a path to
download from, which Step 6 will hand it unchanged.

No ambient file access (PLAN_PHASE14.md §1.3): every function here takes an
explicit Storage path from a caller that has already been through
`vrm_api/tenancy.py`'s checks — never a caller-supplied URL, never a local
path, never anything read from disk outside this bucket.
"""
import io
import logging
from datetime import datetime, timedelta, timezone

from database.supabase_client import get_client

logger = logging.getLogger("vrm_api.storage")

BUCKET = "vrm-monitor"
UPLOADS_PREFIX = "uploads"
REPORTS_PREFIX = "reports"
# PLAN_PHASE14.md §1.5 point 4: an orphaned upload (browser uploaded, then
# never confirmed — closed tab, abandoned preview) has no benefit sitting in
# Storage. The CSV is fully re-derivable from VRM; a week is generous slack
# for someone to come back and finish a preview they started.
ORPHAN_UPLOAD_MAX_AGE_DAYS = 7


def _bucket():
    return get_client().storage.from_(BUCKET)


def download_csv(storage_path: str) -> io.BytesIO:
    """Downloads a CSV object into an in-memory buffer.

    Wrapped in `BytesIO` rather than handed back as raw `bytes` because
    `victron/vrm_csv.py:load_vrm_csv()` already accepts "a path or a
    file-like object" (it was written for a Streamlit `UploadedFile`) — a
    `BytesIO` is a file-like object, so the exact same parsing function reads
    a Storage download unchanged, no new code path in `victron/*` needed.
    """
    data = _bucket().download(storage_path)
    return io.BytesIO(data)


def download_object_bytes(storage_path: str) -> bytes:
    """Downloads any object in this bucket as raw bytes (PLAN_PHASE17.md
    §4.4/§8 Step 4) — `vrm_api/branding.py:resolve_branding()`'s only use of
    Storage, to base64-embed a customer's logo directly into a rendered PDF
    the same way `proposals/assets/assets.py:get_logo_b64()` embeds the
    Pauly & Co asset from local disk. Raises on a missing/unreadable object;
    the caller (`resolve_branding()`) is the one that decides a missing logo
    is a warning-and-fallback, not a failed report — this function stays a
    plain, unopinionated read."""
    return _bucket().download(storage_path)


def upload_report_pdf(site_id: str, start: str, end: str, pdf_bytes: bytes) -> str:
    """Uploads a rendered report PDF, returns the Storage path (what
    `routers/reports.py` stores as `result.storage_path`). `upsert=true`
    because a caller re-generating the same range is expected to overwrite,
    not collide."""
    path = f"{REPORTS_PREFIX}/{site_id}/{start}_{end}.pdf"
    _bucket().upload(
        path, pdf_bytes,
        {"content-type": "application/pdf", "upsert": "true"},
    )
    return path


def delete_object(path: str) -> None:
    """Best-effort delete. Failures are logged, never raised — a stray
    object left in Storage after a successful ingest is a minor cleanup
    debt; failing the ingest job over it would be a much worse trade."""
    try:
        _bucket().remove([path])
    except Exception:  # noqa: BLE001 — see docstring
        logger.exception("failed to delete storage object %s", path)


def sweep_orphan_uploads(max_age_days: int = ORPHAN_UPLOAD_MAX_AGE_DAYS) -> int:
    """Deletes any `uploads/{customer}/...` object older than `max_age_days`.

    Run from `main.py`'s startup hook, the same moment `jobs.sweep_stale_jobs()`
    runs — PLAN_PHASE14.md §1.5 point 4 explicitly ties the two together
    ("swept by the same job the API runs on startup"). Best-effort at every
    level: a bucket or prefix that doesn't exist yet (a fresh environment
    before Step 6/8 provision it) is logged and treated as "nothing to
    sweep," not a startup failure.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    removed = 0
    try:
        customer_dirs = _bucket().list(UPLOADS_PREFIX)
    except Exception:  # noqa: BLE001 — see docstring
        logger.info("orphan-upload sweep: could not list %s/ (bucket not provisioned yet?)",
                    UPLOADS_PREFIX)
        return 0

    for entry in customer_dirs or []:
        name = entry.get("name")
        # Storage's `list()` returns files and "directories" (prefixes with
        # no id/metadata of their own) in the same shape; a real file at the
        # bucket root here would be unexpected, but skip it rather than
        # crash the sweep over one odd entry.
        if not name or entry.get("id") is not None:
            continue
        prefix = f"{UPLOADS_PREFIX}/{name}"
        try:
            files = _bucket().list(prefix)
        except Exception:  # noqa: BLE001
            continue
        for f in files or []:
            created = f.get("created_at")
            if not created:
                continue
            try:
                created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                continue
            if created_at < cutoff:
                delete_object(f"{prefix}/{f['name']}")
                removed += 1
    return removed
