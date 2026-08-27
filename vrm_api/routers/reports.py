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
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from database import vrm_report_db as rdb
from database.supabase_client import get_client

from victron import weekly_report

from vrm_api import jobs, report_runs, storage, tenancy
from vrm_api.branding import resolve_branding
from vrm_api.deps import require_pipeline_key
from vrm_api.report_delivery import notify_cap_reached_once, send_report_email
from vrm_api.report_limits import check_manual_cap, check_scheduled_cap, resolve_billing_period, resolve_limits
from vrm_api.report_modules import resolve_report_modules
from vrm_api.report_schedule import compute_due_period
from vrm_api.schemas import (
    JobCreated, ReportRequest, ReportRunSiteResult, ReportsRunDueOut, ReportsRunDueRequest,
)

logger = logging.getLogger("vrm_api.reports")

router = APIRouter(prefix="/v1/reports", tags=["reports"],
                   dependencies=[Depends(require_pipeline_key)])

_SCHEMA = "vrm"

# §3.6's entitlement gate, restated here as the same DENYLIST branding.py's
# resolve_branding() uses (and for the identical reason: the naive allowlist
# version silently excludes billing_status='none'/NULL, which is every
# legacy, hand-created, Oscar-invited customer — see that module's own
# comment). Kept as its own copy rather than an import: this endpoint's
# entitlement question also includes vrm.sites.active, which branding.py's
# customer-only gate has no reason to know about.
_NOT_ENTITLED_STATUSES = {"incomplete", "unpaid", "canceled"}

# §3.4: once exceeded, stop STARTING new sites (already-started work is
# never aborted mid-way) and return with remaining > 0. jobs.py's own
# comment budgets a single report at "well under a minute" — 240s leaves
# headroom for several slow ones inside one HTTP request before any
# reasonable caller's timeout would fire.
_WALL_CLOCK_BUDGET_SECONDS = 240


def _t(name: str):
    return get_client().schema(_SCHEMA).table(name)


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
            # Added 2026-08-19: this router's field list predates
            # `battery_kwh_available` (PLAN_PHASE15.md §4.6) — without it,
            # a VRM-API-ingested site's "discharge": 0.0 (fabricated-safe
            # value, not a real reading — see weekly_report.py's own guard)
            # is indistinguishable on the frontend from a real zero, and the
            # energy-mix bar renders "Batería · 0 kWh (0%)" as if confirmed.
            "batteryKwhAvailable": tot["batteryKwhAvailable"],
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


def _do_report(site_id: str, start: str, end: str, schema_: str, customer_id: str,
               *, include_pdf_bytes: bool = False, site: dict | None = None) -> dict:
    # PLAN_PHASE17.md §4.2/§8 Step 4 — resolved ONCE, here, at the top of
    # every report path, regardless of who asked for it (`actor='customer'`
    # or `'admin'` both get the customer's real branding, since this is the
    # actual PDF that would be delivered). `monitoring` reports have no
    # `vrm.customers` owner at all (this router's own module docstring) and
    # always get `None` — the Pauly & Co defaults, unconditionally.
    # `victron/weekly_report.py` never sees `customer_row['branding']`
    # directly — only this function's resolved output, or `None`.
    #
    # PLAN_PHASE18.md §2/§3 — `selected` is resolved the SAME way, right
    # here, for the identical reason: this is the one function every real
    # report path (manual `post_report()`, scheduled `post_run_due()`) goes
    # through, so it's the only place that can guarantee personalization is
    # never silently skipped. Found live (2026-08-27): Steps 1-5 built the
    # whole selection/entitlement/UI chain but never wired THIS call site to
    # actually read it — `render_pdf()` was always called with its default
    # (`selected=None`, every module on), so a saved selection had zero
    # effect on any real report. `site` is optional and defaults to `None`
    # (falls back to "every module on," the identical pre-fix behavior) only
    # because a future caller might not have it handy yet — both of TODAY's
    # real callers already fetch the full site row for other reasons and
    # pass it in below, at zero extra query cost.
    customer = tenancy.get_customer(customer_id) if schema_ == "vrm" else None
    branding = resolve_branding(customer) if customer else None
    selected = resolve_report_modules(customer, site) if (customer and site) else None
    data = weekly_report.build_report_data(site_id, start, end, schema_, branding=branding)
    pdf_bytes = weekly_report.render_pdf(data, selected)
    storage_path = storage.upload_report_pdf(site_id, start, end, pdf_bytes)
    result = {
        "storage_path": storage_path,
        "is_overview": bool(data.get("isOverview")),
        "start": data.get("startStr"),
        "end": data.get("endStr"),
        "summary": _report_summary(data),
        # Additive (PLAN_PHASE17.md §8 Step 8) — `branding` is JSON-safe
        # (plain strings/None) and harmless in a `post_report()` job's
        # persisted result; every existing caller already ignores unknown
        # keys. `post_run_due()` is the only reader — the SAME resolved
        # branding used to render THIS pdf (never re-resolved — this
        # function's own docstring: "resolved ONCE"), so the report email
        # and the PDF are always in agreement.
        "branding": branding,
    }
    if include_pdf_bytes:
        # NOT included by default: `post_report()`'s call site runs through
        # `jobs.run_job()`, which `_jsonable()`s this whole dict into
        # `vrm.jobs.result` AND returns it to a customer's browser via job
        # polling — raw PDF bytes in there would silently mangle into a
        # multi-megabyte garbage string (`json.dumps(..., default=str)` on
        # a `bytes` object) on every single poll. Only `post_run_due()`
        # (a synchronous call, never routed through `jobs.run_job()`) opts
        # in, to attach the PDF it just rendered to the report email
        # without a second Storage round trip to re-download what it just
        # uploaded.
        result["pdf_bytes"] = pdf_bytes
    return result


