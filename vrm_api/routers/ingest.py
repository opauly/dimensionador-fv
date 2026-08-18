from __future__ import annotations
"""
CSV ingestion: `POST /v1/ingest/preview` then `POST /v1/ingest/commit`.

The two-step split is `victron/ingest.py`'s own file-parsed-exactly-once
rule, unchanged from `pages/06_vrm_monitor.py:tab_upload()` ("never write on
the first click," PLAN_PHASE14.md §1.6): `preview` downloads and parses the
CSV once and stores the result on the job row; `commit` writes from that
stored result and never re-reads the source file.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from victron import ingest as victron_ingest
from victron import vrm_csv

from vrm_api import jobs, storage, tenancy
from vrm_api.deps import require_pipeline_key
from vrm_api.schemas import IngestCommitRequest, IngestPreviewRequest, JobCreated

router = APIRouter(prefix="/v1/ingest", tags=["ingest"],
                   dependencies=[Depends(require_pipeline_key)])


def _battery_usable_kwh(site_fields: dict) -> float | None:
    """Same formula as the GENERATED `vrm.sites.battery_usable_kwh` column
    (migration 019) and `pages/06_vrm_monitor.py`'s upload tab — computed
    here only as an argument to `parse_export()` (it stamps
    `energy_daily.battery_kwh_snapshot`), never written to `vrm.sites`
    directly; that column computes itself."""
    nominal = site_fields.get("battery_nominal_kwh")
    dod = site_fields.get("battery_dod_pct")
    return round(nominal * dod / 100, 2) if nominal and dod else None


def _do_preview(customer: dict, site_name_or_id: str, storage_path: str,
                filename: str, site_fields: dict) -> dict:
    """Downloads the CSV exactly once, parses it, and returns everything
    `_do_commit` (a later, separate job) needs — the preview/commit split
    this module's docstring describes. Runs inside the background thread
    `jobs.run_job` schedules it on, so it must not touch anything the route
    handler hasn't already validated (the caller passes in an already
    tenancy-checked `customer` row rather than a bare `customer_id`).
    """
    existing = tenancy.find_customer_site(customer["id"], site_name_or_id)
    site_id = (existing["site_id"] if existing
              else victron_ingest.make_site_id(customer["slug"], site_name_or_id))

    # Use the browser's real filename when the caller sent one (Step 6's
    # Next.js proxy always does); only fall back to storage_path's own
    # `{uuid}.csv` name for a caller that didn't (there is none today, but
    # `filename` is optional on the request model, so this must not crash).
    # `vrm_csv.py:installation_id()` parses the VRM installation id out of
    # the *filename* (`<id>_<n>_<site>_log_...`) — the uuid-renamed Storage
    # object name would silently produce `installation_id: None` otherwise.
    display_filename = filename or storage_path.rsplit("/", 1)[-1]

    buf = storage.download_csv(storage_path)
    parsed = vrm_csv.parse_export(
        buf, site_id=site_id, filename=display_filename,
        pv_kwp=site_fields.get("pv_kwp"),
        battery_usable_kwh=_battery_usable_kwh(site_fields),
    )
    return {
        "site_id": site_id,
        "site_is_existing": bool(existing),
        "site_name": site_name_or_id,
        "storage_path": storage_path,
        "filename": display_filename,
        "site_fields": site_fields,
        "parsed": parsed,
    }


@router.post("/preview", response_model=JobCreated)
def post_preview(body: IngestPreviewRequest, background_tasks: BackgroundTasks) -> JobCreated:
    # get_customer() is this endpoint's tenancy check: a caller cannot parse
    # a file "on behalf of" a customer_id that doesn't exist. If
    # site_name_or_id turns out to name an *existing* site, _do_preview()
    # (via find_customer_site) only ever matches one scoped to this same
    # customer_id — there is no way to address another customer's site by
    # name from here.
    customer = tenancy.get_customer(body.customer_id)
    site_fields = body.site_fields.model_dump(exclude_none=True)

    job = jobs.create_job("ingest_preview", customer_id=body.customer_id,
                          site_id=None, params=body.model_dump())
    background_tasks.add_task(
        jobs.run_job, job["id"],
        lambda: _do_preview(customer, body.site_name_or_id, body.storage_path, body.filename, site_fields),
    )
    return JobCreated(job_id=job["id"])


def _do_commit(customer_id: str, preview: dict) -> dict:
    """Writes what `_do_preview` parsed. Deliberately never calls
    `victron.ingest.upsert_customer()` — the tenant is fixed (it is whoever
    the stored `ingest_preview` job belongs to, not anything this request
    body can name), matching PLAN_PHASE14.md §1.12 rule 1: a customer-
    initiated request must never be able to create or rename a tenant.

    # TODO(Step 7): an admin-initiated upload — the one path allowed to
    # touch `upsert_customer` — reaches this API through a different actor
    # context that Step 7's admin flow hasn't defined yet. Nothing in this
    # module calls `upsert_customer`; do not add it here speculatively.
    """
    site_fields = dict(preview["site_fields"])
    parsed = preview["parsed"]
    if parsed.get("installation_id"):
        site_fields.setdefault("vrm_installation_id", int(parsed["installation_id"]))
    display_name = site_fields.pop("display_name", None) or preview["site_name"]

    victron_ingest.upsert_site(customer_id, preview["site_id"], display_name, **site_fields)
    summary = victron_ingest.ingest_parsed(
        parsed, preview["site_id"],
        # The browser's real filename (stamped onto `preview` by
        # `_do_preview` above), not the uuid-renamed Storage object name —
        # see that function's own comment. `ingestion_log.filename` is an
        # audit-trail column ("why did this report look wrong"); a uuid
        # there would defeat the point.
        filename=preview.get("filename") or preview["storage_path"].rsplit("/", 1)[-1],
    )
    storage.delete_object(preview["storage_path"])
    return {"site_id": preview["site_id"], **summary}


@router.post("/commit", response_model=JobCreated)
def post_commit(body: IngestCommitRequest, background_tasks: BackgroundTasks) -> JobCreated:
    source_job = jobs.get_job(body.job_id)
    if (not source_job or source_job["kind"] != "ingest_preview"
            or source_job["status"] != "done" or not source_job.get("result")):
        raise HTTPException(status_code=404)

    customer_id = source_job["customer_id"]
    preview = source_job["result"]
    # Independent re-check even though this job's customer_id was already
    # fixed, unforgeably, at preview time (commit takes no customer_id/
    # site_id of its own to trust or distrust) — PLAN_PHASE14.md §3's "every
    # assertOwnsSite() that looks redundant" instruction. Guards against the
    # (currently theoretical) case of a site being reassigned between
    # preview and commit, at the cost of one query.
    if preview.get("site_is_existing"):
        tenancy.assert_owns_site(customer_id, preview["site_id"])
    else:
        tenancy.get_customer(customer_id)

    job = jobs.create_job("ingest_commit", customer_id=customer_id,
                          site_id=preview["site_id"], params=body.model_dump())
    background_tasks.add_task(jobs.run_job, job["id"],
                              lambda: _do_commit(customer_id, preview))
    return JobCreated(job_id=job["id"])
