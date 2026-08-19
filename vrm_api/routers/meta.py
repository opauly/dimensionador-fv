from __future__ import annotations
"""
Small read-only endpoints the web app needs but that don't warrant a job:
available report dates for a site, the range-boundary constants, and (Step 7
addition) a cross-schema site list for the admin report picker.

`GET /v1/limits` exists specifically so `MAX_CUSTOM_RANGE_DAYS` /
`MAX_OVERVIEW_RANGE_DAYS` are served by this API and never hand-copied into
TypeScript (PLAN_PHASE14.md §1.11) — duplicating them is exactly how the
Detallado/Overview boundary would silently drift between the two surfaces.

── `schema`/`actor` on `available_dates`, and the new `GET /v1/sites` (PLAN_PHASE14.md §2 Step 7) ──
Both are additive, backwards-compatible extensions written for `/admin/reports`
(PLAN_PHASE14.md §Step 7: "both `vrm` and `monitoring` schemas selectable").
Step 5 shipped `available_dates` VRM-only (it always called
`tenancy.assert_owns_site`, which only ever queries `vrm.sites` — a
`monitoring` site_id, which lives in a completely different Postgres schema
with no `vrm.customers` owner at all, could never pass that check). Every
existing caller (the customer-facing proxy, `schema` defaulting to `"vrm"`,
`actor` defaulting to `"customer"`) is unaffected — this only opens a new,
actor-gated branch, mirroring `routers/reports.py`'s own
`schema == "monitoring"` gate rather than inventing a second pattern for the
same rule.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from database import vrm_report_db as rdb

from vrm_api import tenancy
from vrm_api.deps import require_pipeline_key
from vrm_api.schemas import AvailableDatesOut, LimitsOut, SiteSummaryOut, SitesOut

router = APIRouter(prefix="/v1", tags=["meta"], dependencies=[Depends(require_pipeline_key)])


@router.get("/sites/{site_id}/available-dates", response_model=AvailableDatesOut)
def available_dates(
    site_id: str,
    customer_id: str = Query(...),
    schema: Literal["vrm", "monitoring"] = Query("vrm"),
    actor: Literal["customer", "admin"] = Query("customer"),
) -> AvailableDatesOut:
    if schema == "monitoring":
        # Same reasoning as routers/reports.py's schema=="monitoring" gate:
        # a customer-actor request must never reach the monitoring schema
        # (PLAN_PHASE14.md §1.12 rule 2). `monitoring` sites have no
        # `vrm.customers` owner, so there is no ownership fact to check here
        # — `tenancy.get_customer(customer_id)` only confirms `customer_id`
        # names a real row (the same "must be real, not tied to this site"
        # contract `routers/reports.py` already requires for a monitoring
        # report job's `vrm.jobs.customer_id` FK).
        if actor != "admin":
            raise HTTPException(status_code=403, detail="monitoring schema requires actor=admin")
        tenancy.get_customer(customer_id)
    else:
        # customer_id as a required query param, not just the path's site_id,
        # is this endpoint's independent tenancy check (PLAN_PHASE14.md §1.3) —
        # a site_id alone, however it got into the URL, is never enough on its
        # own to read another customer's ingestion history.
        tenancy.assert_owns_site(customer_id, site_id)
    return AvailableDatesOut(dates=rdb.get_available_dates(site_id, schema))


@router.get("/sites", response_model=SitesOut)
def list_sites(
    schema: Literal["vrm", "monitoring"] = Query("vrm"),
    actor: Literal["customer", "admin"] = Query("customer"),
) -> SitesOut:
    """Cross-*customer* site list for one schema — always cross-tenant by
    construction (there is no `customer_id` filter, unlike everything else
    in this router), so this is admin-only regardless of `schema`: a
    `schema="vrm"` call here would hand back every customer's site names in
    one shot, which is exactly the kind of unscoped result set
    PLAN_PHASE14.md §1.2 rule 4 exists to make impossible. In practice
    `/admin/reports` only calls this for `schema="monitoring"` — the `vrm`
    branch is only reachable from Next.js as a matter of admin.ts's own
    `listAllSites()` (which returns full rows, not this thin summary) never
    calling out to `vrm_api` at all — but the gate is unconditional here
    rather than schema-conditional, because "unscoped" is the actual hazard,
    not "monitoring" specifically.
    """
    if actor != "admin":
        raise HTTPException(status_code=403, detail="cross-tenant site list requires actor=admin")
    rows = rdb.list_sites(schema, active_only=False)
    # `owner` only means anything for `schema="monitoring"` (PLAN_PHASE15.md
    # bug-fix pass, Bug 3) — `rdb.list_sites()` already selects `*`, so a
    # `vrm` row simply has no `owner` key and `.get()` returns `None`, same
    # as any other column one schema has and the other doesn't.
    return SitesOut(sites=[
        SiteSummaryOut(site_id=r["site_id"], display_name=r["display_name"], owner=r.get("owner"))
        for r in rows
    ])


@router.get("/limits", response_model=LimitsOut)
def limits() -> LimitsOut:
    return LimitsOut(
        max_custom_range_days=rdb.MAX_CUSTOM_RANGE_DAYS,
        max_overview_range_days=rdb.MAX_OVERVIEW_RANGE_DAYS,
    )