@router.post("", response_model=JobCreated)
def post_report(body: ReportRequest, background_tasks: BackgroundTasks) -> JobCreated:
    if body.schema_ == "monitoring" and body.actor != "admin":
        # 403, not 422: this is an authorization decision (who is allowed to
        # ask for monitoring data), not a malformed request — a caller
        # should be able to tell the two apart.
        raise HTTPException(status_code=403, detail="monitoring schema requires actor=admin")

    # PLAN_PHASE18.md §3 — captured (not discarded) specifically so
    # `_do_report()` below can resolve this customer's module selection
    # without a second `vrm.sites` query, per `assert_owns_site()`'s own
    # docstring ("Returns the site row on success so callers that need it
    # (report generation, ...) don't pay for a second query").
    site_row: dict | None = None
    if body.schema_ == "vrm":
        # The real tenancy re-check (PLAN_PHASE14.md §1.3): customer_id must
        # own site_id in vrm.sites, independently of whatever Next.js
        # already checked. `monitoring` sites have no vrm.customers owner —
        # the actor=="admin" gate above is the only guard that applies to
        # them, by design (PLAN_PHASE14.md §1.12 rule 2).
        site_row = tenancy.assert_owns_site(body.customer_id, body.site_id)
    else:
        tenancy.get_customer(body.customer_id)

    if body.actor == "customer":
        # Cap A's vrm_api-side ceiling (PLAN_PHASE17.md §2.2) — a SECOND,
        # higher rate limit, independent of app/api/pipeline/reports/
        # route.ts's own lower one. Not redundancy: this is vrm_api's own
        # trust boundary, and Next.js is only today's caller.
        # actor=="admin" (/admin/reports) is exempt by design — the guard
        # above already forces actor=="admin" whenever schema_=="monitoring",
        # so this branch only ever fires for a real vrm-schema customer.
        customer = tenancy.get_customer(body.customer_id)
        check_manual_cap(body.customer_id, customer.get("plan"))

    job = jobs.create_job("report", customer_id=body.customer_id, site_id=body.site_id,
                          params=body.model_dump(by_alias=True))
    background_tasks.add_task(
        jobs.run_job, job["id"],
        lambda: _do_report(body.site_id, body.start, body.end, body.schema_, body.customer_id, site=site_row),
    )
    return JobCreated(job_id=job["id"])


def _site_has_data(site_id: str, start: str, end: str) -> bool:
    """PLAN_PHASE17.md §3.5's `skipped_no_data` PRE-check — called before any
    report work starts, so a no-data period costs one cheap query and no
    Anthropic call, rather than being caught from
    `build_report_data()`'s own `ValueError`. `schema` is always `"vrm"`
    here: the scheduler only ever runs for `source='vrm_api'` sites (§0.7),
    and `monitoring` sites have no `report_schedule` column at all."""
    return bool(rdb.get_energy_daily(site_id, start, end, "vrm"))


