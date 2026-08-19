from __future__ import annotations
"""
FastAPI entry point for `vrm_api` — the internal pipeline service
`victron-monitor/web`'s server calls to run VRM CSV ingestion and render
weekly/overview reports, without rewriting `victron/vrm_csv.py`,
`victron/ingest.py`, or `victron/weekly_report.py` (PLAN_PHASE14.md §1.3,
§2 Step 5).

── No CORS middleware — anywhere, ever (PLAN_PHASE14.md §1.3) ─────────────
This is not "CORS configured to deny everything"; it is CORS not configured
at all. `victron-monitor/web`'s server is the only legitimate caller, and a
server never runs in a browser's CORS sandbox to begin with — it doesn't
need permission. Installing `CORSMiddleware` with an empty/strict allow-list
would still add an `Access-Control-*` response path that a future edit could
loosen by one line without anyone noticing it changed the trust boundary.
With no middleware installed, Starlette has nothing to answer a browser's
`OPTIONS` preflight with (no route here declares `OPTIONS`, so it 405s, and
no response anywhere carries `Access-Control-Allow-Origin`) — a browser
fails the preflight by construction, not by policy.

── Every route but /health requires a bearer token (vrm_api/deps.py) ──────
Wired as a `dependencies=[Depends(require_pipeline_key)]` on each router
in `routers/`, not globally on `app` — `GET /health` is registered directly
here with no dependency, because it is the one endpoint PLAN_PHASE14.md §1.3
carves out as unauthenticated (so an uptime monitor / Render's own health
check can hit it without holding the pipeline key).

Run locally, from the repo root (not from inside `vrm_api/`):
    uvicorn vrm_api.main:app --reload
"""
import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from vrm_api import jobs, storage
from vrm_api.deps import require_pipeline_key
from vrm_api.routers import ingest, meta, reports, vrm_fleet, vrm_link, vrm_sync
from vrm_api.schemas import JobOut
from vrm_api.tenancy import NotAuthorized, VrmAccountAlreadyLinked

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vrm_api")

# docs_url/redoc_url/openapi_url all disabled: this API has exactly one
# intended caller (Next.js's server), so a public interactive schema is pure
# downside — one more surface that could leak endpoint shapes to whoever
# stumbles onto the host, for zero benefit to the only caller that matters
# (it already has this source tree).
app = FastAPI(title="vrm_api", docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(NotAuthorized)
async def _not_authorized_handler(request: Request, exc: NotAuthorized) -> JSONResponse:
    # The *reason* (which customer, which site) stays server-side, logged —
    # never in the response. Same rule as jobs.py:_safe_error_message()
    # (PLAN_PHASE14.md §1.12 rule 6).
    logger.warning("tenancy check failed on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=403, content={"code": "not_authorized"})


@app.exception_handler(VrmAccountAlreadyLinked)
async def _vrm_account_already_linked_handler(
    request: Request, exc: VrmAccountAlreadyLinked
) -> JSONResponse:
    # PLAN_PHASE15.md §1.5: turns a raw Postgres unique-violation on
    # vrm.customers.vrm_user_id into a clean, typed, customer-renderable
    # response instead of an opaque 500 — same pattern as NotAuthorized
    # above. The message itself is safe to return as-is (see the exception's
    # own docstring in tenancy.py — it never names the other customer).
    logger.info("vrm-link connect: %s", exc)
    return JSONResponse(
        status_code=409,
        content={"code": "vrm_account_already_linked", "message": str(exc)},
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # The last-resort backstop: whatever this is, the caller gets a typed
    # code and nothing else, and the full traceback goes to the log. Without
    # this, an unexpected Postgres/pandas/WeasyPrint exception would
    # otherwise surface FastAPI's default 500 body, which (unlike this
    # handler) includes the exception's own message — exactly what
    # PLAN_PHASE14.md §1.3 / §1.12 rule 6 says must never reach a browser.
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"code": "internal_error"})


@app.on_event("startup")
def _on_startup() -> None:
    # Both sweeps are best-effort housekeeping, not preconditions for
    # serving traffic — a transient DB hiccup, or `vrm.jobs`/the Storage
    # bucket not existing yet in a freshly-provisioned environment (this is
    # exactly what migration 023 not being applied yet looks like), must not
    # crash the whole process on startup. The stale-job/orphan-upload sweep
    # existing at all is meant to make restarts *safer*; it would be
    # self-defeating if a sweep failure were itself a reason the service
    # can't come back up after a restart.
    try:
        failed = jobs.sweep_stale_jobs()
        if failed:
            logger.warning("startup: marked %d stale running job(s) as failed", failed)
    except Exception:  # noqa: BLE001 — see above
        logger.exception("startup: stale-job sweep failed")

    try:
        removed = storage.sweep_orphan_uploads()
        if removed:
            logger.info("startup: removed %d orphaned upload(s)", removed)
    except Exception:  # noqa: BLE001 — see storage.py:sweep_orphan_uploads docstring
        logger.exception("startup: orphan-upload sweep failed")


@app.get("/health")
def health() -> dict:
    """The one unauthenticated route (PLAN_PHASE14.md §1.3). Deliberately
    minimal — no version string, no dependency status, no build info; just
    enough to prove the process is up and answering requests."""
    return {"status": "ok"}


@app.get("/v1/jobs/{job_id}", response_model=JobOut, dependencies=[Depends(require_pipeline_key)])
def get_job(job_id: str) -> JobOut:
    """Polled by Next.js's job-proxy route handler, which is where the
    customer-scoping for this lives (PLAN_PHASE14.md §1.6: "the browser
    polls a Next.js route handler that proxies GET /v1/jobs/{id} (scoped:
    the handler refuses a job whose customer_id isn't the session's)") —
    this endpoint itself answers to any holder of the pipeline key, same as
    every other route in this API; the pipeline key authenticates "this is
    our own trusted server," not "this is a specific customer."
    """
    row = jobs.get_job(job_id)
    if not row:
        raise HTTPException(status_code=404)
    return JobOut(**row)


app.include_router(ingest.router)
app.include_router(reports.router)
app.include_router(meta.router)
app.include_router(vrm_link.router)
app.include_router(vrm_sync.router)
app.include_router(vrm_fleet.router)
