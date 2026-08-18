from __future__ import annotations
"""
`POST /v1/reports` — build a weekly/overview report and render it to PDF.

Wraps `victron/weekly_report.py:build_report_data()` + `render_pdf()`
unchanged. The one piece of business logic this router owns (rather than
`victron/*`) is the `schema="monitoring"` gate: `monitoring` is Pauly & Co's
own Cerbo GX fleet (migration 004), has no `vrm.customers` owner at all, and
must never be reachable by a customer-actor request — PLAN_PHASE14.md
§1.12 rule 2 restated for the API side of the trust boundary.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from victron import weekly_report

from vrm_api import jobs, storage, tenancy
from vrm_api.deps import require_pipeline_key
from vrm_api.schemas import JobCreated, ReportRequest

router = APIRouter(prefix="/v1/reports", tags=["reports"],
                   dependencies=[Depends(require_pipeline_key)])


def _report_summary(data: dict) -> dict:
    """The small, JSON-safe subset of `build_report_data()`'s output that a
    web dashboard needs to render the same KPI tiles/chips/energy-mix bar
    `pages/06_vrm_monitor.py:tab_report()` already shows on screen (as
    opposed to what only the rendered PDF shows, e.g. the narrative) —
    added here, additively, for `victron-monitor/web`'s Step 6 Reports page
    (PLAN_PHASE14.md §2 Step 6, §1.11).

    §1.11 is explicit that the Next.js layer must not reimplement
    `build_report_data()`'s math — "anything that computes a number a
    customer sees goes through vrm_api." The Step 5 result shape
    (`storage_path`/`is_overview`/`start`/`end` only) was written before
    Step 6 needed to show any of those numbers on screen, not the PDF alone;
    this is the closing of that gap, not a reinterpretation of §1.11 — the
    alternative (computing grid independence, battery stress tier, etc. a
    second time in TypeScript) is exactly the duplication §1.11 rules out.
    `storage_path`/`is_overview`/`start`/`end` are unchanged for any
    existing caller; `summary` is purely additive.
    """
    tot = data["totals"]
    return {
        "siteName": data["siteName"],
        "startStr": data["startStr"],
        "endStr": data["endStr"],
        "schema": data["schema"],
        "systemType": data["systemType"],
        "totals": {
            "pv": round(tot["pv"], 1),
            "load": round(tot["load"], 1),
            "grid": round(tot["grid"], 1),
            "discharge": round(tot["discharge"], 1),
            "charge": round(tot["charge"], 1),
            "outageCount": tot["outageCount"],
            "outageMinutes": tot["outageMinutes"],
        },
        "gridIndependencePct": data["gridIndependencePct"],
        "avgHealth": data["avgHealth"],
        "healthStatus": data["healthStatus"],
        "batteryCycles": data["batteryCycles"],
        "battStressLabel": data["battStressLabel"],
        "battStressColor": data["battStressColor"],
        "gridQualityScore": data["gridQualityScore"],
        "gridQualityStatus": data["gridQualityStatus"],
        "gridQualityColor": data["gridQualityColor"],
        "weatherErrors": data["weatherErrors"],
        "missingDays": data["missingDays"],
        "daysWithData": len(data["dailyGrouped"]),
        "isOverview": data["isOverview"],
        "exportsToGrid": data["exportsToGrid"],
        "longestOutageMinutes": data["longestOutageMinutes"],
        "alarmEpisodesTotal": data["alarmEpisodesTotal"],
    }


def _do_report(site_id: str, start: str, end: str, schema_: str) -> dict:
    data = weekly_report.build_report_data(site_id, start, end, schema_)
    pdf_bytes = weekly_report.render_pdf(data)
    storage_path = storage.upload_report_pdf(site_id, start, end, pdf_bytes)
    return {
        "storage_path": storage_path,
        "is_overview": bool(data.get("isOverview")),
        "start": data.get("startStr"),
        "end": data.get("endStr"),
        "summary": _report_summary(data),
    }


@router.post("", response_model=JobCreated)
def post_report(body: ReportRequest, background_tasks: BackgroundTasks) -> JobCreated:
    if body.schema_ == "monitoring" and body.actor != "admin":
        # 403, not 422: this is an authorization decision (who is allowed to
        # ask for monitoring data), not a malformed request — a caller
        # should be able to tell the two apart.
        raise HTTPException(status_code=403, detail="monitoring schema requires actor=admin")

    if body.schema_ == "vrm":
        # The real tenancy re-check (PLAN_PHASE14.md §1.3): customer_id must
        # own site_id in vrm.sites, independently of whatever Next.js
        # already checked. `monitoring` sites have no vrm.customers owner —
        # the actor=="admin" gate above is the only guard that applies to
        # them, by design (PLAN_PHASE14.md §1.12 rule 2).
        tenancy.assert_owns_site(body.customer_id, body.site_id)
    else:
        tenancy.get_customer(body.customer_id)

    job = jobs.create_job("report", customer_id=body.customer_id, site_id=body.site_id,
                          params=body.model_dump(by_alias=True))
    background_tasks.add_task(
        jobs.run_job, job["id"],
        lambda: _do_report(body.site_id, body.start, body.end, body.schema_),
    )
    return JobCreated(job_id=job["id"])