def _is_schedule_entitled(customer: dict, site: dict) -> bool:
    """PLAN_PHASE17.md §3.6 — read `_NOT_ENTITLED_STATUSES` above before this
    function: it is stated as a DENYLIST on purpose, so `billing_status`
    `'none'`/`NULL` (every legacy, hand-created, Oscar-invited customer)
    keeps generating rather than being silently excluded by a naive
    allowlist. The scheduler never calls ONVO or `reconcile_customer()` to
    answer this — it reads the derived cache `apply_entitlements()` already
    maintains, same as `branding.py`'s own entitlement check."""
    if not customer.get("active"):
        return False
    if customer.get("provisioning_state") != "active":
        return False
    if not site.get("active"):
        return False
    if customer.get("billing_status") in _NOT_ENTITLED_STATUSES:
        return False
    return True


def _safe_run_due_error(exc: Exception) -> str:
    """Customer-safe text for `vrm.report_runs.error` — same allow-list
    discipline as `jobs.py:_safe_error_message()`, applied directly here
    rather than through that function: `run-due` is synchronous, not a
    `vrm.jobs` background task, so its exceptions never pass through that
    function at all."""
    from victron.vrm_csv import VrmCsvError

    from vrm_api.tenancy import NotAuthorized

    if isinstance(exc, (VrmCsvError, NotAuthorized)):
        return str(exc)
    if isinstance(exc, ValueError):
        # build_report_data()'s own "No energy_daily rows for ..." —
        # normally pre-empted by _site_has_data() above, but if data
        # disappears in the gap between that check and the render, this
        # message is already customer-safe as written.
        return str(exc)
    return "Internal error generating this report — see server logs."


