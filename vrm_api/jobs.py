from __future__ import annotations
"""
Job bookkeeping against `vrm.jobs` (migration 023) — create/run/poll, plus
the startup sweep for jobs orphaned by a restart. PLAN_PHASE14.md §1.6.

Execution model: a route handler creates a `queued` row synchronously (one
insert — fast), then schedules `run_job` via FastAPI's `BackgroundTasks`.
Starlette runs a *sync* background task through `anyio.to_thread` — its
bounded worker thread pool — automatically; nothing here spins up its own
executor. That is the whole of "in-process, bounded thread pool, not Celery/
Redis" (§1.6): the concurrency control already exists in the framework, so
adding a second one would just be two pools to reason about instead of one.

The trade this buys: a container restart silently drops any job that was
mid-flight. There is no queue to persist it and re-pick it up. `sweep_stale_jobs()`
is the honest acknowledgment of that cost, not a fix for it — it turns
"stuck in `running` forever" into "clearly `failed`, please retry," which is
the best a process with no state outside one Postgres row can promise.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from database.supabase_client import get_client

logger = logging.getLogger("vrm_api.jobs")

SCHEMA = "vrm"
STALE_RUNNING_MINUTES = 15


def _t():
    return get_client().schema(SCHEMA).table("jobs")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(obj: Any) -> Any:
    """Best-effort coercion to plain JSON-safe types before a `jsonb` write.

    `victron/vrm_csv.py:parse_export()`'s output is already plain
    floats/ints/strings (every numeric field is wrapped in `round(float(...))`
    or `.isoformat()` — see that module), so this is cheap insurance, not a
    load-bearing conversion: better a stringified value than a background
    job crashing on an insert because one field turned out to be a pandas/
    numpy scalar.
    """
    return json.loads(json.dumps(obj, default=str))


def create_job(kind: str, customer_id: str, site_id: str | None, params: dict) -> dict:
    """Inserts a `queued` job row and returns it (including the DB-assigned
    `id`, which the caller returns to the client as `job_id`)."""
    row = {
        "kind": kind,
        "customer_id": customer_id,
        "site_id": site_id,
        "status": "queued",
        "params": _jsonable(params),
    }
    return _t().insert(row).execute().data[0]


def get_job(job_id: str) -> dict | None:
    rows = _t().select("*").eq("id", job_id).limit(1).execute().data
    return rows[0] if rows else None


def _safe_error_message(exc: Exception) -> str:
    """The text stored in `vrm.jobs.error`, which Next.js relays toward the
    customer's browser (PLAN_PHASE14.md §1.3 / §1.12 rule 6: never a raw
    Postgres/Python error string reaches a customer). Exceptions this
    pipeline already raises with a deliberately customer-safe message
    (`VrmCsvError` — "this doesn't look like a VRM export" — and this API's
    own `NotAuthorized`) are passed through as-is; anything else collapses to
    one generic sentence, with the real exception and traceback going to the
    server log via `logging.exception` in `run_job` below, not here.
    """
    from victron.vrm_csv import VrmCsvError

    from vrm_api.tenancy import NotAuthorized

    if isinstance(exc, (VrmCsvError, NotAuthorized)):
        return str(exc)
    return "Internal error — see server logs."


def run_job(job_id: str, work_fn: Callable[[], dict]) -> None:
    """The `BackgroundTasks` target. Marks the job `running`, calls
    `work_fn()` (the actual parse/ingest/report work, already validated by
    the route handler before scheduling this), and stores the outcome.

    `work_fn` takes no arguments by convention — route handlers close over
    whatever the job needs (already-fetched customer/site rows, the parsed
    request body) rather than this function re-deriving them, so the
    tenancy checks a route handler already ran are not silently skipped or
    re-run differently here.
    """
    _t().update({"status": "running", "started_at": _now()}).eq("id", job_id).execute()
    try:
        result = work_fn()
        _t().update({
            "status": "done",
            "result": _jsonable(result),
            "finished_at": _now(),
        }).eq("id", job_id).execute()
    except Exception as exc:  # noqa: BLE001 — this IS the boundary that must not crash
        logger.exception("job %s (kind unknown here) failed", job_id)
        _t().update({
            "status": "failed",
            "error": _safe_error_message(exc),
            "finished_at": _now(),
        }).eq("id", job_id).execute()


def sweep_stale_jobs() -> int:
    """Run once at API startup (`main.py`). Anything still `running` past a
    generous margin for the slowest real job (a multi-month Overview report:
    Anthropic + Open-Meteo + WeasyPrint, still well under a minute in
    practice) is presumed orphaned by a restart, not merely slow, and is
    failed with a message that tells the caller to retry rather than
    leaving a spinner with no job behind it. Returns the number of jobs
    failed, purely for the startup log line.
    """
    cutoff = (datetime.now(timezone.utc)
              - timedelta(minutes=STALE_RUNNING_MINUTES)).isoformat()
    stale = (_t().select("id").eq("status", "running").lt("started_at", cutoff)
             .execute().data or [])
    for row in stale:
        _t().update({
            "status": "failed",
            "error": "Interrupted by a server restart — please try again.",
            "finished_at": _now(),
        }).eq("id", row["id"]).execute()
    return len(stale)