@router.post("/run-due", response_model=ReportsRunDueOut)
def post_run_due(body: ReportsRunDueRequest) -> ReportsRunDueOut:
    """PLAN_PHASE17.md §3.4 — the scheduled-reports fan-out. Modeled on
    `routers/vrm_sync.py:post_run_due()` (read that function's own
    docstring first); the differences are batching (a report is slow — an
    Anthropic call + a weather fetch + a WeasyPrint render — a sync attempt
    is not), a wall-clock budget alongside the site-count one, and the
    fuller status vocabulary §3.4 defines.

    The candidate query is §0.7's guarantee proven at the QUERY level, not
    just the schema level: `source='vrm_api'` is filtered here defensively,
    even though migration 026's `sites_scheduled_reports_require_vrm_api`
    CHECK already makes a CSV-sourced site with a live schedule
    unrepresentable — such a row could never exist for this query to return
    in the first place.

    Budget accounting: only a DUE site counts against `max_sites`/the
    wall-clock budget — a `skipped_not_due` site is one date comparison and
    is never the reason a real due site gets deferred to the next call. The
    budget check runs BEFORE `report_runs.claim_period()` is ever called for
    a site, on purpose: claiming first and bailing on budget second would
    leave that row stuck in `running` with nothing to un-claim it.
    """
    candidates = (_t("sites").select("*")
                 .neq("report_schedule", "off")
                 .eq("active", True)
                 .eq("source", "vrm_api")
                 .order("site_id")
                 .execute().data or [])

    now_utc = datetime.now(timezone.utc)
    start_time = time.monotonic()
    results: list[ReportRunSiteResult] = []
    attempted = 0

    for site in candidates:
        site_id = site["site_id"]
        try:
            period = compute_due_period(
                schedule=site["report_schedule"],
                weekday=site["report_schedule_weekday"],
                day_of_month=site["report_schedule_day_of_month"],
                hour=site["report_schedule_hour"],
                tz_name=site.get("timezone") or "UTC",
                now_utc=now_utc,
            )
        except Exception:  # noqa: BLE001 — §3.3: a bad timezone value (or any
            # other arithmetic surprise) fails THIS site only, no ledger row
            # (there is no period to key one on).
            logger.exception("reports/run-due: period arithmetic failed for site %s", site_id)
            results.append(ReportRunSiteResult(
                site_id=site_id, status="failed",
                error="Couldn't schedule this site — check its timezone setting.",
            ))
            continue

        if period is None:
            results.append(ReportRunSiteResult(site_id=site_id, status="skipped_not_due"))
            continue

        if attempted >= body.max_sites or (time.monotonic() - start_time) > _WALL_CLOCK_BUDGET_SECONDS:
            # §3.4: stop STARTING new sites. Everything from here on
            # (including this site) is left for the next call — `remaining`
            # below is what tells the caller that.
            break
        attempted += 1

        period_start, period_end = period
        claimed = report_runs.claim_period(
            site["customer_id"], site_id, site["report_schedule"],
            period_start.isoformat(), period_end.isoformat(),
        )
        if claimed is None:
            # Already done/abandoned/genuinely in-progress this instant —
            # the idempotency guarantee (§3.2/§5.2): a second back-to-back
            # or concurrent call produces zero new reports for this period.
            # `done`/`abandoned` are real, meaningfully different terminal
            # outcomes worth reporting as themselves (the 4th run of an
            # abandoned site must show `abandoned`, not a generic skip); a
            # genuinely in-flight `running` row collapses to
            # `skipped_not_due` — §3.4's vocabulary has no slot for "someone
            # else is handling this right now".
            existing = report_runs.existing_status(site_id, period_end.isoformat())
            status = existing if existing in ("done", "abandoned") else "skipped_not_due"
            results.append(ReportRunSiteResult(site_id=site_id, status=status))
            continue

        run_id = claimed["id"]
        try:
            customer = tenancy.get_customer(site["customer_id"])

            if not _is_schedule_entitled(customer, site):
                report_runs.record_skipped(run_id, "skipped_not_entitled")
                results.append(ReportRunSiteResult(site_id=site_id, status="skipped_not_entitled"))
                continue

            cap_start, cap_end = resolve_billing_period(site["customer_id"], customer.get("country"))
            if not check_scheduled_cap(site["customer_id"], customer.get("plan"), cap_start, cap_end):
                report_runs.record_skipped(run_id, "skipped_capped")
                # PLAN_PHASE17.md §0.6 Q7 — ONE notification per customer
                # per billing period, gated inside this call itself (never
                # raises); every OTHER site of this customer's that also
                # lands here this tick is a no-op past the first.
                notify_cap_reached_once(customer, resolve_limits(customer.get("plan"))["scheduled_reports_per_period"], cap_end)
                results.append(ReportRunSiteResult(site_id=site_id, status="skipped_capped"))
                continue

            if not _site_has_data(site_id, period_start.isoformat(), period_end.isoformat()):
                report_runs.record_skipped(run_id, "skipped_no_data")
                results.append(ReportRunSiteResult(site_id=site_id, status="skipped_no_data"))
                continue

            report_result = _do_report(site_id, period_start.isoformat(), period_end.isoformat(),
                                       "vrm", site["customer_id"], include_pdf_bytes=True, site=site)
            # PLAN_PHASE17.md §8 Step 8 — never raises (see its own module
            # docstring): a delivery failure must never lose the already-
            # generated, already-uploaded report. `email_status`/
            # `recipients` land on this SAME ledger row as the generation
            # outcome, not a second one.
            email_status, email_recipients = send_report_email(
                customer, site, report_result["branding"], report_result["summary"],
                report_result["pdf_bytes"], period_start.isoformat(), period_end.isoformat(),
            )
            report_runs.record_done(run_id, report_result["storage_path"],
                                    recipients=email_recipients, email_status=email_status)
            _t("sites").update({
                "report_last_period_end": period_end.isoformat(),
                "report_last_run_at": datetime.now(timezone.utc).isoformat(),
            }).eq("site_id", site_id).execute()
            results.append(ReportRunSiteResult(site_id=site_id, status="done"))
        except Exception as exc:  # noqa: BLE001 — per-site isolation (§3.4,
            # the Phase 12 gate): one site's failure must not block the rest.
            logger.exception("reports/run-due: site %s failed", site_id)
            safe_message = _safe_run_due_error(exc)
            report_runs.record_failed(run_id, claimed["attempt_count"], safe_message)
            final_status = "abandoned" if claimed["attempt_count"] >= report_runs.MAX_ATTEMPTS else "failed"
            results.append(ReportRunSiteResult(site_id=site_id, status=final_status, error=safe_message))

    return ReportsRunDueOut(
        sites_checked=len(candidates),
        processed=len(results),
        remaining=len(candidates) - len(results),
        results=results,
    )
